"""Analyzes changesets to calculate feature creation tallies and contribution
counts per quest, team, and user.
"""

import xml.etree.ElementTree as ET
from collections import defaultdict

from .classify import (
    classify_osm_feature, classify_quest, classify_by_tags,
    get_photo_urls, get_team_selections, parse_element_tags, split_note_photos,
)
from .osc import _extract_all_quest_elements


def analyse(changesets: list, quest_index: dict, notes: list | None = None) -> dict:
    quest_counts: dict[str, int] = defaultdict(int)
    team_counts: dict[str, int] = defaultdict(int)
    user_counts: dict[str, int] = defaultdict(int)
    quest_photo_urls: dict[str, list] = defaultdict(list)
    team_photo_urls: dict[str, list] = defaultdict(list)
    user_photo_urls: dict[str, list] = defaultdict(list)
    seen_photo_urls: set[str] = set()

    # Sorting by changeset-ID ensures credit goes to the earliest CS
    # introducing a photo URL. Later CSes repeat the same URL in their OSC
    # because the OSC records full current element state instead of a diff.
    for cs in sorted(changesets, key=lambda x: x.get("id", 0)):
        if cs.get("changes_count") == 0:
            continue
        osc_xml = cs.get("osc_xml", "")
        elem_tags = parse_element_tags(osc_xml)
        teams = get_team_selections(elem_tags)
        # The changeset's quest elements provide all photo URLs, which ensures
        # summary cards for users, teams, and quests include photos from every
        # modified node beyond the first.
        quest_elems = _extract_all_quest_elements(osc_xml, quest_index)
        all_urls: list[str] = list(dict.fromkeys(
            url
            for _, _, _, etags in quest_elems
            for url in get_photo_urls(etags)
        )) if quest_elems else get_photo_urls(elem_tags)
        new_urls = [u for u in all_urls if u not in seen_photo_urls]
        seen_photo_urls.update(all_urls)
        user = cs.get("user", "unknown")

        user_counts[user] += 1
        if new_urls:
            user_photo_urls[user].extend(new_urls)
        for t in teams:
            team_counts[t] += 1
            if new_urls:
                team_photo_urls[t].extend(new_urls)

        # A changeset qualifies as a quest type only when it follows the quest
        # workflow, which means either the element contains ext: survey tags or
        # Android included quest_type.
        #
        # Changesets that create features alone (man_made=manhole,
        # amenity=bench ...) lack both markers and stay out of the Quest Types
        # breakdown.
        is_quest = any(k.startswith("ext:") for k in elem_tags) or any(
            "quest_type" in k for k in cs.get("tags", {})
        )
        if is_quest:
            quest = classify_quest(cs, elem_tags, quest_index)
            quest_counts[quest] += 1
            if new_urls:
                quest_photo_urls[quest].extend(new_urls)

    # Each note represents one contribution from its author. Because caches
    # created before notes included a user lack attribution, the loop skips
    # those notes.
    for note in notes or []:
        user = note.get("user")
        if not user:
            continue
        user_counts[user] += 1
        _, urls = split_note_photos(note.get("text", ""))
        new_urls = [u for u in urls if u not in seen_photo_urls]
        seen_photo_urls.update(urls)
        if new_urls:
            user_photo_urls[user].extend(new_urls)

    return {
        "total": len(changesets),
        "quest": dict(sorted(quest_counts.items(), key=lambda x: -x[1])),
        "team": dict(sorted(team_counts.items(), key=lambda x: -x[1])),
        "users": dict(sorted(user_counts.items(), key=lambda x: -x[1])),
        "quest_photo_urls": {k: list(dict.fromkeys(v)) for k, v in quest_photo_urls.items()},
        "team_photo_urls": {k: list(dict.fromkeys(v)) for k, v in team_photo_urls.items()},
        "user_photo_urls": {k: list(dict.fromkeys(v)) for k, v in user_photo_urls.items()},
    }


def count_created_features(changesets: list, quest_index: dict) -> dict[str, int]:
    """Tallies OSC <create> elements grouped by element_type, placing unclassified
    items into an 'other' category.
    """
    counts: dict[str, int] = defaultdict(int)
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
                etype = classify_by_tags(tags, quest_index)
                if etype == "other":
                    etype = classify_osm_feature(tags)
                counts[etype] += 1
    # Counts descend by value, but the 'other' bucket stays last.
    classified = dict(sorted(
        ((k, v) for k, v in counts.items() if k != "other"), key=lambda x: -x[1]
    ))
    if "other" in counts:
        classified["other"] = counts["other"]
    return classified


def count_questions(changesets: list, quest_index: dict) -> dict[str, dict[str, dict[str, int]]]:
    counts: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for cs in changesets:
        osc = cs.get("osc_xml", "")
        if not osc:
            continue
        try:
            root = ET.fromstring(osc)
        except ET.ParseError:
            continue
        for action in root:
            for elem in action:
                if elem.tag not in ("node", "way", "relation"):
                    continue
                for t in elem:
                    if t.tag != "tag":
                        continue
                    k = t.attrib["k"]
                    v = t.attrib["v"]
                    if k in quest_index:
                        counts[quest_index[k]["element_type"]][k][v] += 1
    return counts
