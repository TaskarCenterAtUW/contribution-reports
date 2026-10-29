"""Tests error handling at the CLI boundary during archive intake.

We verify that the CLI returns an exit code and prints a single-line error
message starting with ERROR: without a traceback when:
- a directory is passed to `--cache-file`
- a manifest entry is not an object
- a manifest entry lacks an `id`
- an action element is not an object
- `manifest.json` is not a JSON object
- the `changesets` field in the manifest is not a list

We also test that `offline.load_offline_archive` raises a `ValueError` with
specific details about the offending archive entry, file path, or missing field
when processing these same malformed archives.
"""

import json
import zipfile

import pytest

from contribution_reports import offline

from _cli_errors_helpers import (
    WS_META,
    _CREATE_TAGGED,
    _cs,
    _manifest_zip,
    _run,
    _run_offline,
    _valid_archive,
)


def test_cache_file_path_is_directory_clean_error(dummy_env, monkeypatch, capsys):
    archive = _valid_archive(dummy_env / "ok.zip")
    cache_dir = dummy_env / "cache-dir"
    cache_dir.mkdir()
    run = _run(monkeypatch, ["--offline", str(archive), "--cache-file", str(cache_dir)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert str(cache_dir) in captured.err
    assert "directory" in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_loader_rejects_offline_manifest_entry_that_is_not_an_object(tmp_path):
    archive = tmp_path / "bad-entry.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "workspace": {"id": 1, "title": "T", "type": "osw"},
                    "changesets": [7],
                }
            ),
        )
    with pytest.raises(ValueError) as excinfo:
        offline.load_offline_archive(archive)
    assert str(archive) in str(excinfo.value)
    assert "entry 0" in str(excinfo.value)
    assert "must be an object" in str(excinfo.value)


def test_offline_manifest_entry_not_object_clean_error(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "bad-entry.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "workspace": {"id": 1, "title": "T", "type": "osw"},
                    "changesets": [7],
                }
            ),
        )
    run = _run(monkeypatch, ["--offline", str(archive)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "bad-entry.zip" in captured.err
    assert "must be an object" in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err


def test_loader_rejects_offline_manifest_entry_missing_id(tmp_path):
    archive = tmp_path / "no-id.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "workspace": {"id": 1, "title": "T", "type": "osw"},
                    "changesets": [{"created_at": "2026-06-01T00:00:00Z", "tags": {}}],
                }
            ),
        )
    with pytest.raises(ValueError) as excinfo:
        offline.load_offline_archive(archive)
    assert str(archive) in str(excinfo.value)
    assert "entry 0" in str(excinfo.value)
    assert "id" in str(excinfo.value)


def test_offline_manifest_entry_missing_id_clean_error(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "no-id.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "workspace": {"id": 1, "title": "T", "type": "osw"},
                    "changesets": [{"created_at": "2026-06-01T00:00:00Z", "tags": {}}],
                }
            ),
        )
    run = _run(monkeypatch, ["--offline", str(archive)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "no-id.zip" in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err


def test_loader_rejects_offline_action_element_that_is_not_an_object(tmp_path):
    archive = tmp_path / "bad-action.zip"
    with zipfile.ZipFile(archive, "w") as zf:
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
        zf.writestr("changesets/1.json", json.dumps({"create": [42]}))
    with pytest.raises(ValueError) as excinfo:
        offline.load_offline_archive(archive)
    assert "changesets/1.json" in str(excinfo.value)
    assert "create" in str(excinfo.value)
    assert "element that is not an object" in str(excinfo.value)


def test_offline_action_element_not_object_clean_error(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "bad-action.zip"
    with zipfile.ZipFile(archive, "w") as zf:
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
        zf.writestr("changesets/1.json", json.dumps({"create": [42]}))
    run = _run(monkeypatch, ["--offline", str(archive)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "changesets/1.json" in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err


def test_offline_manifest_not_object_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "list-manifest.zip",
        [1, 2],
        None,
        ["manifest.json needs to be structured as a JSON object"],
    )


def test_offline_manifest_raises_clean_error_when_changesets_is_not_a_list(
    dummy_env, monkeypatch, capsys
):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "cs-not-list.zip",
        {**WS_META, "changesets": 5},
        None,
        ["changesets", "is required to be a list"],
    )


def test_offline_mixed_int_str_ids_normalized_renders(dummy_env, monkeypatch, capsys):
    # String IDs containing only digits normalize to integers so that key
    # lookups and sorted() calls compare homogeneous values. This ensures the
    # report renders like any other archive.
    members = {"changesets/1.json": _CREATE_TAGGED, "changesets/2.json": _CREATE_TAGGED}
    archive = _manifest_zip(
        dummy_env / "mixed-ids.zip",
        {
            **WS_META,
            "changesets": [
                _cs(),
                _cs(id="2", user="other", created_at="2026-06-01T00:01:00Z"),
            ],
        },
        members,
    )
    _run(monkeypatch, ["--offline", str(archive)])()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    assert (dummy_env / "output" / "report.html").exists()


def test_offline_manifest_entry_invalid_id_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "bad-id.zip",
        {**WS_META, "changesets": [_cs(id=1.5)]},
        None,
        ["entry 0", "invalid id"],
    )
    # Bools and non-digit strings both cause rejection at the loader level.
    with pytest.raises(ValueError, match="invalid id"):
        offline.load_offline_archive(
            _manifest_zip(
                dummy_env / "bad-id2.zip", {**WS_META, "changesets": [_cs(id="abc")]}
            )
        )
    with pytest.raises(ValueError, match="invalid id"):
        offline.load_offline_archive(
            _manifest_zip(
                dummy_env / "bad-id3.zip", {**WS_META, "changesets": [_cs(id=True)]}
            )
        )
