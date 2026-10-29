"""Label helpers for block-face elements that handle abbreviations, chip
formatting, and `seg_ref` dictionaries.

These functions are pure and require no I/O, so we can unit-test them using
plain ``python3``.
"""

import re

# ---------------------------------------------------------------------------
# Abbreviation tables
# ---------------------------------------------------------------------------

# We need to place longer and more specific entries first because order
# matters.
#
# Matching uses lower-cased keys to perform case-insensitive boundary matching.
_TYPE_ABBREVS: list[tuple[str, str]] = [
    ("boulevard",  "Blvd"),
    ("parkway",    "Pkwy"),
    ("highway",    "Hwy"),
    ("terrace",    "Ter"),
    ("square",     "Sq"),
    ("avenue",     "Ave"),
    ("circle",     "Cir"),
    ("street",     "St"),
    ("drive",      "Dr"),
    ("court",      "Ct"),
    ("place",      "Pl"),
    ("lane",       "Ln"),
    ("road",       "Rd"),
    # We don't abbreviate Way because it typically functions as part of a
    # proper name.
]

# We order these by length in descending order so that longer names like
# "Northeast" take precedence over shorter ones like "North".
_DIR_ABBREVS: list[tuple[str, str]] = [
    ("northeast", "NE"),
    ("northwest", "NW"),
    ("southeast", "SE"),
    ("southwest", "SW"),
    ("north",     "N"),
    ("south",     "S"),
    ("east",      "E"),
    ("west",      "W"),
]

# We pre-compile word-boundary patterns for every abbreviation entry. The
# word-boundary prevents a match for Streetcar while still capturing Street.
_TYPE_RE: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b" + pat + r"\b", re.IGNORECASE), abbr)
    for pat, abbr in _TYPE_ABBREVS
]
_DIR_RE: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b" + pat + r"\b", re.IGNORECASE), abbr)
    for pat, abbr in _DIR_ABBREVS
]


def abbreviate_street(name: str) -> str:
    """Shortens street names by abbreviating directionals and type suffixes.

    First we apply replacements from `_DIR_RE` and then those from `_TYPE_RE`.
    After these substitutions, we collapse multiple spaces into one and strip
    leading or trailing whitespace.
    """
    if not name:
        return name
    result = name
    for pattern, abbr in _DIR_RE:
        result = pattern.sub(abbr, result)
    for pattern, abbr in _TYPE_RE:
        result = pattern.sub(abbr, result)
    # We collapse consecutive whitespace that substitution might have
    # introduced.
    return re.sub(r"  +", " ", result).strip()


# ---------------------------------------------------------------------------
# Cross-street range formatting
# ---------------------------------------------------------------------------

def _shared_suffix(a: str, b: str) -> str | None:
    """Returns the common trailing word as a type suffix when both street strings
    end with it.

    ``"H Street"`` and ``"I Street"`` -> ``"Street"`` ``"H Street"`` and
    ``"K Avenue"`` -> None
    """
    if not a or not b:
        return None
    words_a = a.split()
    words_b = b.split()
    if words_a and words_b and words_a[-1].lower() == words_b[-1].lower():
        return words_a[-1]
    return None


def cross_street_range(cross_streets: list) -> str:
    """Converts a list of [from, to] cross-streets into a compact range using an
    en-dash.

    We return an empty string if the input is falsy or empty. When the list
    contains only one cross-street, we return its abbreviated name.
    """
    streets = [s for s in (cross_streets or []) if s]
    if not streets:
        return ""
    if len(streets) == 1:
        return abbreviate_street(streets[0])

    a, b = streets[0], streets[1]
    suffix = _shared_suffix(a, b)

    if suffix:
        # We strip the shared suffix from both names before we abbreviate it
        # once.
        abbr_suffix = abbreviate_street(suffix)
        stem_a = a[: len(a) - len(suffix)].strip()
        stem_b = b[: len(b) - len(suffix)].strip()
        # We also abbreviate street directionals within the stems.
        stem_a = abbreviate_street(stem_a)
        stem_b = abbreviate_street(stem_b)
        return f"{stem_a}–{stem_b} {abbr_suffix}"

    return f"{abbreviate_street(a)}–{abbreviate_street(b)}"


# ---------------------------------------------------------------------------
# Side letter
# ---------------------------------------------------------------------------

_SIDE_MAP = {
    "north": "N",
    "south": "S",
    "east":  "E",
    "west":  "W",
}


def side_letter(side: str) -> str:
    """Maps cardinal direction strings to single capital letters.

    When we pass non-cardinal values like "nearby", "left", "right", or "", the
    function returns "" so we can suppress the chip entirely.
    """
    return _SIDE_MAP.get((side or "").lower(), "")


# ---------------------------------------------------------------------------
# seg_ref dict
# ---------------------------------------------------------------------------

def format_segment_ref(segment: dict) -> dict:
    """Constructs a structured `seg_ref` dictionary from stored segment
    components.

    We return a dictionary containing these fields:
    - **road:** abbreviated road name as a `str`
    - **side:** raw side `str` from the segment
    - **side_letter:** single capital letter `str` or an empty string
    - **cross_range:** formatted cross-street range `str` or an empty string
    - **text:** plain-text `str` summary for aria or titles
    """
    name  = (segment or {}).get("name", "")
    side  = (segment or {}).get("side", "")
    cross = (segment or {}).get("cross_streets", []) or []

    road       = abbreviate_street(name) if name else ""
    sl         = side_letter(side)
    cross_r    = cross_street_range(cross)

    parts = [p for p in [road, sl, cross_r] if p]
    text = " · ".join(parts)

    return {
        "road":        road,
        "side":        side,
        "side_letter": sl,
        "cross_range": cross_r,
        "text":        text,
    }
