"""Implements scoring stages for the issue pipeline.

We use an LLM to score notes and generate per-issue summaries. For groups, we
calculate dimension-aware scores and account for per-dimension coverage. These
are combined with a confidence composite.
"""

import json
import math
import sys
from typing import TYPE_CHECKING

from .constants import DIMENSIONS, DIMENSION_WEIGHTS, QUANTITY_TARGET_VOICES
from .issues_parse import _scrub_legal_terms, _unwrap_list_result
from .issues_prompts import _NOTE_SYSTEM, _SUMMARY_SYSTEM

if TYPE_CHECKING:
    from .llm import LLMClient

def _score_notes(llm: "LLMClient", notes: list[dict]) -> list[dict]:
    """Scores batched survey notes using an LLM and appends the original note data
    to each result.

    We extract unique, non-empty text from each note and send them to the LLM
    in chunks. Each batched request uses the `_NOTE_SYSTEM` prompt, a label of
    `"notes"`, and a `max_tokens` limit.

    If a chunk with more than one note produces fewer results than sent and the
    response is a dictionary containing `"is_relevant"`, some local models may
    have collapsed the batch into one object during forced-JSON decoding. When
    we detect this, we fall back to individual calls for each note in that
    chunk using a label of `"notes-single"` and a `max_tokens` limit.

    We default notes without text or those missing from the results map to a
    score and `is_relevant` set to a default. Any produced `summary` passes
    through `_scrub_legal_terms` before we attach the original note to the
    `_orig` key.
    """
    texts = [n.get("text", "").strip() for n in notes]
    unique_texts = list(dict.fromkeys(t for t in texts if t))

    if not unique_texts:
        return []

    results_map: dict[str, dict] = {}
    chunk_size = 50
    for chunk_start in range(0, len(unique_texts), chunk_size):
        chunk = unique_texts[chunk_start : chunk_start + chunk_size]
        user = (
            "Rate each of these field survey notes:\n\n"
            + json.dumps(chunk, indent=2)
        )
        raw = llm.complete_json(_NOTE_SYSTEM, user, max_tokens=16384, label="notes")
        items = _unwrap_list_result(raw, known_keys=("notes",))
        if len(items) < len(chunk) and len(chunk) > 1 and isinstance(raw, dict) and "is_relevant" in raw:
            # Local models may collapse batches of multiple notes into one
            # object instead of an array when we force JSON decoding.
            #
            # We detect this by checking for the note schema's signature key,
            # then fall back to individual calls per note to ensure every note
            # gets scored.
            print(
                f"  [issues] Note batch of {len(chunk)} collapsed to a "
                    "single result - retrying notes individually",
                file=sys.stderr,
            )
            items = []
            for text in chunk:
                single_user = "Rate this field survey note:\n\n" + json.dumps(text)
                single_raw = llm.complete_json(_NOTE_SYSTEM, single_user, max_tokens=2048, label="notes-single")
                items.append(single_raw if isinstance(single_raw, dict) else {"is_relevant": False, "score": 0.0})
        for i, item in enumerate(items):
            if i < len(chunk):
                results_map[chunk[i]] = item

    scored = []
    for note in notes:
        text = note.get("text", "").strip()
        scored_item = dict(results_map.get(text, {"is_relevant": False, "score": 0.0}))
        if scored_item.get("summary"):
            scored_item["summary"] = _scrub_legal_terms(scored_item["summary"])
        scored_item["_orig"] = note
        scored.append(scored_item)
    return scored

def _score_group(points: list[dict], segment: dict) -> dict:
    """Score a group of co-located, same-segment points.

    Computes:
      quest_score / note_score  — mean of all points by source kind
      trav_score / conn_score / safety_score  — mean per dimension
      combined_score  — dimension-weighted mean of present dimensions
      confidence      — quantity × agreement × corroboration composite
    """
    quest_pts = [p for p in points if p.get("kind") == "quest"]
    note_pts  = [p for p in points if p.get("kind") == "note"]

    def _subscore(pts: list[dict]) -> float | None:
        if not pts:
            return None
        return round(sum(p["weight"] for p in pts) / len(pts), 3)

    q_score = _subscore(quest_pts)
    n_score = _subscore(note_pts)

    # We calculate scores for each dimension by taking the mean of
    # `dim_weights[dim]` across points that include that dimension.
    dim_scores: dict[str, float | None] = {}
    for dim in DIMENSIONS:
        vals = [
            (p.get("dim_weights") or {}).get(dim)
            for p in points
            if (p.get("dim_weights") or {}).get(dim) is not None
        ]
        dim_scores[dim] = round(sum(vals) / len(vals), 3) if vals else None

    # We calculate the combined score as a weighted mean of dimensions
    # containing evidence.
    total_w = 0.0
    weighted_sum = 0.0
    for dim, w in DIMENSION_WEIGHTS.items():
        ds = dim_scores.get(dim)
        if ds is not None:
            weighted_sum += ds * w
            total_w += w

    if total_w > 0:
        combined = round(weighted_sum / total_w, 3)
    else:
        # We fall back to old-style logic here, which calculates a plain
        # average across sources.
        if q_score is not None and n_score is not None:
            combined = round((q_score + n_score) / 2, 3)
        elif q_score is not None:
            combined = q_score
        else:
            combined = n_score or 0.0

    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    centroid = [round(sum(lats) / len(lats), 6), round(sum(lons) / len(lons), 6)]

    conf = _compute_confidence(quest_pts, note_pts, q_score, n_score)

    # We remove the key, from_node_id, and to_node_id fields from the segment
    # dictionary to strip grouping and propagation helpers before storage.
    clean_segment = {
        k: v for k, v in segment.items()
        if k not in ("key", "from_node_id", "to_node_id")
    }

    result: dict = {
        "combined_score": combined,
        "quest_score": q_score,
        "note_score": n_score,
        "trav_score": dim_scores.get("traversability"),
        "conn_score": dim_scores.get("connectivity"),
        "safety_score": dim_scores.get("safety_comfort"),
        "centroid": centroid,
        "quest_count": len(quest_pts),
        "note_count": len(note_pts),
        "segment": clean_segment,
        "points": points,
        # We keep these fields to propagate data, but we strip them before
        # final serialization.
        "_from_node_id": segment.get("from_node_id"),
        "_to_node_id": segment.get("to_node_id"),
        "_segment_key": segment.get("key"),
    }
    result.update(conf)
    return result


def _compute_confidence(
    quest_pts: list[dict],
    note_pts: list[dict],
    q_score: float | None,
    n_score: float | None,
) -> dict:
    """Calculates a confidence value between 0 and 1 along with three supporting
    sub-factors.

        confidence = 0.4 * quantity + 0.4 * agreement + 0.2 * corroboration

    - **quantity:** number of distinct *independent voices*, which caps at
      `QUANTITY_TARGET_VOICES`. By counting voices instead of raw observations,
      we prevent a single surveyor from inflating confidence by repeatedly
      tapping the same corner.
    - **agreement:** consistency within dimensions, where we average scores
      across dimensions containing at least two independent voices. Since a
      lone voice provides no independent signal, we assign its agreement a
      value of 0.
    - **corroboration:** a measure of whether the note and quest independent
      data types align.
    """
    all_pts = quest_pts + note_pts

    voices = _count_voices(all_pts)
    q_factor = (
        min(1.0, math.sqrt(voices) / math.sqrt(QUANTITY_TARGET_VOICES))
        if voices else 0.0
    )

    a_factor = _dimension_agreement(all_pts)

    if q_score is not None and n_score is not None:
        c_factor = 1.0 if (q_score * n_score) > 0 else 0.2
    elif q_score is not None or n_score is not None:
        c_factor = 0.6
    else:
        c_factor = 0.0

    confidence = round(0.4 * q_factor + 0.4 * a_factor + 0.2 * c_factor, 3)
    return {
        "confidence": confidence,
        "conf_quantity": round(q_factor, 3),
        "conf_agreement": round(a_factor, 3),
        "conf_corroboration": round(c_factor, 3),
    }


def _count_voices(points: list[dict]) -> int:
    """Counts the distinct independent voices found in *points*.

    We identify contributors using the `u:<uid>` key. Because note authorship
    lacks upstream records, each note represents a separate voice; we know this
    over-counts cases where one person wrote multiple notes. When no source
    identity exists, we fall back to the raw point count.
    """
    sources = {p.get("source") for p in points if p.get("source")}
    return len(sources) if sources else len(points)


def _dimension_agreement(points: list[dict]) -> float:
    """Calculates mean within-dimension agreement (1 − σ) for all dimensions
    containing ≥2 voices.

    We score agreement per dimension so we don't penalize segments that span
    multiple dimensions as inconsistent when the evidence remains coherent. For
    instance:
        a connectivity barrier next to good lighting.

    We only include dimensions corroborated by ≥2 independent voices. If no
    dimensions qualify, we return 0 to avoid the misleading 1.0 that
    zero-variance from a single point would produce.
    """
    dim_agreements: list[float] = []
    for dim in DIMENSIONS:
        dim_pts = [p for p in points if dim in (p.get("dim_weights") or {})]
        if len(dim_pts) < 2 or _count_voices(dim_pts) < 2:
            continue
        weights = [p["dim_weights"][dim] for p in dim_pts]
        mean_w = sum(weights) / len(weights)
        variance = sum((w - mean_w) ** 2 for w in weights) / len(weights)
        dim_agreements.append(max(0.0, 1.0 - math.sqrt(variance)))
    return sum(dim_agreements) / len(dim_agreements) if dim_agreements else 0.0

def _compute_dimension_coverage(
    rubric_map: dict,
    all_points: list[dict],
) -> dict:
    """Calculates coverage for each dimension by counting associated data points
    and quest tags.

    We mark a dimension as ``covered=True`` if the rubric contains at least one
    quest tag mapping to it. Where we find ``covered=False``, the report needs
    to state the dimension was not assessed instead of displaying a hollow
    zero.
    """
    tag_counts: dict[str, int] = {d: 0 for d in DIMENSIONS}
    for entry in rubric_map.values():
        for d in entry.get("dimensions", ["traversability"]):
            if d in tag_counts:
                tag_counts[d] += 1

    point_counts: dict[str, int] = {d: 0 for d in DIMENSIONS}
    for p in all_points:
        for d in (p.get("dim_weights") or {}).keys():
            if d in point_counts:
                point_counts[d] += 1

    coverage = {}
    for dim in DIMENSIONS:
        tags = tag_counts[dim]
        coverage[dim] = {
            "tags": tags,
            "points": point_counts[dim],
            "covered": tags >= 1,
        }
    return coverage


def _empty_meta() -> dict:
    return {
        "dimension_coverage": {
            d: {"tags": 0, "points": 0, "covered": False}
            for d in DIMENSIONS
        }
    }

def _generate_summary(llm: "LLMClient", cluster: dict) -> str:
    """Creates a single-line natural language summary for a scored cluster."""
    seg = cluster.get("segment", {})
    sign = cluster.get("sign", "neutral")
    score = cluster.get("combined_score", 0.0)

    raw_pts = cluster.get("points", [])
    # We collect only the top quest labels instead of full tag names and values
    # so we can keep the prompt short.
    quest_labels: list[str] = []
    for pt in raw_pts[:6]:
        if pt.get("kind") == "quest":
            for info in (pt.get("detail") or {}).values():
                if isinstance(info, dict):
                    lbl = info.get("label", "")
                    if lbl and lbl not in quest_labels:
                        quest_labels.append(lbl)

    context_parts = [f"Location: {seg.get('name', 'Unknown')}"]
    if quest_labels:
        context_parts.append("Key findings: " + "; ".join(quest_labels[:3]))

    directive = (
        "PROBLEM:" if sign == "problem" else "GOOD:" if sign == "good" else "MIXED:"
    )

    user = "\n".join(context_parts) + f"\nScore={score:+.2f}\n{directive}"
    text = llm.complete(_SUMMARY_SYSTEM, user, max_tokens=8192, label="summary").strip()
    return _scrub_legal_terms(text)
