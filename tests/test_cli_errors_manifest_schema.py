"""Tests error handling for the manifest schema at the CLI boundary."""

import json
import sys
import zipfile

import pytest

from contribution_reports import cli, offline

from _cli_errors_helpers import (
    WS_META,
    _CREATE_TAGGED,
    _assert_clean_cli_error,
    _cs,
    _manifest_zip,
    _quest_cli_fail,
    _quest_def,
    _quest_file,
    _run,
    _run_offline,
)


def test_offline_created_at_non_string_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "cs-int-date.zip",
        {**WS_META, "changesets": [_cs(created_at=12345)]},
        None,
        ["entry 0", "created_at"],
    )


def test_offline_created_at_unparseable_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "cs-garbage-date.zip",
        {**WS_META, "changesets": [_cs(created_at="garbage")]},
        None,
        ["entry 0", "created_at", "garbage"],
    )


def test_api_timestamps_render_offline(dummy_env, monkeypatch, capsys):
    # We need to ensure that timestamps from the real API--including both Z and
    # millisecond-Z formats--continue to render.
    archive = _manifest_zip(
        dummy_env / "real-ts.zip",
        {
            **WS_META,
            "changesets": [
                _cs(created_at="2024-08-29T16:56:03Z"),
                _cs(id=2, created_at="2024-08-29T16:56:03.000Z"),
            ],
        },
        {"changesets/1.json": _CREATE_TAGGED},
    )
    _run(monkeypatch, ["--offline", str(archive)])()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    assert (dummy_env / "output" / "report.html").exists()


def test_offline_entry_tags_non_object_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "tags-str.zip",
        {**WS_META, "changesets": [_cs(tags="notadict")]},
        None,
        ["entry 0", "tags"],
    )


def test_offline_entry_non_string_user_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "user-int.zip",
        {**WS_META, "changesets": [_cs(user=5)]},
        {"changesets/1.json": _CREATE_TAGGED},
        ["entry 0", "user"],
    )


def test_offline_entry_geo_non_number_clean_error(dummy_env, monkeypatch, capsys):
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
                {"id": 1, "version": 1},
                {"id": 2, "version": 1},
            ]
        }
    )
    entries = {
        "min_lat": "x",
        "min_lon": 1.0,
        "max_lat": 2.0,
        "max_lon": 3.0,
    }
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "geo-str.zip",
        {**WS_META, "changesets": [_cs(**entries)]},
        {"changesets/1.json": created_way},
        ["entry 0", "min_lat"],
    )
    # Downstream processes treat booleans as numbers because
    # `float(True) == 1.0`, so these values load into a complete bbox at the
    # loader level. However, position fields starting with `elem_*` still
    # reject non-numeric input.
    offline.load_offline_archive(
        _manifest_zip(
            dummy_env / "geo-bool.zip",
            {
                **WS_META,
                "changesets": [
                    _cs(min_lat=1.0, min_lon=1.0, max_lat=2.0, max_lon=False)
                ],
            },
            {"changesets/1.json": created_way},
        )
    )
    with pytest.raises(ValueError, match="elem_lat"):
        offline.load_offline_archive(
            _manifest_zip(
                dummy_env / "geo-elem.zip",
                {**WS_META, "changesets": [_cs(elem_lat="x")]},
            )
        )
    # We keep `None` allowed because downstream code already treats it as
    # absent.
    offline.load_offline_archive(
        _manifest_zip(
            dummy_env / "geo-none.zip",
            {**WS_META, "changesets": [_cs(min_lat=None, max_lat=None)]},
            {"changesets/1.json": created_way},
        )
    )


def test_offline_member_json_not_object_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "member-array.zip",
        {**WS_META, "changesets": [_cs()]},
        {"changesets/1.json": "[1, 2]"},
        ["changesets/1.json", "OSC JSON requires an object format"],
        name_archive=False,
    )


def test_offline_element_tags_not_object_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "elem-tags-list.zip",
        {**WS_META, "changesets": [_cs()]},
        {"changesets/1.json": json.dumps({"create": [{"id": 7, "tags": [1, 2]}]})},
        ["changesets/1.json", "7"],
        name_archive=False,
    )


def _zip_with_lying_member(path, manifest):
    # We mutate member data after writing, so the stored CRC does not match the
    # bytes.
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("changesets/1.json", '{"create":[]}')
    info = zipfile.ZipFile(path).getinfo("changesets/1.json")
    data_off = info.header_offset + 30 + len(info.filename) + len(info.extra)
    with path.open("rb+") as f:
        f.seek(data_off)
        f.write(b'{"create":[XX')
    return path


def test_offline_corrupt_zip_member_clean_error(dummy_env, monkeypatch, capsys):
    archive = _zip_with_lying_member(
        dummy_env / "bad-crc.zip", {**WS_META, "changesets": [_cs()]}
    )
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, ["--offline", str(archive)])()
    assert excinfo.value.code == 1
    _assert_clean_cli_error(capsys.readouterr(), "bad-crc.zip", "changesets/1.json")


def test_offline_corrupt_zip_manifest_clean_error(dummy_env, monkeypatch, capsys):
    archive = _zip_with_lying_member(
        dummy_env / "bad-crc-manifest.zip", {**WS_META, "changesets": [_cs()]}
    )
    info = zipfile.ZipFile(archive).getinfo("manifest.json")
    data_off = info.header_offset + 30 + len(info.filename) + len(info.extra)
    with archive.open("rb+") as f:
        f.seek(data_off)
        f.write(b'{"workspace":{"idXX')
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, ["--offline", str(archive)])()
    assert excinfo.value.code == 1
    _assert_clean_cli_error(
        capsys.readouterr(), "bad-crc-manifest.zip", "manifest.json"
    )


QUEST_HOSTILE_SHAPES = [
    {"elements": [1]},
    {"elements": 5},
    5,
    {"elements": [{}]},
    {"elements": [{"element_type": "node", "quests": 5}]},
    {"elements": [{"element_type": "node", "quests": ["x"]}]},
    {"elements": [{"element_type": "node", "quests": [{"quest_tag": "surface"}]}]},
    {
        "elements": [
            {"element_type": "node", "quests": [{"quest_tag": 5, "quest_title": "T"}]}
        ]
    },
]


def test_offline_quest_file_hostile_shapes_clean_error(dummy_env, monkeypatch, capsys):
    archive = _manifest_zip(dummy_env / "ok.zip", {**WS_META, "changesets": []})
    for i, shape in enumerate(QUEST_HOSTILE_SHAPES):
        quest_file = dummy_env / f"hostile{i}.json"
        quest_file.write_text(json.dumps(shape))
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
        assert excinfo.value.code == 1, f"shape {shape!r}"
        captured = capsys.readouterr()
        assert captured.err.startswith("ERROR:"), f"shape {shape!r}"
        assert len(captured.err.strip().splitlines()) == 1, (
            f"shape {shape!r}: {captured.err}"
        )
        assert str(quest_file) in captured.err, f"shape {shape!r}"
        assert "Traceback" not in captured.err


def test_offline_quest_rejects_int_element_type(dummy_env, monkeypatch, capsys):
    # We need to reject scalar element_type values because index keys pass
    # through template k.replace. A non-string value fails at load even when
    # changesets remain empty and never reach the render-time path.
    archive = _manifest_zip(dummy_env / "ok.zip", {**WS_META, "changesets": []})
    quest_file = _quest_file(dummy_env, "etype.json", _quest_def(element_type=5))
    _quest_cli_fail(
        monkeypatch,
        capsys,
        archive,
        quest_file,
        str(quest_file),
        "element_type",
        "requires a string",
    )
