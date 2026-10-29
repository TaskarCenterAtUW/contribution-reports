"""Categorization logic for changesets and elements based on OSM feature types and
quest types.
"""

import base64
import re
import xml.etree.ElementTree as ET
from collections import Counter

from .constants import KARTAVIEW_CDN_PREFIX


def convert_kartaview_url(url: str) -> str:
    url = url.strip()
    if url.startswith(KARTAVIEW_CDN_PREFIX):
        return url
    b64 = base64.b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{KARTAVIEW_CDN_PREFIX}{b64}"


def _first_domain_word(tag_suffix: str) -> str:
    """This function pulls the first meaningful word out of an `ext:` tag suffix.

    We split by `:` and `_` and normalize plurals by removing a trailing `s`
    when the word exceeds 3 characters.

        (e.g. 'crossings' -> 'crossing')
    """
    word = tag_suffix.replace(":", "_").split("_")[0]
    return word.rstrip("s") if len(word) > 3 else word


def classify_by_tags(elem_tags: dict, quest_index: dict) -> str:
    """Determines `element_type` by matching element tags against a `quest_index`.

    1. First, we look for exact matches on `quest_tag` keys.

    2. If that fails, we fall back to checking `team_selection` tags. These
       tags are intentionally excluded from the `quest_index`, but we can
       unambiguously identify the `element_type` through their first domain
       word:

        ext:curbs_team_selection -> Curbs

    We handle quest tags that use either underscore separators
    (`ext:crossing_{attr}`) or colon separators (`ext:crossing:{attr}`) by
    splitting on both.
    """
    if not quest_index:
        return "other"

    matched = [quest_index[k]["element_type"] for k in elem_tags if k in quest_index]
    if matched:
        return Counter(matched).most_common(1)[0][0]

    # The `word_map` records which `element_type` each first word maps to by
    # scanning the quest index.
    word_map: dict[str, str] = {}
    for qt, info in quest_index.items():
        if qt.startswith("ext:"):
            w = _first_domain_word(qt[4:])
            if w and w not in word_map:
                word_map[w] = info["element_type"]

    # Matching operates only on team_selection tags, which prevents metadata
    # tags such as ext:intersection_id from causing false positives on curb
    # nodes.
    for tag_key in elem_tags:
        if tag_key.endswith("_team_selection") and tag_key.startswith("ext:"):
            w = _first_domain_word(tag_key[4:])
            if w in word_map:
                return word_map[w]

    return "other"


# _OSM_FEATURE_RULES maps specific key-value pairs to display names for common
# pedestrian-infrastructure features.
#
# Plural forms match quest element_type values to maintain consistency.
#
# A None sentinel matches any non-empty value for a given key.
_OSM_FEATURE_RULES: list[tuple[str, str | None, str]] = [
    ("highway",         "street_lamp",      "Street Lamps"),
    ("highway",         "bus_stop",         "Bus Stops"),
    ("highway",         "crossing",         "Crossings"),
    ("highway",         "traffic_signals",  "Traffic Signals"),
    ("footway",         "sidewalk",         "Sidewalks"),
    ("footway",         "crossing",         "Crossings"),
    ("barrier",         "kerb",             "Curbs"),
    ("kerb",            None,               "Curbs"),
    ("public_transport","platform",         "Bus Stops"),
    ("public_transport","stop_position",    "Bus Stops"),
    ("man_made",        "manhole",          "Manhole"),
    ("man_made",        "utility_pole",     "Utility Pole"),
    ("man_made",        "street_cabinet",   "Street Cabinet"),
    ("man_made",        "surveillance_camera", "Surveillance Camera"),
    ("amenity",         "bench",            "Bench"),
    ("amenity",         "waste_basket",     "Waste Basket"),
    ("amenity",         "bicycle_parking",  "Bicycle Parking"),
    ("amenity",         "shelter",          "Shelter"),
    ("amenity",         "telephone",        "Telephone"),
    ("natural",         "tree",             "Tree"),
    ("barrier",         "bollard",          "Bollard"),
    ("barrier",         "cycle_barrier",    "Cycle Barrier"),
]

# The generic title-case fallback checks these keys in priority order.
_OSM_FEATURE_KEYS = (
    "highway", "footway", "barrier", "kerb", "man_made", "amenity",
    "public_transport", "natural", "railway", "building", "landuse",
)


def classify_osm_feature(elem_tags: dict) -> str:
    """Classifies created features through OSM tag heuristics.

    We first evaluate explicit rules. If none match, we title-case the value
    from the most significant tag to ensure every created element has a
    human-readable name.
    """
    for key, value, name in _OSM_FEATURE_RULES:
        tag_val = elem_tags.get(key)
        if tag_val and (value is None or tag_val == value):
            return name
    # Generic fallback
    for key in _OSM_FEATURE_KEYS:
        val = elem_tags.get(key)
        if val:
            return val.replace("_", " ").title()
    return "other"


def classify_quest(cs: dict, elem_tags: dict, quest_index: dict) -> str:
    """Assigns an element_type to a changeset submission.

    Android clients provide a `quest_type` tag in the changeset that matches
    the element_type. Because iOS clients exclude this tag, we instead compare
    tags from the modified element against `quest_tag` values in the
    definition.
    """
    for k, v in cs.get("tags", {}).items():
        if "quest_type" in k and v:
            return v
    etype = classify_by_tags(elem_tags, quest_index)
    if etype == "other":
        etype = classify_osm_feature(elem_tags)
    return etype


def get_team_selections(elem_tags: dict) -> list[str]:
    sel = []
    for k, v in elem_tags.items():
        if "team_selection" in k:
            for part in v.split(";"):
                part = part.strip()
                if part:
                    sel.append(part)
    return sel


def get_photo_urls(elem_tags: dict) -> list[str]:
    raw = elem_tags.get("ext:kartaview_url", "")
    if not raw:
        return []
    return [convert_kartaview_url(u) for u in raw.split(",") if u.strip()]


_KARTAVIEW_URL = r"https?://(?:[\w-]+\.)*(?:kartaview|openstreetcam)\.org/[^\s,]*"
_TRAILING_PHOTO_URLS_RE = re.compile(rf"(?:[\s,]*{_KARTAVIEW_URL})+[\s,]*$")


def split_note_photos(text: str) -> tuple[str, list[str]]:
    """Extracts KartaView photo URLs appended by survey apps from a note.

    We get a tuple containing the note text stripped of trailing URLs and a
    list of those URLs converted to CDN form. URLs that appear on different
    hosts or precede additional text remain in the note text.
    """
    text = text or ""
    match = _TRAILING_PHOTO_URLS_RE.search(text)
    if not match:
        return text, []
    urls = [convert_kartaview_url(u) for u in re.findall(_KARTAVIEW_URL, match.group())]
    return text[: match.start()].rstrip(), urls


def parse_element_tags(osc_xml: str) -> dict:
    if not osc_xml:
        return {}
    try:
        root = ET.fromstring(osc_xml)
    except ET.ParseError:
        return {}
    first_tags = None
    for action in root:
        for elem in action:
            if elem.tag in ("node", "way", "relation"):
                tags = {t.attrib["k"]: t.attrib["v"] for t in elem if t.tag == "tag"}
                if first_tags is None:
                    first_tags = tags
                if any(k.startswith("ext:") for k in tags):
                    return tags
    return first_tags or {}
