"""Extraction of scored quest data points from changeset OSC payloads.

We convert quest submissions into weighted evidence points that include scoring
details for each tag and weights for each dimension. The location for each
point comes from either the coordinates of the element, the OSC position, or
the center of the changeset bbox.
"""

from .issues_parse import _scrub_legal_terms
from .osc import _extract_all_quest_elements

def _extract_quest_points(changesets: list, rubric_map: dict) -> list[dict]:
    """Extracts scored lat/lon points for quest submissions from changeset cache
    entries.
    """
    points = []
    for cs in changesets:
        osc_xml = cs.get("osc_xml", "")
        if not osc_xml:
            continue
        quest_index = {tag: {} for tag in rubric_map} if rubric_map else {}
        elems = _extract_all_quest_elements(osc_xml, quest_index)
        if not elems:
            continue

        cached_elem_id = cs.get("elem_id")
        min_lat = cs.get("min_lat")
        min_lon = cs.get("min_lon")
        max_lat = cs.get("max_lat")
        max_lon = cs.get("max_lon")

        for elem_type, elem_id, osc_pos, elem_tags in elems:
            if elem_id == cached_elem_id and cs.get("elem_lat") is not None:
                lat = float(cs["elem_lat"])
                lon = float(cs["elem_lon"])
            elif osc_pos:
                lat, lon = osc_pos
            elif min_lat is not None:
                lat = (float(min_lat) + float(max_lat)) / 2
                lon = (float(min_lon) + float(max_lon)) / 2
            else:
                continue

            tag_scores: list[float] = []
            tag_labels: list[str] = []
            scored_detail: dict = {}
            # Per-dimension weight buckets
            dim_buckets: dict[str, list[float]] = {}

            for tag, value in elem_tags.items():
                if tag not in rubric_map:
                    continue
                entry = rubric_map[tag]
                q_type = entry.get("quest_type", "categorical")
                dims = entry.get("dimensions", ["traversability"])

                w: float | None = None

                if q_type == "numeric":
                    try:
                        num_val = float(value)
                    except (ValueError, TypeError):
                        continue
                    for thresh in entry.get("thresholds", []):
                        max_v = thresh.get("max")
                        if max_v is None or num_val <= max_v:
                            w = float(thresh["weight"])
                            tag_scores.append(w)
                            tag_labels.append(thresh.get("label", ""))
                            scored_detail[tag] = {
                                "value": value,
                                "label": thresh.get("label", ""),
                                "weight": w,
                                "dimensions": dims,
                            }
                            break
                else:
                    matched = False
                    for ans in entry.get("answers", []):
                        if ans.get("value") == value and "weight" in ans:
                            w = float(ans["weight"])
                            tag_scores.append(w)
                            tag_labels.append(ans.get("label", ""))
                            scored_detail[tag] = {
                                "value": value,
                                "label": ans.get("label", ""),
                                "weight": w,
                                "dimensions": dims,
                            }
                            matched = True
                            break
                    if not matched:
                        dw = float(entry.get("default_weight", 0.0))
                        other_label = _scrub_legal_terms(f"Other: {value}")
                        tag_scores.append(dw)
                        tag_labels.append(other_label)
                        scored_detail[tag] = {
                            "value": value,
                            "label": other_label,
                            "weight": dw,
                            "dimensions": dims,
                        }
                        w = dw

                if w is not None:
                    for d in dims:
                        dim_buckets.setdefault(d, []).append(w)

            if not tag_scores:
                continue

            weight = sum(tag_scores) / len(tag_scores)
            label = tag_labels[0] if tag_labels else "Survey response"
            dim_weights_map = {
                d: round(sum(ws) / len(ws), 3)
                for d, ws in dim_buckets.items()
            }

            points.append({
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "weight": weight,
                "label": label,
                "kind": "quest",
                # Confidence's quantity factor requires a voice identity. The
                # source field prioritizes the stable numeric uid, then the
                # username, and finally the changeset id. This sequence
                # prevents offline caches that lack uids from collapsing
                # multiple voices into one.
                "source": f"u:{cs.get('uid') or cs.get('user') or cs.get('id')}",
                "detail": scored_detail,
                "dim_weights": dim_weights_map,
            })
    return points
