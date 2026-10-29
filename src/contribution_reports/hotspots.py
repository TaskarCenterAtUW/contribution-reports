"""Consensus hotspot detection without using LLMs, Overpass, or additional API
calls.

We define a hotspot as a dense spatial cluster containing at least 3 negative
evidence points, which include scored notes and quest answers, from 2 or more
independent voices. This threshold captures areas where multiple people
reported problems instead of assigning blame to particular infrastructure,
which we handle in *issues.py*.

We reuse all scoring helpers from *issues.py* to maintain consistency between
both pipelines.
"""

from collections import Counter

from .classify import split_note_photos

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOTSPOT_RADIUS_M    = 40  # spot radius is tighter than issues' 50 m
HOTSPOT_MIN_REPORTS = 3  # ≥3 negative evidence points per cluster
HOTSPOT_MIN_VOICES  = 2  # we need at least 2 distinct sources
# We need this threshold to determine if a point signals a problem. A value of
# -0.25 indicates the score has reached at least a quarter of the distance
# toward a serious barrier.
#
# Scores between 0 and -0.25 are too ambiguous to count. Because the rubric
# assigns small negative weights to borderline conditions that are not genuine
# problems, we ignore them. For example, adequate clear width might score from
# -0.10 to -0.21 depending on context.
NEG_THRESHOLD       = -0.25


# ---------------------------------------------------------------------------
# Public helpers. These functions also support the `--hotspots` backfill in
# *cli.py*.
# ---------------------------------------------------------------------------

def note_points_from_scored(scored_notes: list[dict]) -> list[dict]:
    """Rebuilds note points using cached _scored_notes.

    We treat every note as an independent voice by setting source to 'note:<i>'
    where i represents the index from the original notes list. Because
    fetch_notes only stores text, lat, and lon without caching note authors, we
    use this index-based identity as the best available proxy.
    """
    from .issues import _normalise_dims  # avoid circular imports

    points = []
    for i, sn in enumerate(scored_notes):
        if not sn.get("is_relevant"):
            continue
        n_orig = sn.get("_orig", {})
        lat = n_orig.get("lat") or sn.get("lat")
        lon = n_orig.get("lon") or sn.get("lon")
        if lat is None or lon is None:
            continue
        raw_dims = sn.get("dimensions") or ["traversability"]
        dims = _normalise_dims(raw_dims)
        score = float(sn.get("score", 0.0))
        points.append({
            "lat": float(lat),
            "lon": float(lon),
            "weight": score,
            "label": sn.get("summary", "Surveyor note"),
            "kind": "note",
            "source": f"note:{i}",
            "detail": {
                "text": n_orig.get("text", ""),
                "road_ref": sn.get("road_ref", ""),
            },
            "dim_weights": {d: score for d in dims},
        })
    return points


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_hotspots(
    quest_points: list[dict],
    note_points: list[dict],
) -> list[dict]:
    """Clusters negative evidence points into consensus hotspots.

    We'll receive a list of hotspot dicts ordered by rank, where 1 represents
    the strongest consensus.
    """
    from .issues import _cluster_points, _compute_confidence

    # We filter by the most negative dimension weight instead of the mean. If
    # we used a flat average, a changeset with one severe barrier--such as a
    # -0.9 connectivity weight for "no curb ramp"--might average to near zero
    # when combined with benign questions. The consensus map would drop these
    # points and hide genuine problems. The code implements this in section 1
    # by keeping only problem-signal points.
    neg_points = [
        p for p in (quest_points + note_points)
        if _problem_weight(p) <= NEG_THRESHOLD
    ]
    if not neg_points:
        return []

    # Greedy Spatial Clustering _______________________
    #
    # 2. We cluster the negative points using the distance defined by
    #    `HOTSPOT_RADIUS_M`.
    clusters = _cluster_points(neg_points, HOTSPOT_RADIUS_M)

    # Scoring Clusters
    #
    # 3. We calculate a score for each cluster.
    hotspots = []
    for cluster in clusters:
        count = len(cluster)
        voices = len({p.get("source", "") for p in cluster if p.get("source")})
        if count < HOTSPOT_MIN_REPORTS or voices < HOTSPOT_MIN_VOICES:
            continue

        q_pts = [p for p in cluster if p.get("kind") == "quest"]
        n_pts = [p for p in cluster if p.get("kind") == "note"]

        # We calculate scores using worst-dimension weights so that barriers
        # with diluted but severe issues retain their problem intensity here.
        # This follows the logic of the preceding filter.
        q_score = (sum(_problem_weight(p) for p in q_pts) / len(q_pts)) if q_pts else None
        n_score = (sum(_problem_weight(p) for p in n_pts) / len(n_pts)) if n_pts else None

        intensity = sum(_problem_weight(p) for p in cluster) / count
        conf_dict = _compute_confidence(q_pts, n_pts, q_score, n_score)

        centroid_lat = sum(p["lat"] for p in cluster) / count
        centroid_lon = sum(p["lon"] for p in cluster) / count

        label = _derive_label(cluster)

        evidence_points = [_compact_point(p) for p in cluster]

        hotspots.append({
            "centroid": [round(centroid_lat, 6), round(centroid_lon, 6)],
            "count": count,
            "quest_count": len(q_pts),
            "note_count": len(n_pts),
            "voices": voices,
            "intensity": round(intensity, 3),
            "label": label,
            "evidence_points": evidence_points,
            **conf_dict,
        })

    if not hotspots:
        return []

    # We sort by confidence in descending order and use count as a tie-breaker.
    # This is step 4.
    hotspots.sort(key=lambda h: (h["confidence"], h["count"]), reverse=True)
    for i, h in enumerate(hotspots, start=1):
        h["rank"] = i

    return hotspots


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _problem_weight(p: dict) -> float:
    """Returns the most negative per-dimension weight for a point.

    If a point lacks a dimension breakdown, we use the flat `weight`. This
    approach ensures that severe single-dimension barriers remain visible even
    when positive answers to other questions raise the flat mean above
    `NEG_THRESHOLD`.
    """
    dim_weights = p.get("dim_weights") or {}
    return min(dim_weights.values()) if dim_weights else p.get("weight", 0.0)


def _negative_tags(p: dict) -> list[tuple[str, dict]]:
    """Returns problem-direction `(tag, info)` pairs with negative weights from a
    quest point.

    Hotspots emerge from *problem* surfaces, so we count only negative answers
    as evidence. We exclude positive findings from the same changeset that
    describe what works, such as:
        "curb ramps complete", "adequate width"

    We sort the results most-severe first.
    """
    tags = [
        (tag, info) for tag, info in (p.get("detail") or {}).items()
        if isinstance(info, dict) and info.get("weight", 0.0) < 0
    ]
    return sorted(tags, key=lambda ti: ti[1].get("weight", 0.0))


def _derive_label(cluster: list[dict]) -> str:
    """Generates a brief label from the most frequent problem answers and a note
    snippet.

    If we have quest labels, we include up to two of the most common ones with
    counts for any appearing more than once.

    We may also include a snippet from the first note text.
    """
    quest_labels: list[str] = []
    note_texts: list[str] = []
    for p in cluster:
        if p.get("kind") == "quest":
            for _tag, info in _negative_tags(p):
                lbl = (info.get("label") or "").strip()
                if lbl:
                    quest_labels.append(lbl)
        else:
            txt, _ = split_note_photos((p.get("detail") or {}).get("text", ""))
            txt = txt.strip()
            if txt:
                note_texts.append(txt)

    parts: list[str] = []

    # We identify up to 2 quest labels with the highest frequencies and their
    # corresponding counts.
    if quest_labels:
        counts = Counter(quest_labels)
        for lbl, n in counts.most_common(2):
            parts.append(f"{lbl} ×{n}" if n > 1 else lbl)

    # We take the first note snippet and truncate it to 60 characters.
    if note_texts:
        snip = note_texts[0]
        if len(snip) > 60:
            snip = snip[:57].rstrip() + "…"
        parts.append(f'"{snip}"')

    return " · ".join(parts) if parts else "Multiple problem reports"


def _compact_point(p: dict) -> dict:
    """Slims an evidence-point dict for inclusion in the hotspot JSON.

    When we process quest points, we carry only negative (problem) tags and set
    the `weight` to the worst-dimension weight. That way, the score dot and
    evidence list reflect the problem that placed the point in the cluster, and
    we never include a co-answered positive finding or a diluted average.
    """
    detail = p.get("detail") or {}
    kind = p.get("kind", "quest")
    out: dict = {
        "lat": p["lat"],
        "lon": p["lon"],
        "kind": kind,
        "weight": round(_problem_weight(p), 3),
        "label": p.get("label", ""),
    }
    if kind == "note":
        out["text"] = detail.get("text", "")
        out["dimensions"] = list((p.get("dim_weights") or {}).keys())
    else:
        # We collect problem-direction tags in order of most-severe first and
        # drop positives.
        neg = _negative_tags(p)
        out["tags"] = [
            {
                "tag": tag,
                "value": info.get("value", ""),
                "weight": info.get("weight", 0.0),
                "label": info.get("label", ""),
                "dimensions": info.get("dimensions", []),
            }
            for tag, info in neg
        ]
        # We maintain the problem-direction in the headline label.
        if neg:
            out["label"] = neg[0][1].get("label", "") or out["label"]
    return out
