"""Generates `quest_index` and `choices_index` using a quest definition
dictionary.
"""

_QUEST_INTERNAL_SUFFIXES = (
    "_team_selection", "_collect_for_other_teams", "_additional_data_groups",
    "_observation_visibility", "_internal_note_prompt",
)


def _tag_aliases(tag: str) -> set[str]:
    """Returns a set containing the quest tag in both its bare and `ext:`-prefixed
    forms.
    """
    if tag.startswith("ext:"):
        return {tag, tag[4:]}
    return {tag, f"ext:{tag}"}


def build_quest_index(quest_def: dict | None) -> dict:
    if not quest_def:
        return {}
    index = {}
    for element in quest_def.get("elements", []):
        etype = element["element_type"]
        for q in element.get("quests", []):
            tag = q.get("quest_tag", "")
            if tag and not any(tag.endswith(s) for s in _QUEST_INTERNAL_SUFFIXES):
                entry = {"title": q["quest_title"], "element_type": etype}
                for alias in _tag_aliases(tag):
                    index[alias] = entry
    return index


def build_choices_index(quest_def: dict | None) -> dict[str, dict[str, str]]:
    """Constructs a mapping of `{quest_tag: {value: choice_text}}` using
    `quest_answer_choices` from the provided definition.
    """
    if not quest_def:
        return {}
    index: dict[str, dict[str, str]] = {}
    for element in quest_def.get("elements", []):
        for q in element.get("quests", []):
            tag = q.get("quest_tag", "")
            choices = q.get("quest_answer_choices", [])
            if tag and choices:
                choice_map = {
                    c["value"]: c.get("choice_text", c["value"])
                    for c in choices if "value" in c
                }
                for alias in _tag_aliases(tag):
                    index[alias] = choice_map
    return index
