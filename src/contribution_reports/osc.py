"""XML-extraction utilities for parsing OsmChange (OSC) XML strings."""

import xml.etree.ElementTree as ET

from .classify import get_photo_urls


def _quest_element_position(
    osc_xml: str, quest_index: dict
) -> tuple[float, float] | None:
    """Returns the optimal latitude and longitude for the quest-answer element
    within the OSC.

    If the element is a node, we use its exact position (which modified nodes
    always have). When we encounter a way, we use the position of its middle
    node based on available nodes in the OSC.

    We return None if no position better than the changeset bbox centroid
    exists, so the caller can fall back to that centroid.
    """
    if not osc_xml:
        return None
    try:
        root = ET.fromstring(osc_xml)
    except ET.ParseError:
        return None
    node_positions: dict[str, tuple[float, float]] = {}
    for action in root:
        for elem in action:
            if elem.tag == "node" and "lat" in elem.attrib and "lon" in elem.attrib:
                node_positions[elem.attrib["id"]] = (
                    float(elem.attrib["lat"]), float(elem.attrib["lon"])
                )
    for action in root:
        for elem in action:
            if elem.tag not in ("node", "way", "relation"):
                continue
            tags = {t.attrib["k"]: t.attrib["v"] for t in elem if t.tag == "tag"}
            if not (any(k in quest_index for k in tags) or any(k.startswith("ext:") for k in tags)):
                continue
            if elem.tag == "node":
                lat = elem.attrib.get("lat")
                lon = elem.attrib.get("lon")
                return (float(lat), float(lon)) if lat and lon else None
            if elem.tag == "way":
                nd_refs = [nd.attrib["ref"] for nd in elem if nd.tag == "nd" and "ref" in nd.attrib]
                positions = [node_positions[r] for r in nd_refs if r in node_positions]
                return positions[len(positions) // 2] if positions else None
    return None


def _extract_all_quest_elements(
    osc_xml: str, quest_index: dict
) -> list[tuple[str, str, tuple[float, float] | None, dict]]:
    """Returns a list of tuples containing the `elem_type`, `elem_id`,
    `position_or_None`, and `tags` for each quest element found in the OSC.

    If we populate `quest_index`, we only return elements that contain at least
    one key from that index. If `quest_index` is empty, we return any element
    with a tag starting with `ext:`.

    For nodes, we derive position from lat/lon values found inline in the OSC.
    For ways, we use the middle `nd-ref`.
    """
    if not osc_xml:
        return []
    try:
        root = ET.fromstring(osc_xml)
    except ET.ParseError:
        return []
    node_positions: dict[str, tuple[float, float]] = {}
    for action in root:
        for elem in action:
            if elem.tag == "node" and "lat" in elem.attrib and "lon" in elem.attrib:
                node_positions[elem.attrib["id"]] = (
                    float(elem.attrib["lat"]), float(elem.attrib["lon"])
                )
    result = []
    for action in root:
        for elem in action:
            if elem.tag not in ("node", "way", "relation"):
                continue
            tags = {t.attrib["k"]: t.attrib["v"] for t in elem if t.tag == "tag"}
            if quest_index:
                if not any(k in quest_index for k in tags):
                    continue
            else:
                if not any(k.startswith("ext:") for k in tags):
                    continue
            elem_id = elem.attrib.get("id")
            if not elem_id:
                continue
            if elem.tag == "node":
                pos: tuple[float, float] | None = node_positions.get(elem_id)
            elif elem.tag == "way":
                nd_refs = [nd.attrib["ref"] for nd in elem if nd.tag == "nd" and "ref" in nd.attrib]
                positions = [node_positions[r] for r in nd_refs if r in node_positions]
                pos = positions[len(positions) // 2] if positions else None
            else:
                pos = None
            result.append((elem.tag, elem_id, pos, tags))
    return result


def _extract_quest_element_info(
    osc_xml: str, quest_index: dict
) -> tuple[str, str, int] | None:
    """Extracts the `elem_type`, `elem_id`, and `version` from the primary
    quest-answer element within the OSC.

    We return `None` if the `osc_xml` string proves empty or if `ET.fromstring`
    raises an `ET.ParseError`. When we find an element with a tag of `node`,
    `way`, or `relation` that contains either a key from `quest_index` or a key
    starting with `ext:`, we return its tag along with its `id` and `version`
    attributes as a tuple.
    """
    if not osc_xml:
        return None
    try:
        root = ET.fromstring(osc_xml)
    except ET.ParseError:
        return None
    for action in root:
        for elem in action:
            if elem.tag not in ("node", "way", "relation"):
                continue
            tags = {t.attrib["k"]: t.attrib["v"] for t in elem if t.tag == "tag"}
            if not (any(k in quest_index for k in tags) or any(k.startswith("ext:") for k in tags)):
                continue
            eid = elem.attrib.get("id")
            eversion = elem.attrib.get("version")
            if eid and eversion:
                return (elem.tag, eid, int(eversion))
    return None
