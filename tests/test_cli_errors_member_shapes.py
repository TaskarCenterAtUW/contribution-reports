"""Tests error handling at the CLI boundary for member shapes.

We verify that if the `workspace` key in an offline manifest is not an object,
the CLI shows a clean error stating it must be an object. If the key is absent
entirely, we check that it continues to use the default.

We test that JSON files nested too deeply trigger clean errors when we pass
them as a manifest via `--offline` or as a `--quest-file`.

For archives containing encrypted zip members, we verify the CLI rejects them
with a clean error stating the encrypted zip member is not supported.

We check that parse errors in OSC XML return empty results instead of crashing.

When we provide a `--quest-file` where a choice has an unhashable value, we
expect a clean error stating the surface must not be a JSON object/array. We
also verify that hashable values including strings, numbers, booleans, and
`None` remain accepted.

We test which forms of quest choices the upstream consumer tolerates. We verify
that strings, lists of strings, and dictionaries pass without error. We verify
that other shapes like integers, booleans, or lists of integers trigger a clean
error for `quest_answer_choices`.
"""

import json
import sys
import zipfile

import pytest

from contribution_reports import cli, offline

from _cli_errors_helpers import (
    WS_META,
    _GEO_OK,
    _assert_clean_cli_error,
    _cs,
    _manifest_zip,
    _quest_def,
    _quest_file,
    _run,
    _run_offline,
)


def test_offline_manifest_workspace_is_not_an_object_raises_clean_error(
    dummy_env, monkeypatch, capsys
):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "ws-int.zip",
        {"workspace": 5, "changesets": []},
        None,
        ["workspace", "requires an object value"],
    )
    # We default the workspace when it's absent.
    offline.load_offline_archive(
        _manifest_zip(dummy_env / "ws-absent.zip", {"changesets": []})
    )


def test_offline_nested_json_clean_error(dummy_env, monkeypatch, capsys):
    manifest_path = dummy_env / "deep.zip"
    with zipfile.ZipFile(manifest_path, "w") as zf:
        zf.writestr("manifest.json", "[" * 10000 + "]" * 10000)
    monkeypatch.setattr(
        sys, "argv", ["contribution-report", "--offline", str(manifest_path)]
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    _assert_clean_cli_error(captured, "deep.zip", "exceeds maximum nesting depth")

    quest_file = dummy_env / "deep-quest.json"
    quest_file.write_text("[" * 100000 + "]" * 100000)
    archive = _manifest_zip(dummy_env / "deep-ok.zip", {**WS_META, "changesets": []})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "contribution-report",
            "--offline",
            str(archive),
            "--quest-file",
            str(quest_file),
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    _assert_clean_cli_error(
        captured, "deep-quest.json", "exceeds maximum nesting depth"
    )


def _encrypted_member_zip(path):
    # We patch reserved flag words in the central directory entry and local
    # file header to fabricate a member with an encrypted flag. Then we verify
    # that reads raise a RuntimeError, because this error escapes the CLI's
    # error mapping.
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("manifest.json", json.dumps({**WS_META, "changesets": [_cs()]}))
        zf.writestr("changesets/1.json", '{"create":[]}')
    raw = bytearray(path.read_bytes())
    name = b"changesets/1.json"
    pos1 = raw.find(name)
    pos2 = raw.find(name, pos1 + 1)
    raw[pos1 - 24] |= 0x01
    raw[pos2 - 38] |= 0x01
    path.write_bytes(bytes(raw))
    return path


def test_offline_encrypted_zip_member_clean_error(dummy_env, monkeypatch, capsys):
    archive = _encrypted_member_zip(dummy_env / "enc.zip")
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, ["--offline", str(archive)])()
    assert excinfo.value.code == 1
    _assert_clean_cli_error(
        capsys.readouterr(),
        "enc.zip",
        "cannot accept encrypted zip member: changesets/1.json",
    )


def test_osc_parse_errors_return_empty_results():
    from contribution_reports.analysis import count_questions
    from contribution_reports.classify import parse_element_tags

    bad_xml = (
        '<osmChange version="0.6"><create><node id="1">'
        f'<tag k="a{chr(0x01)}b" v="x"/></node></create></osmChange>'
    )
    assert parse_element_tags(bad_xml) == {}
    assert (
        count_questions(
            [{"osc_xml": bad_xml}], {"highway": {"element_type": "X", "title": "T"}}
        )
        == {}
    )


def test_quest_choice_unhashable_clean_error(dummy_env, monkeypatch, capsys):
    archive = _manifest_zip(dummy_env / "ok.zip", {**WS_META, "changesets": []})
    for i, bad in enumerate(({"nested": 1}, [1, 2])):
        quest_file = _quest_file(
            dummy_env,
            f"choice{i}.json",
            _quest_def(choices=[{"value": bad}, {"value": "ok"}]),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "contribution-report",
                "--offline",
                str(archive),
                "--quest-file",
                str(quest_file),
            ],
        )
        with pytest.raises(SystemExit) as excinfo:
            cli.main()
        assert excinfo.value.code == 1, f"value {bad!r}"
        captured = capsys.readouterr()
        _assert_clean_cli_error(
            captured, str(quest_file), "surface", "cannot be a JSON array or object"
        )
    # We want to verify that every type of hashable choice value remains
    # acceptable.
    quest_file = _quest_file(
        dummy_env,
        "choice-hashable.json",
        _quest_def(
            choices=[
                {"value": "yes"},
                {"value": 3},
                {"value": 0.5},
                {"value": True},
                {"value": None},
            ]
        ),
    )
    offline.load_offline_archive(archive, quest_file)


def test_upstream_tolerates_quest_choice_forms(dummy_env, monkeypatch, capsys):
    # We can pass any iterable to the consumer, which skips entries that lack a
    # value in c.
    archive = _manifest_zip(dummy_env / "ok.zip", {**WS_META, "changesets": []})
    for name, shape in (("str", "abc"), ("liststr", ["yes", "no"]), ("dict", {"a": 1})):
        quest_file = _quest_file(
            dummy_env, f"ch-{name}.json", _quest_def(choices=shape)
        )
        _run(
            monkeypatch, ["--offline", str(archive), "--quest-file", str(quest_file)]
        )()
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err, name
        assert "ERROR" not in captured.err, name
    for name, shape in (("int", 5), ("true", True), ("listint", [5])):
        quest_file = _quest_file(
            dummy_env, f"chbad-{name}.json", _quest_def(choices=shape)
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "contribution-report",
                "--offline",
                str(archive),
                "--quest-file",
                str(quest_file),
            ],
        )
        with pytest.raises(SystemExit) as excinfo:
            cli.main()
        assert excinfo.value.code == 1, name
        _assert_clean_cli_error(
            capsys.readouterr(), str(quest_file), "quest_answer_choices"
        )


def test_osc_lat_validated_only_for_nodes(dummy_env, monkeypatch, capsys):
    # Upstream records lat/lon attributes only if the effective type is node.
    way = json.dumps(
        {
            "create": [
                {
                    "id": 2,
                    "version": 1,
                    "type": "way",
                    "nodes": [1],
                    "lat": "garbage",
                    "lon": None,
                    "tags": {"highway": "path"},
                },
            ]
        }
    )
    archive = _manifest_zip(
        dummy_env / "way-lat.zip",
        {**WS_META, "changesets": [_cs(**_GEO_OK)]},
        {"changesets/1.json": way},
    )
    _run(monkeypatch, ["--offline", str(archive)])()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "ERROR" not in captured.err
    for bad_node in (
        {
            "id": 1,
            "version": 1,
            "lat": "garbage",
            "lon": 1.0,
            "tags": {"highway": "path"},
        },
        {
            "id": 1,
            "version": 1,
            "type": "node",
            "lat": "garbage",
            "lon": 1.0,
            "tags": {"highway": "path"},
        },
    ):
        archive = _manifest_zip(
            dummy_env / f"node-lat-{bad_node.get('type', 'inf')}.zip",
            {**WS_META, "changesets": [_cs(**_GEO_OK)]},
            {"changesets/1.json": json.dumps({"create": [bad_node]})},
        )
        with pytest.raises(SystemExit) as excinfo:
            _run(monkeypatch, ["--offline", str(archive)])()
        assert excinfo.value.code == 1
        _assert_clean_cli_error(
            capsys.readouterr(), "changesets/1.json", "lat", "numeric"
        )
