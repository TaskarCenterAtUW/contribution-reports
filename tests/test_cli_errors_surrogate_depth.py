"""CLI-boundary error handling for surrogate depth."""

import json
import zipfile

import pytest

from contribution_reports import cli, offline

from _cli_errors_helpers import (
    WS_META,
    _CREATE_TAGGED,
    _EXT_NODE_MEMBER,
    _MINIMAL_CS,
    _SURFACE_QUEST_DEF,
    _accept_cli,
    _assert_clean_cli_error,
    _build_archive,
    _cs,
    _manifest_zip,
    _quest_cli_fail,
    _quest_file,
    _reject_cli,
    _run,
    _run_offline,
)


# These tests verify that all_elem_geoms rejects invalid container shapes and
# that lone surrogates trigger rejection errors.


def test_all_elem_geoms_object_coords_clean_error(dummy_env, monkeypatch, capsys):
    # Coordinates arriving as dicts or lists crash the round() call. If a
    # non-dict value exists below the container, elem_cache.get crashes.
    for i, geoms in enumerate(
        ({"1": {"lat": {"a": 1}, "lon": [1]}}, {"1": [1]}, {"1": "x"})
    ):
        archive = _build_archive(
            dummy_env, f"a5-{i}.zip", {"all_elem_geoms": geoms}, member=_EXT_NODE_MEMBER
        )
        _reject_cli(
            dummy_env, monkeypatch, capsys, archive, ["all_elem_geoms", "1"], quest=True
        )


def test_all_elem_geoms_non_object_clean_error(dummy_env, monkeypatch, capsys):
    # Calling `all_elem_geoms.get` raises an `AttributeError` when the value is
    # a truthy non-mapping.
    #
    # Falsy values instead coalesce to `{}` because the consumer uses
    # `cs.get(...) or {}`. This allows those values to pass, which mirrors the
    # round-8 F6 ruling that treats falsy member files as empty.
    for i, bad in enumerate((5, [1, 2], "x")):
        archive = _build_archive(
            dummy_env, f"a6-{i}.zip", {"all_elem_geoms": bad}, member=_EXT_NODE_MEMBER
        )
        _reject_cli(
            dummy_env,
            monkeypatch,
            capsys,
            archive,
            ["all_elem_geoms", "JSON object"],
            quest=True,
        )
    for i, ok in enumerate(({}, [], 0, False, "")):
        archive = _build_archive(
            dummy_env, f"a6ok{i}.zip", {"all_elem_geoms": ok}, member=_EXT_NODE_MEMBER
        )
        _accept_cli(dummy_env, monkeypatch, capsys, archive, quest=True)


def test_surrogate_workspace_title_clean_error(dummy_env, monkeypatch, capsys):
    # Lone surrogates pass through escaped cache JSON but trigger a
    # UnicodeEncodeError in out_file.write_text after partial HTML reaches the
    # disk. The loader rejects these characters instead.
    archive = _build_archive(dummy_env, "b-title.zip", {}, title="ws\ud801")
    _reject_cli(
        dummy_env, monkeypatch, capsys, archive, ["manifest.json", "title", "surrogate"]
    )
    assert not (dummy_env / "output" / "report.html").exists()


def test_surrogate_changeset_user_clean_error(dummy_env, monkeypatch, capsys):
    archive = _build_archive(dummy_env, "b-user.zip", {"user": "U\ud801"})
    _reject_cli(
        dummy_env, monkeypatch, capsys, archive, ["entry 0", "user", "surrogate"]
    )
    assert not (dummy_env / "output" / "report.html").exists()


def test_surrogate_quest_title_clean_error(dummy_env, monkeypatch, capsys):
    archive = _build_archive(dummy_env, "b-qtitle.zip", {}, member=_EXT_NODE_MEMBER)
    definition = json.loads(json.dumps(_SURFACE_QUEST_DEF))
    definition["elements"][0]["quests"][0]["quest_title"] = "Q\ud801"
    quest_file = _quest_file(dummy_env, "bq.json", definition)
    _quest_cli_fail(
        monkeypatch,
        capsys,
        archive,
        quest_file,
        str(quest_file),
        "quest_title",
        "surrogate",
    )
    assert not (dummy_env / "output" / "report.html").exists()


def test_surrogate_element_type_clean_error(dummy_env, monkeypatch, capsys):
    archive = _build_archive(dummy_env, "b-etype.zip", {}, member=_EXT_NODE_MEMBER)
    definition = json.loads(json.dumps(_SURFACE_QUEST_DEF))
    definition["elements"][0]["element_type"] = "ET\ud801"
    quest_file = _quest_file(dummy_env, "be.json", definition)
    _quest_cli_fail(
        monkeypatch,
        capsys,
        archive,
        quest_file,
        str(quest_file),
        "element_type",
        "surrogate",
    )
    assert not (dummy_env / "output" / "report.html").exists()


def test_surrogate_benign_fields_are_accepted(dummy_env, monkeypatch, capsys):
    # The app filter alone uses created_by, so the field never reaches rendered
    # HTML. The loader accepts both fields as-is because a surrogate
    # `quest_tag` cannot match a changeset tag (accepted-benign divergence,
    # security report adjudication).
    #
    # Rejects from pass 7 in the XML-serializer cover OSC tag surrogates.
    cs = dict(_MINIMAL_CS)
    cs["tags"] = {"created_by": "GIG\ud801 app 1.0", "quest_type": "Sidewalks"}
    archive = _manifest_zip(
        dummy_env / "b-cb.zip",
        {"workspace": {"id": 1, "title": "T", "type": "osw"}, "changesets": [cs]},
        {"changesets/1.json": _EXT_NODE_MEMBER},
    )
    _accept_cli(dummy_env, monkeypatch, capsys, archive)
    definition = json.loads(json.dumps(_SURFACE_QUEST_DEF))
    definition["elements"][0]["quests"][0]["quest_tag"] = "ext:sur\ud801face"
    quest_file = _quest_file(dummy_env, "bqt.json", definition)
    _run(monkeypatch, ["--offline", str(archive), "--quest-file", str(quest_file)])()
    captured = capsys.readouterr()
    assert "ERROR" not in captured.err and "Traceback" not in captured.err


def test_render_safety_net_removes_partial_output(dummy_env, monkeypatch, capsys):
    # B-3 requires that if a partial write occurs before a render-side
    # exception, we'll need to return a single ERROR line that states the
    # failure. The process must return rc 1 and produce no output file.
    def boom(data, out_file, **kwargs):
        out_file.write_text("<html>partial")
        raise RuntimeError("render boom")

    monkeypatch.setattr(cli, "render_report", boom)
    archive = _build_archive(dummy_env, "net.zip", {})
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, ["--offline", str(archive)])()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    _assert_clean_cli_error(captured, "render boom")
    assert not (dummy_env / "output" / "report.html").exists()


# Container depth limits, cache write protections, and additional surrogate
# fields.

_JUNK_4800 = '[{"k":' * 2400 + "0" + "}]" * 2400  # 4800 alternating levels


def _deep_manifest_text():
    entry = json.dumps(_cs())[:-1] + ', "junk": ' + _JUNK_4800 + "}"
    return (
        '{"workspace": {"id": 1, "title": "T", "type": "osw"},'
        ' "changesets": [' + entry + "]}"
    )


def test_deep_container_manifest_clean_error(dummy_env, monkeypatch, capsys):
    # `json.loads` accepts nesting depths that exceed what `json.dumps` can
    # serialize, which caused cache dumps to crash with a raw `RecursionError`
    # when manifest values fell under the `loads` ceiling. The output must be a
    # single ERROR line without HTML or cache details.
    archive = dummy_env / "deep.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", _deep_manifest_text())
        zf.writestr("changesets/1.json", "{}")
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, ["--offline", str(archive)])()
    assert excinfo.value.code == 1
    _assert_clean_cli_error(
        capsys.readouterr(), "deep.zip", "JSON nesting level exceeds the storage limit"
    )
    assert not (dummy_env / "output" / "changesets_raw.json").exists()
    assert not (dummy_env / "output" / "report.html").exists()


def test_json_depth_limit_raises_value_error():
    ok = offline._loads("[" * 99 + "]" * 99, "unit")
    assert ok is not None
    with pytest.raises(
        ValueError, match="JSON nesting level exceeds the storage limit"
    ):
        offline._loads("[" * 101 + "]" * 101, "unit")
    with pytest.raises(
        ValueError, match="JSON nesting level exceeds the storage limit"
    ):
        offline._loads(_JUNK_4800, "unit")


def test_cache_write_guard_clean_error(dummy_env, monkeypatch, capsys):
    # The cache dump and write must produce a single ERROR line regardless of
    # which exception the serializer raises (providing a second layer of
    # protection behind the depth cap).
    archive = _manifest_zip(
        dummy_env / "net.zip",
        {**WS_META, "changesets": []},
    )

    def boom(*args, **kwargs):
        raise RecursionError("cache boom")

    monkeypatch.setattr(json, "dumps", boom)
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, ["--offline", str(archive)])()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    _assert_clean_cli_error(captured, "failed to cache", "cache boom")
    assert not (dummy_env / "output" / "changesets_raw.json").exists()


def test_quest_file_deep_values_clean_reject(dummy_env, monkeypatch, capsys):
    archive = _manifest_zip(dummy_env / "ok.zip", {**WS_META, "changesets": []})
    quest_file = dummy_env / "deep-q.json"
    quest_file.write_text('{"elements": ' + "[" * 121 + "]" * 121 + "}")
    _quest_cli_fail(
        monkeypatch,
        capsys,
        archive,
        quest_file,
        str(quest_file),
        "JSON nesting level exceeds the storage limit",
    )


def test_member_file_deep_junk_clean_error(dummy_env, monkeypatch, capsys):
    member = '{"junk": ' + _JUNK_4800 + "}"
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "deep-member.zip",
        {**WS_META, "changesets": [_cs()]},
        {"changesets/1.json": member},
        ["changesets/1.json", "JSON nesting level exceeds the storage limit"],
        name_archive=False,
    )


def test_quest_type_tag_surrogate_clean_error(dummy_env, monkeypatch, capsys):
    # Jinja renders the values of `quest_type` tags as raw text in the Quest
    # Types breakdown. When we encounter a lone surrogate, it triggers the same
    # `write_text` crash seen in round-10 fields.
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "qt-sur.zip",
        {
            **WS_META,
            "changesets": [
                _cs(tags={"created_by": "GIG test", "quest_type": "Sidewalks\ud801"})
            ],
        },
        {"changesets/1.json": _CREATE_TAGGED},
        ["entry 0", "tags.quest_type", "surrogate"],
    )


def test_choice_text_surrogate_clean_cli_error(dummy_env, monkeypatch, capsys):
    # The Labels view renders `display_choice` raw, so we need to reject
    # `choice_text` with a lone surrogate during load. Because they never
    # render raw, we accept extra choice keys and choice "value" strings.
    def definition(text):
        q = json.loads(json.dumps(_SURFACE_QUEST_DEF))
        q["elements"][0]["quests"][0]["quest_answer_choices"] = [
            {"value": "yes", "choice_text": text},
            {"value": "no"},
        ]
        return q

    archive = _build_archive(dummy_env, "ct-sur.zip", {}, member=_EXT_NODE_MEMBER)
    quest_file = _quest_file(dummy_env, "cts.json", definition("Yes\ud802"))
    _quest_cli_fail(
        monkeypatch,
        capsys,
        archive,
        quest_file,
        str(quest_file),
        "choice_text",
        "surrogate",
    )
    benign = json.loads(json.dumps(definition("Yes")))
    benign["elements"][0]["quests"][0]["quest_answer_choices"][0] = {
        "value": "ye\ud802s",
        "choice_text": "Yes",
        "other": "x\ud802",
    }
    quest_file = _quest_file(dummy_env, "ctb.json", benign)
    _run(monkeypatch, ["--offline", str(archive), "--quest-file", str(quest_file)])()
    captured = capsys.readouterr()
    assert "ERROR" not in captured.err and "Traceback" not in captured.err
