"""Validates offline archive quest definitions to ensure they meet index-builder
expectations.
"""

from .offline_validate import _reject_lone_surrogates
from .quests import _QUEST_INTERNAL_SUFFIXES


def _validate_quest_definition(quest_def, quest_path) -> None:
    """Validates quest-definition structures to prevent crashes during index
    building.

    We match the dereferencing behavior of `build_quest_index` and
    `build_choices_index`, as well as the requirements of render consumers such
    as popup title lookups, template `k.replace`, and `Counter` keys. When a
    shape is tolerated by all consumers, we treat it as valid. Otherwise, we
    raise a `ValueError` that identifies the quest file.
    """
    where = f"quest file {quest_path}"
    if not quest_def:
        return
    if not isinstance(quest_def, dict):
        raise ValueError(f"{where}: the definition needs to be in JSON "
                             "object format")
    elements = quest_def.get("elements", [])
    if not isinstance(elements, list):
        raise ValueError(f"{where}: 'elements' is required to be a list")
    for i, element in enumerate(elements):
        if not isinstance(element, dict):
            raise ValueError(f"{where}: element {i} must be an object")
        if "element_type" not in element:
            raise ValueError(f"{where}: element {i} lacks the 'element_type' "
                                 "key")
        # The `element_type` field keys the Counter and quest indexes, and it
        # feeds into the template's `k.replace` method, which crashes if a
        # matching changeset appears.
        #
        # We require strings here instead of any scalar allowed upstream,
        # keeping this restriction consistent with the strictness applied to
        # `changeset-id`.
        etype_val = element["element_type"]
        if not isinstance(etype_val, str):
            raise ValueError(f"{where}: element {i} requires a string for "
                                 "'element_type'")
        _reject_lone_surrogates(f"{where}: element {i}", "element_type", etype_val)
        quests = element.get("quests", [])
        if not isinstance(quests, list):
            raise ValueError(f"{where}: element {i} 'quests' is required to "
                                 "be a list")
        for j, q in enumerate(quests):
            if not isinstance(q, dict):
                raise ValueError(f"{where}: element {i} quest {j} must be an "
                                     "object")
            tag = q.get("quest_tag", "")
            if tag and not isinstance(tag, str):
                raise ValueError(
                    f"{where}: element {i} quest {j} requires 'quest_tag' to "
                        "be text"
                )
            # popup._map_choice_value uses quest titles as keys. Because dicts
            # and lists lack hashability, we cannot use them there. Scalar
            # types--including None, True, and integers--work because we coerce
            # them with str().
            if "quest_title" in q and isinstance(q["quest_title"], (dict, list)):
                raise ValueError(
                    f"{where}: element {i} quest {j} 'quest_title' cannot be "
                        "a list or dictionary"
                )
            if "quest_title" in q:
                _reject_lone_surrogates(
                    f"{where}: element {i} quest {j}", "quest_title", q["quest_title"]
                )
            if tag and not any(tag.endswith(s) for s in _QUEST_INTERNAL_SUFFIXES):
                if "quest_title" not in q:
                    raise ValueError(
                        f"{where}: element {i} quest {j} lacks a "
                            "'quest_title'"
                    )
            choices = q.get("quest_answer_choices", [])
            # `build_choices_index` subscripts entries that pass the
            # `"value" in c` check after iterating through an iterable. When we
            # have dict keys or str list entries, that check performs a
            # substring test. Any entry or key containing `"value"` passes this
            # guard but crashes the consumer because string indices must be
            # integers. We need to reject those cases. If we pass a top-level
            # str, it yields single characters that can never contain
            # `"value"`.
            if choices:
                if isinstance(choices, str):
                    pass
                elif isinstance(choices, dict):
                    for key in choices:
                        if isinstance(key, str) and "value" in key:
                            raise ValueError(
                                f"{where}: element {i} quest {j} "
                                    f"'quest_answer_choices' key {key!r} "
                                    "cannot include 'value'"
                            )
                elif not isinstance(choices, (list, tuple)):
                    raise ValueError(
                        f"{where}: element {i} quest {j} "
                            "'quest_answer_choices' is required to be a list"
                    )
                else:
                    for c in choices:
                        if isinstance(c, dict):
                            if "value" in c and isinstance(c["value"], (dict, list)):
                                raise ValueError(
                                    f"{where}: the 'value' field of quest "
                                        f"{tag!r} answer choice cannot be a "
                                        "JSON array or object"
                                )
                            # The popup crashes when it encounters non-string
                            # values because it joins `choice_text` with "; "
                            # to handle multi-answer inputs (such as "yes;no").
                            # Upstream non-strings are tolerated during direct
                            # single-value lookups.
                            #
                            # We maintain this documented divergence because a
                            # single quest may receive multiple answers, so any
                            # available `choice_text` needs to be either a
                            # string or `None`.
                            if (
                                "choice_text" in c
                                and c["choice_text"] is not None
                                and not isinstance(c["choice_text"], str)
                            ):
                                raise ValueError(
                                    f"{where}: the answer choice "
                                        f"'choice_text' for quest {tag!r} "
                                        "cannot be anything but a string"
                                )
                            if isinstance(c.get("choice_text"), str):
                                # The Labels view renders `display_choice` as
                                # raw text. We don't render choice `value`
                                # strings or additional choice keys raw, so
                                # those fields remain unguarded.
                                _reject_lone_surrogates(
                                    f"{where}: quest {tag!r} answer",
                                    "choice_text",
                                    c["choice_text"],
                                )
                        elif isinstance(c, str):
                            if "value" in c:
                                raise ValueError(
                                    f"{where}: element {i} quest {j} "
                                        "'quest_answer_choices' entry "
                                        "cannot be a string that includes "
                                        "'value'"
                                )
                        else:
                            raise ValueError(
                                f"{where}: element {i} quest {j} requires "
                                    "'quest_answer_choices' entries to be "
                                    "objects"
                            )
