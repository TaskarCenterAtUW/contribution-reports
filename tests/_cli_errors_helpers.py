"""Provides shared builders for test modules that verify CLI error handling."""

import json
import sys
import zipfile

import pytest

from contribution_reports import cli


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["contribution-report", *argv])
    return cli.main


WS_META = {"workspace": {"id": 1, "title": "T", "type": "osw"}}


_APP_TAGS = {"created_by": "GIG test"}


def _manifest_zip(path, manifest, members=None):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, content in (members or {}).items():
            zf.writestr(name, content)
    return path


def _cs(**overrides):
    cs = {
        "id": 1,
        "user": "surveyor",
        "created_at": "2026-06-01T00:00:00Z",
        "tags": dict(_APP_TAGS),
        "changes_count": 1,
    }
    cs.update(overrides)
    return cs


_CREATE_TAGGED = json.dumps(
    {
        "create": [
            {"id": 1, "version": 1, "lat": 1.5, "lon": 1.5, "tags": {"highway": "path"}}
        ]
    }
)


def _assert_clean_cli_error(captured, *needles):
    assert captured.err.startswith("ERROR:")
    assert len(captured.err.strip().splitlines()) == 1
    for needle in needles:
        assert needle in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def _run_offline(
    dummy_env,
    monkeypatch,
    capsys,
    archive_name,
    manifest,
    members,
    needles,
    name_archive=True,
):
    archive = _manifest_zip(dummy_env / archive_name, manifest, members)
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, ["--offline", str(archive)])()
    assert excinfo.value.code == 1
    expected = (archive_name, *needles) if name_archive else needles
    _assert_clean_cli_error(capsys.readouterr(), *expected)


# These functions build CLI failure checks that rely on quest files.


def _quest_file(dummy_env, name, definition):
    path = dummy_env / name
    path.write_text(json.dumps(definition))
    return path


def _quest_def(element_type="Sidewalks", choices=None):
    quest = {"quest_tag": "surface", "quest_title": "Q"}
    if choices is not None:
        quest["quest_answer_choices"] = choices
    return {"elements": [{"element_type": element_type, "quests": [quest]}]}


_GEO_OK = {"min_lat": 1.0, "min_lon": 1.0, "max_lat": 2.0, "max_lon": 2.0}


def _quest_cli_fail(monkeypatch, capsys, archive, quest_file, *needles):
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
    _assert_clean_cli_error(capsys.readouterr(), *needles)


def _valid_archive(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "workspace": {"id": 1, "title": "T", "type": "osw"},
                    "changesets": [
                        {"id": 1, "created_at": "2026-06-01T00:00:00Z", "tags": {}}
                    ],
                }
            ),
        )
        zf.writestr("changesets/1.json", json.dumps({"create": []}))
    return path


# This archive harness provides a minimal single-changeset for testing CLI
# accept and reject checks.


_MINIMAL_CS = {
    "id": 1,
    "created_at": "2026-01-01T00:00:00Z",
    "changes_count": 1,
    "user": "U",
    "tags": {"created_by": "GIG app 1.0", "quest_type": "Sidewalks"},
    "min_lat": 1,
    "min_lon": 2,
    "max_lat": 3,
    "max_lon": 4,
}


_BARE_NODE_MEMBER = json.dumps(
    {"modify": [{"type": "node", "id": 1, "version": 1, "lat": 1, "lon": 2}]}
)


_EXT_NODE_MEMBER = json.dumps(
    {
        "modify": [
            {
                "type": "node",
                "id": 1,
                "version": 1,
                "lat": 1,
                "lon": 2,
                "tags": {"ext:surface": "yes"},
            }
        ]
    }
)


_SURFACE_QUEST_DEF = {
    "elements": [
        {
            "element_type": "Sidewalks",
            "quests": [{"quest_tag": "ext:surface", "quest_title": "Q"}],
        }
    ]
}


def _build_archive(dummy_env, name, over, member=_BARE_NODE_MEMBER, title="T"):
    cs = dict(_MINIMAL_CS)
    cs.update(over)
    ws = {"id": 1, "title": title, "type": "osw"}
    return _manifest_zip(
        dummy_env / name,
        {"workspace": ws, "changesets": [cs]},
        {"changesets/1.json": member},
    )


def _reject_cli(dummy_env, monkeypatch, capsys, archive, needles, quest=False):
    argv = ["--offline", str(archive)]
    if quest:
        argv += ["--quest-file", str(_quest_file(dummy_env, "q.json", _SURFACE_QUEST_DEF))]
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, argv)()
    assert excinfo.value.code == 1
    _assert_clean_cli_error(capsys.readouterr(), archive.name, *needles)


def _accept_cli(dummy_env, monkeypatch, capsys, archive, quest=False):
    argv = ["--offline", str(archive)]
    if quest:
        argv += ["--quest-file", str(_quest_file(dummy_env, "q.json", _SURFACE_QUEST_DEF))]
    _run(monkeypatch, argv)()
    captured = capsys.readouterr()
    assert "ERROR" not in captured.err and "Traceback" not in captured.err
