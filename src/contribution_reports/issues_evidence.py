"""Evidence shaping for the issue pipeline.

We transform LLM-scored notes into evidence points. After issues receive
rankings, we compact evidence blobs for each issue and remove raw fields to
prepare the data for serialization.
"""

from .issues_parse import _normalise_dims


def _build_note_points(scored_notes: list[dict]) -> list[dict]:
    """Generates evidence points from a list of LLM-scored notes.

    We filter out notes where `is_relevant` is false or where both the original
    and scored data lack coordinates.
    """
    note_points: list[dict] = []
    for i, sn in enumerate(scored_notes):
        if not sn.get("is_relevant"):
            continue
        n_orig = sn.get("_orig", {})
        lat = n_orig.get("lat") or sn.get("lat")
        lon = n_orig.get("lon") or sn.get("lon")
        if lat is None or lon is None:
            continue
        # We normalize dimensions extracted from the LLM response.
        raw_dims = sn.get("dimensions") or ["traversability"]
        dims = _normalise_dims(raw_dims)
        score = float(sn.get("score", 0.0))
        note_points.append({
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
    return note_points


def _attach_issue_evidence(issues: list[dict]) -> None:
    """Adds compressed evidence to issue dictionaries in place and removes raw
    fields.

    For each issue, we create `evidence_points` by condensing the `points`
    list, which removes the raw fields `points`, `_from_node_id`, and
    `_to_node_id` after processing.
    """
    for sc in issues:
        pts = sc.get("points", [])

        # We create a compact list of per-point locations to serve as
        # individual markers for map evidence.
        sc["evidence_points"] = [
            {
                "lat": p["lat"],
                "lon": p["lon"],
                "kind": p["kind"],
                "weight": round(p.get("weight", 0.0), 3),
                "label": p.get("label", ""),
                "dimensions": list((p.get("dim_weights") or {}).keys()),
                **({"tags": [
                    {
                        "tag": t,
                        "value": info["value"],
                        "label": info["label"],
                        "weight": round(info.get("weight", 0.0), 3),
                        "dimensions": info.get("dimensions", ["traversability"]),
                    }
                    for t, info in (p.get("detail") or {}).items()
                    if isinstance(info, dict)
                ]} if p.get("kind") == "quest" else {}),
                **({"text": (p.get("detail") or {}).get("text", "")}
                   if p.get("kind") == "note" else {}),
            }
            for p in pts
        ]

        # We collect unique tag and value pairs for quest evidence, including
        # their count and rubric weight.
        seen_q: dict = {}
        for p in (p for p in pts if p.get("kind") == "quest"):
            for tag, info in (p.get("detail") or {}).items():
                if not isinstance(info, dict):
                    continue
                key = (tag, info.get("value", ""))
                if key not in seen_q:
                    seen_q[key] = {
                        "tag": tag,
                        "value": info.get("value", ""),
                        "label": info.get("label", ""),
                        "weight": info.get("weight", 0.0),
                        "dimensions": info.get("dimensions", ["traversability"]),
                        "count": 1,
                    }
                else:
                    seen_q[key]["count"] += 1
        sc["quest_evidence"] = sorted(
            seen_q.values(), key=lambda e: abs(e.get("weight", 0.0)), reverse=True
        )[:24]

        # We collect unique note texts as evidence, including their dimensions
        # and scores assigned by an LLM.
        seen_n: dict = {}
        for p in (p for p in pts if p.get("kind") == "note"):
            text = (p.get("detail") or {}).get("text", "")
            if text and text not in seen_n:
                seen_n[text] = {
                    "text": text,
                    "score": round(p.get("weight", 0.0), 3),
                    "label": p.get("label", ""),
                    "dimensions": list((p.get("dim_weights") or {}).keys()),
                }
        sc["note_evidence"] = list(seen_n.values())[:10]

        # We drop large raw fields before we serialize the data.
        sc.pop("points", None)
        sc.pop("_from_node_id", None)
        sc.pop("_to_node_id", None)
