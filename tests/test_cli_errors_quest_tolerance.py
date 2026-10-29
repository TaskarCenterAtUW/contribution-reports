"""Tests that verify error handling at the CLI boundary for quest tolerance."""

import json

import pytest

from contribution_reports import offline

from _cli_errors_helpers import (
    WS_META,
    _GEO_OK,
    _assert_clean_cli_error,
    _cs,
    _manifest_zip,
    _quest_cli_fail,
    _quest_def,
    _quest_file,
    _run,
    _run_offline,
)


_EXT_NODE = json.dumps(
    {
        "create": [
            {
                "id": 1,
                "version": 1,
                "lat": 1.0,
                "lon": 1.0,
                "tags": {"ext:surface": "paved"},
            }
        ]
    }
)


def test_geo_bool_accepted_string_mirror_kept(dummy_env, monkeypatch, capsys):
    created_way = json.dumps(
        {
            "create": [
                {
                    "id": 2,
                    "version": 1,
                    "type": "way",
                    "nodes": [1, 2],
                    "tags": {"highway": "path"},
                },
            ]
        }
    )
    entry = dict(min_lat=True, min_lon=1.0, max_lat=2.0, max_lon=3.0)
    archive = _manifest_zip(
        dummy_env / "geo-true.zip",
        {**WS_META, "changesets": [_cs(**entry)]},
        {"changesets/1.json": created_way},
    )
    _run(monkeypatch, ["--offline", str(archive)])()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "ERROR" not in captured.err
    # We'll use the bbox centroid as a fallback for markers. Because
    # float(True) equals 1.0, we get a midpoint of 1.5.
    assert "1.5" in (dummy_env / "output" / "report.html").read_text(encoding="utf-8")
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "geo-abc.zip",
        {**WS_META, "changesets": [_cs(min_lat="abc")]},
        None,
        ["entry 0", "min_lat"],
    )
    # We use digit-strings for coordinates so they mirror the coercion to
    # float() we'll encounter downstream, which allows them to pass.
    offline.load_offline_archive(
        _manifest_zip(
            dummy_env / "geo-numstr.zip",
            {
                **WS_META,
                "changesets": [
                    _cs(min_lat="47.5", min_lon="1.0", max_lat="1", max_lon=1)
                ],
            },
        )
    )


def test_falsy_members_accepted_truthy_rejected(dummy_env, monkeypatch, capsys):
    for label, content in (("false", "false"), ("zero", "0"), ("null", "null")):
        archive = _manifest_zip(
            dummy_env / f"m-{label}.zip",
            {**WS_META, "changesets": [_cs()]},
            {"changesets/1.json": content},
        )
        data = offline.load_offline_archive(archive)
        assert data["workspaces"]["1"]["changesets"][0]["osc_xml"] == ""
    archive = _manifest_zip(
        dummy_env / "m-five.zip",
        {**WS_META, "changesets": [_cs()]},
        {"changesets/1.json": "5"},
    )
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, ["--offline", str(archive)])()
    assert excinfo.value.code == 1
    _assert_clean_cli_error(
        capsys.readouterr(),
        "changesets/1.json",
        "OSC JSON requires an object format",
    )


def test_quest_choices_reject_string_entries_containing_value_substring(
    dummy_env, monkeypatch, capsys
):
    # `build_choices_index` checks for the substring "value" within string
    # entries and then attempts to subscript them. When entries pass this test,
    # they crash during rendering with a "string indices must be integers"
    # error, matching behavior found upstream.
    archive = _manifest_zip(dummy_env / "ok.zip", {**WS_META, "changesets": []})
    for name, shape in (
        ("exact", ["value"]),
        ("substring", ["xvaluey 1", "value:2"]),
    ):
        quest_file = _quest_file(
            dummy_env, f"sub-{name}.json", _quest_def(choices=shape)
        )
        _quest_cli_fail(
            monkeypatch,
            capsys,
            archive,
            quest_file,
            str(quest_file),
            "quest_answer_choices",
            "string that includes 'value'",
        )
    # Strings that fail the substring test remain accepted because they're
    # skipped upstream.
    quest_file = _quest_file(
        dummy_env, "sub-ctrl.json", _quest_def(choices=["yes", "no"])
    )
    _run(monkeypatch, ["--offline", str(archive), "--quest-file", str(quest_file)])()
    captured = capsys.readouterr()
    assert "ERROR" not in captured.err
    assert "Traceback" not in captured.err


def test_quest_choices_reject_dict_keys_containing_value(
    dummy_env, monkeypatch, capsys
):
    # Because dict iteration yields keys, a key that contains the literal
    # string value passes the consumer's guard. The consumer then attempts to
    # access c["value"], which triggers a TypeError.
    archive = _manifest_zip(dummy_env / "ok.zip", {**WS_META, "changesets": []})
    for name, key in (("exact", "value"), ("substring", "valuex")):
        quest_file = _quest_file(
            dummy_env, f"dkey-{name}.json", _quest_def(choices={key: 1})
        )
        _quest_cli_fail(
            monkeypatch,
            capsys,
            archive,
            quest_file,
            str(quest_file),
            "quest_answer_choices",
            f"key {key!r}",
        )
    # We verify that keys not targeted by the substring test remain acceptable.
    quest_file = _quest_file(
        dummy_env, "dkey-ctrl.json", _quest_def(choices={"a": 1, "yes": 2})
    )
    _run(monkeypatch, ["--offline", str(archive), "--quest-file", str(quest_file)])()
    captured = capsys.readouterr()
    assert "ERROR" not in captured.err
    assert "Traceback" not in captured.err


# We need strings for quest titles, element types, and quest type tags.

_QTYPE = "quest_type"


_NODE = {"id": 1, "version": 1, "lat": 1.0, "lon": 1.0, "tags": {"highway": "path"}}


def _quest_def_title(title, tag="surface"):
    quest = {"quest_tag": tag}
    if title is not _ABSENT:
        quest["quest_title"] = title
    return {"elements": [{"element_type": "Sidewalks", "quests": [quest]}]}


_ABSENT = object()


def test_changeset_quest_type_tag_must_be_a_string_clean_error(
    dummy_env, monkeypatch, capsys
):
    # We'll extract the first truthy quest_type-containing tag value containing
    # a quest_type through `classify_quest`. We need strings here because
    # non-string values break Counter keys and the `k.replace` call during
    # template rendering.
    for i, bad in enumerate((5, 1.5, {"a": 1}, [1])):
        _run_offline(
            dummy_env,
            monkeypatch,
            capsys,
            f"qt{i}.zip",
            {
                **WS_META,
                "changesets": [_cs(tags={"created_by": "GIG test", _QTYPE: bad})],
            },
            {"changesets/1.json": json.dumps({"create": [_NODE]})},
            ["tags.quest_type", "expected a string"],
        )
    # We need to ensure these remain loadable because non-quest_type keys
    # accept any JSON value and the `and v` expression in `classify_quest`
    # skips falsy values.
    for i, ok in enumerate((None, False, 0, "")):
        archive = _manifest_zip(
            dummy_env / f"qtok{i}.zip",
            {
                **WS_META,
                "changesets": [_cs(tags={"created_by": "GIG test", _QTYPE: ok})],
            },
            {"changesets/1.json": json.dumps({"create": [_NODE]})},
        )
        _run(monkeypatch, ["--offline", str(archive)])()
        captured = capsys.readouterr()
        assert "ERROR" not in captured.err and "Traceback" not in captured.err
    archive = _manifest_zip(
        dummy_env / "qtok-other.zip",
        {
            **WS_META,
            "changesets": [_cs(tags={"created_by": "GIG test", "other": {"a": 1}})],
        },
        {"changesets/1.json": json.dumps({"create": [_NODE]})},
    )
    _run(monkeypatch, ["--offline", str(archive)])()
    captured = capsys.readouterr()
    assert "ERROR" not in captured.err and "Traceback" not in captured.err


def test_quest_element_type_must_be_string_clean_error(dummy_env, monkeypatch, capsys):
    # We use `element_type` to index quests, which leads to a `Counter` and a
    # template `k.replace` call when an `ext: changeset` matches.
    #
    # While Round 8 allowed scalars, we now require a string for adjudicated
    # divergence (which follows the same strictness as IDs).
    archive = _manifest_zip(
        dummy_env / "ext.zip",
        {**WS_META, "changesets": [_cs(**_GEO_OK)]},
        {"changesets/1.json": _EXT_NODE},
    )
    for i, bad in enumerate(({"x": 1}, ["walk"], 5, True, 1.5, None)):
        quest_file = _quest_file(
            dummy_env, f"etype{i}.json", _quest_def(element_type=bad)
        )
        _quest_cli_fail(
            monkeypatch,
            capsys,
            archive,
            quest_file,
            str(quest_file),
            "element_type",
            "requires a string",
        )
    quest_file = _quest_file(
        dummy_env, "etype-ok.json", _quest_def(element_type="Sidewalks")
    )
    _run(monkeypatch, ["--offline", str(archive), "--quest-file", str(quest_file)])()
    captured = capsys.readouterr()
    assert "ERROR" not in captured.err and "Traceback" not in captured.err


def test_quest_title_object_array_error(dummy_env, monkeypatch, capsys):
    # We need to use quest titles as keys when `popup._map_choice_value`
    # retrieves results, which means titles that are arrays or objects cause
    # hashing failures. Scalar titles work fine.
    archive = _manifest_zip(dummy_env / "ok.zip", {**WS_META, "changesets": []})
    for i, bad in enumerate(({"q": 1}, ["Q"])):
        quest_file = _quest_file(dummy_env, f"qtitle{i}.json", _quest_def_title(bad))
        _quest_cli_fail(
            monkeypatch,
            capsys,
            archive,
            quest_file,
            str(quest_file),
            "quest_title",
            "cannot be a list or dictionary",
        )
    for i, ok in enumerate((5, None, True)):
        quest_file = _quest_file(dummy_env, f"qtitleok{i}.json", _quest_def_title(ok))
        _run(
            monkeypatch, ["--offline", str(archive), "--quest-file", str(quest_file)]
        )()
        captured = capsys.readouterr()
        assert "ERROR" not in captured.err and "Traceback" not in captured.err
