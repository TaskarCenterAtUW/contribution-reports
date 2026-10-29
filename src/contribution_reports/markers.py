"""This module generates lists of map markers from changesets, representing both
created features and quest submissions.
"""

import xml.etree.ElementTree as ET

from .classify import classify_by_tags, classify_osm_feature, classify_quest, get_photo_urls, parse_element_tags
from .osc import _extract_all_quest_elements, _quest_element_position
from .popup import build_popup_tags, build_readable_tags


def build_map_markers(
    changesets: list, quest_index: dict, choices_index: dict | None = None
) -> list[dict]:
    """Generates quest-submission markers grouped by their combined `elem_type`
    and `elem_id`.

    If multiple changesets modified a single OSM element during the event, we
    include a `versions` list in the marker to allow popup pagination. We order
    these versions with the highest changeset ID first for display purposes.

    Before we group elements, we deduplicate photos in ascending CS-ID order.
    This ensures we credit the earliest changeset that introduces any given
    URL.
    """
    seen_photo_urls: set[str] = set()
    # Maps each `(elem_type, elem_id)` pair to a list of `version_entry`
    # objects ordered by ascending CS-ID.
    elem_groups: dict[tuple, list[dict]] = {}
    elem_geoms: dict[tuple, list] = {}  # first geometry seen per element
    ungrouped: list[dict] = []

    for cs in sorted(changesets, key=lambda x: x.get("id", 0)):
        if cs.get("changes_count") == 0:
            continue
        min_lat = cs.get("min_lat")
        min_lon = cs.get("min_lon")
        max_lat = cs.get("max_lat")
        max_lon = cs.get("max_lon")
        if min_lat is None or min_lon is None:
            continue
        osc_xml = cs.get("osc_xml", "")
        has_quest_type_tag = any("quest_type" in k for k in cs.get("tags", {}))
        # Each quest element in this changeset receives its own marker.
        quest_elems = _extract_all_quest_elements(osc_xml, quest_index)

        if not quest_elems and not has_quest_type_tag:
            continue

        # `cached_elem_id` is the ID of the first quest element stored during
        # fetch, so we can match that element to cached `prev_tags`,
        # `elem_lat`/`lon`, and `elem_geom`.
        #
        # `all_elem_geoms` caches the geometry and position for every quest
        # way.
        cached_elem_id = cs.get("elem_id")
        prev_tags = cs.get("prev_tags")
        all_elem_geoms = cs.get("all_elem_geoms") or {}

        if quest_elems:
            for elem_type, elem_id, osc_pos, elem_tags in quest_elems:
                # Position priority: per-element cache → legacy single-element cache
                #   → OSC inline coords → changeset bbox centroid.
                elem_cache = all_elem_geoms.get(elem_id, {})
                if elem_cache.get("lat") is not None:
                    lat, lon = elem_cache["lat"], elem_cache["lon"]
                elif elem_id == cached_elem_id and cs.get("elem_lat") is not None:
                    lat, lon = cs["elem_lat"], cs["elem_lon"]
                elif osc_pos:
                    lat, lon = osc_pos
                else:
                    lat = (float(min_lat) + float(max_lat)) / 2
                    lon = (float(min_lon) + float(max_lon)) / 2

                # Caches for `prev_tags` exist only for the first quest
                # element. Other elements use the `quest_index` heuristic to
                # determine tag coloring.
                this_prev_tags = prev_tags if elem_id == cached_elem_id else None
                etype = classify_quest(cs, elem_tags, quest_index)
                elem_photos = get_photo_urls(elem_tags)
                new_photos = [u for u in elem_photos if u not in seen_photo_urls]
                seen_photo_urls.update(elem_photos)

                version_entry: dict = {
                    "user": cs.get("user", "unknown"),
                    "tags": build_popup_tags(elem_tags, "quest", quest_index, this_prev_tags),
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "type": etype,
                }
                readable = build_readable_tags(elem_tags, quest_index, choices_index or {}, this_prev_tags)
                if readable:
                    version_entry["readable"] = readable
                if new_photos:
                    version_entry["photos"] = new_photos

                elem_key = (elem_type, elem_id)
                elem_groups.setdefault(elem_key, []).append(version_entry)
                # Per-element caches override legacy single-element caches when
                # resolving geometry.
                if elem_cache.get("geom") and elem_key not in elem_geoms:
                    elem_geoms[elem_key] = elem_cache["geom"]
                elif elem_id == cached_elem_id and cs.get("elem_geom") and elem_key not in elem_geoms:
                    elem_geoms[elem_key] = cs["elem_geom"]
        else:
            # The changeset has a quest_type tag but its OSC contains no
            # parseable quest elements, so the code falls back to a single
            # marker.
            elem_tags = parse_element_tags(osc_xml)
            if cs.get("elem_lat") is not None:
                lat, lon = cs["elem_lat"], cs["elem_lon"]
            else:
                pos = _quest_element_position(osc_xml, quest_index)
                if pos:
                    lat, lon = pos
                else:
                    lat = (float(min_lat) + float(max_lat)) / 2
                    lon = (float(min_lon) + float(max_lon)) / 2
            etype = classify_quest(cs, elem_tags, quest_index)
            elem_photos = get_photo_urls(elem_tags)
            new_photos = [u for u in elem_photos if u not in seen_photo_urls]
            seen_photo_urls.update(elem_photos)
            version_entry = {
                "user": cs.get("user", "unknown"),
                "tags": build_popup_tags(elem_tags, "quest", quest_index, prev_tags),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "type": etype,
            }
            readable = build_readable_tags(elem_tags, quest_index, choices_index or {}, prev_tags)
            if readable:
                version_entry["readable"] = readable
            if new_photos:
                version_entry["photos"] = new_photos
            elem_key = (cs.get("elem_type"), cached_elem_id)
            if elem_key[0] and elem_key[1]:
                elem_groups.setdefault(elem_key, []).append(version_entry)
                if cs.get("elem_geom") and elem_key not in elem_geoms:
                    elem_geoms[elem_key] = cs["elem_geom"]
            else:
                ungrouped.append(version_entry)

    markers = []
    for elem_key, versions in elem_groups.items():
        # Oldest versions occupy page 1 and latest versions occupy page N in
        # ascending order. The latest version appears by default.
        latest = versions[-1]
        m: dict = {
            "lat": latest["lat"],
            "lon": latest["lon"],
            "type": latest["type"],
            "kind": "quest",
            "versions": versions,
        }
        if elem_key in elem_geoms:
            m["geom"] = elem_geoms[elem_key]
        markers.append(m)
    for ve in ungrouped:
        markers.append({
            "lat": ve["lat"],
            "lon": ve["lon"],
            "type": ve["type"],
            "kind": "quest",
            "versions": [ve],
        })
    return markers


def build_created_markers(changesets: list, quest_index: dict) -> list[dict]:
    """Generates a list of markers for each element created in the provided
    changesets, using the element's coordinates for positioning.
    """
    markers = []
    for cs in changesets:
        osc = cs.get("osc_xml", "")
        if not osc:
            continue
        try:
            root = ET.fromstring(osc)
        except ET.ParseError:
            continue
        for action in root:
            if action.tag != "create":
                continue
            for elem in action:
                if elem.tag not in ("node", "way", "relation"):
                    continue
                tags = {t.attrib["k"]: t.attrib["v"] for t in elem if t.tag == "tag"}
                if not tags:
                    continue
                etype = classify_by_tags(tags, quest_index)
                if etype == "other":
                    etype = classify_osm_feature(tags)
                if elem.tag == "node":
                    lat_s = elem.attrib.get("lat")
                    lon_s = elem.attrib.get("lon")
                    if lat_s is None or lon_s is None:
                        continue
                    lat = round(float(lat_s), 6)
                    lon = round(float(lon_s), 6)
                else:
                    # All constituent nodes within the same <create> action
                    # contain lat/lon for created ways and relations, so the
                    # middle node's position provides the coordinates.
                    node_positions = {
                        n.attrib["id"]: (float(n.attrib["lat"]), float(n.attrib["lon"]))
                        for n in action
                        if n.tag == "node" and "lat" in n.attrib and "lon" in n.attrib
                    }
                    nd_refs = [nd.attrib["ref"] for nd in elem if nd.tag == "nd" and "ref" in nd.attrib]
                    positions = [node_positions[r] for r in nd_refs if r in node_positions]
                    if positions:
                        mid_lat, mid_lon = positions[len(positions) // 2]
                        lat = round(mid_lat, 6)
                        lon = round(mid_lon, 6)
                    else:
                        min_lat = cs.get("min_lat")
                        min_lon = cs.get("min_lon")
                        max_lat = cs.get("max_lat")
                        max_lon = cs.get("max_lon")
                        if min_lat is None:
                            continue
                        lat = round((float(min_lat) + float(max_lat)) / 2, 6)
                        lon = round((float(min_lon) + float(max_lon)) / 2, 6)
                m_entry: dict = {
                    "lat": lat, "lon": lon,
                    "type": etype,
                    "user": cs.get("user", "unknown"),
                    "kind": "create",
                    "tags": build_popup_tags(tags, "create"),
                }
                photos = get_photo_urls(tags)
                if photos:
                    m_entry["photos"] = photos
                markers.append(m_entry)
    return markers
