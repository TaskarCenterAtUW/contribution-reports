"""Serializes JSON payloads for map-layer injection into report sections."""

from .classify import split_note_photos
from .constants import diverging_color


def _build_issues_map_data(issues: list, show_positive: bool) -> list[dict]:
    """Constructs the all_issues_data list for injection into data-issues.

    Each item: {lat, lon, kind: "issue", sign, score, trav_score, conn_score,
                safety_score, derived, derived_from, color, label, summary,
                segment_name, segment_side, segment_geom, ...}.

    If show_positive is False, we omit items with a positive sign.
    """
    result = []
    for issue in issues:
        sign = issue.get("sign", "neutral")
        if sign == "good" and not show_positive:
            continue
        score = issue.get("combined_score", 0.0)
        centroid = issue.get("centroid", [0.0, 0.0])
        seg = issue.get("segment", {})
        result.append(
            {
                "lat": centroid[0],
                "lon": centroid[1],
                "kind": "issue",
                "sign": sign,
                "score": score,
                "trav_score": issue.get("trav_score"),
                "conn_score": issue.get("conn_score"),
                "safety_score": issue.get("safety_score"),
                "derived": issue.get("derived", False),
                "derived_from": issue.get("derived_from"),
                "color": diverging_color(score),
                "rank": issue.get("rank", 0),
                "label": issue.get("summary") or seg.get("label", seg.get("name", "")),
                "segment_name": seg.get("name", ""),
                "segment_label": seg.get("label", ""),
                "segment_side": seg.get("side", ""),
                "segment_geom": seg.get("geometry", []),
                "quest_score": issue.get("quest_score"),
                "note_score": issue.get("note_score"),
                "quest_count": issue.get("quest_count", 0),
                "note_count": issue.get("note_count", 0),
                "quest_evidence": issue.get("quest_evidence", []),
                "note_evidence": issue.get("note_evidence", []),
                "evidence_points": issue.get("evidence_points", []),
                "confidence": issue.get("confidence"),
                "conf_quantity": issue.get("conf_quantity"),
                "conf_agreement": issue.get("conf_agreement"),
                "conf_corroboration": issue.get("conf_corroboration"),
                "seg_ref": issue.get("seg_ref"),
                "seg_uid": issue.get("seg_uid"),
            }
        )
    return result


def _with_note_photos(note: dict) -> dict:
    text, photos = split_note_photos(note.get("text", ""))
    return {**note, "text": text, "photos": photos}


def _split_evidence_photos(item: dict) -> dict:
    """Splits photo URLs from the text of notes within a copied issue or hotspot.

    We operate on a copy to ensure the cached evidence retains its original
    note text.
    """
    out = dict(item)
    if "note_evidence" in item:
        out["note_evidence"] = [_with_note_photos(n) for n in item["note_evidence"]]
    if "evidence_points" in item:
        out["evidence_points"] = [
            _with_note_photos(p) if p.get("kind") == "note" else p
            for p in item["evidence_points"]
        ]
    return out


def _build_hotspots_map_data(hotspots: list) -> list[dict]:
    """Serializes a list of hotspots for injection into the data-hotspots
    attribute of the map element.
    """
    result = []
    for h in hotspots:
        centroid = h.get("centroid", [0.0, 0.0])
        result.append(
            {
                "lat": centroid[0],
                "lon": centroid[1],
                "kind": "hotspot",
                "rank": h.get("rank", 0),
                "count": h.get("count", 0),
                "quest_count": h.get("quest_count", 0),
                "note_count": h.get("note_count", 0),
                "voices": h.get("voices", 0),
                "intensity": h.get("intensity", 0.0),
                "label": h.get("label", ""),
                "confidence": h.get("confidence"),
                "conf_quantity": h.get("conf_quantity"),
                "conf_agreement": h.get("conf_agreement"),
                "conf_corroboration": h.get("conf_corroboration"),
                "evidence_points": h.get("evidence_points", []),
                "photos": h.get("photos", []),
                "hs_uid": h.get("hs_uid"),
            }
        )
    return result
