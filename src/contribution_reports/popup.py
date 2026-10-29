"""Generates tag dictionaries for Raw and Labels view displays in map popups.
"""

_POPUP_SKIP_PREFIXES = ("ext:gig_", "ext:osm_version")
_POPUP_SKIP_SUFFIXES = (
    "_id", "_picture", "_photo",
    "_collect_for_other_teams", "_additional_data_groups",
    "_observation_visibility", "_internal_note_prompt",
)
_POPUP_OSM_KEYS = frozenset({
    "highway", "footway", "kerb", "barrier", "man_made", "amenity",
    "public_transport", "crossing", "surface",
})


def filter_popup_tags(elem_tags: dict) -> dict:
    """Filters tags for map popups in quest submissions to include only those
    relevant to the survey.

    We can keep a tag if it starts with `ext:` or exists in `_POPUP_OSM_KEYS`,
    provided it does not start with any prefix in `_POPUP_SKIP_PREFIXES` or end
    with any suffix in `_POPUP_SKIP_SUFFIXES`.
    """
    result = {}
    for k, v in elem_tags.items():
        if any(k.startswith(p) for p in _POPUP_SKIP_PREFIXES):
            continue
        if any(k.endswith(s) for s in _POPUP_SKIP_SUFFIXES):
            continue
        if k.startswith("ext:") or k in _POPUP_OSM_KEYS:
            result[k] = v
    return result


def build_popup_tags(
    elem_tags: dict,
    kind: str,
    quest_index: dict | None = None,
    prev_tags: dict | None = None,
) -> dict:
    """Encodes tags for popup display using diff metadata to enable color-coding.

    We return a dictionary with the structure
    `{key: {"old": str|None, "new": str|None}}`. The contents depend on the
    `kind` and available metadata:

    - If `kind='create'`, we set `old=None` (green) for all tags.
    - If `kind='quest'` and we have `prev_tags`, we calculate a true diff
      against the previous element version.
    - If `kind='quest'` and `prev_tags` is missing, we use the `quest_index`
      heuristic to mark quest tags as green and all others as neutral.
    """
    if kind == "create":
        return {k: {"old": None, "new": v} for k, v in elem_tags.items()}
    if prev_tags is not None:
        result = {}
        for k in set(elem_tags) | set(prev_tags):
            result[k] = {"old": prev_tags.get(k), "new": elem_tags.get(k)}
        return result
    qi = quest_index or {}
    return {
        k: {"old": None, "new": v} if k in qi else {"old": v, "new": v}
        for k, v in elem_tags.items()
    }


def _map_choice_value(v: str, choices: dict) -> str:
    """Maps tag values to display labels while resolving semicolon-separated
    MultipleChoice entries.

    We split the input on ';' and map each component to its `choice_text`
    before joining them back together. If no components match a label in the
    `choices` dictionary, we return the raw value.
    """
    if not choices:
        return v
    # We first attempt a direct lookup to handle single-value quests.
    if v in choices:
        return choices[v]
    # Semicolon-separated MultipleChoice
    parts = [p.strip() for p in v.split(";") if p.strip()]
    if not parts:
        return v
    labels = [choices.get(p) for p in parts]
    if all(label is None for label in labels):
        return v  # we use raw when no labels match
    return "; ".join(label if label is not None else p for label, p in zip(labels, parts))


def build_readable_tags(
    elem_tags: dict,
    quest_index: dict,
    choices_index: dict,
    prev_tags: dict | None = None,
) -> dict | None:
    """Generates human-readable popup tags by resolving quest titles and display
    text for choices.

    We only include tags starting with `ext:` that appear in the `quest_index`.
    The function returns `None` if no such tags exist.

    If we supply `prev_tags`, we also map the previous value through the
    `choices_index`. This ensures the labels view displays a true before->after
    diff instead of marking the entry as always green.
    """
    filtered = filter_popup_tags(elem_tags)
    result: dict = {}
    has_readable = False
    for k, v in filtered.items():
        if not k.startswith("ext:"):
            continue
        choices = choices_index.get(k, {})
        if k in quest_index:
            title = quest_index[k]["title"]
        elif k.endswith("_team_selection"):
            # We build the title from the key, turning
            # ext:sidewalk_team_selection into "Sidewalk Team".
            domain = k[4:].removesuffix("_team_selection").replace("_", " ").strip().title()
            title = f"{domain} Team" if domain else "Team Selection"
        else:
            continue
        display_val = _map_choice_value(v, choices)
        if title != k or display_val != v:
            has_readable = True
        if prev_tags is not None:
            old_raw = prev_tags.get(k)
            old_display = None if old_raw is None else _map_choice_value(old_raw, choices)
        else:
            old_display = None
        result[title] = {"old": old_display, "new": display_val}
    return result if has_readable else None
