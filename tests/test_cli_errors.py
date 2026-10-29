"""Tests boundary error handling when generating offline reports via the CLI.

We verify that missing archives, missing quest files, and invalid zip files
cause a `SystemExit`, outputting an `ERROR:` message without a traceback. We
also check that `offline.load_offline_archive` raises a `ValueError` when it
encounters files that are not valid zip archives or archives missing a
`manifest.json`.

We specifically test for:
- Archives that lack a `manifest.json` (including empty zips).
- Files that are not valid zip archives or are corrupt.
- JSON corruption within changeset members.
- Archive members exceeding the `_MAX_MEMBER_BYTES` limit.

Additionally, we confirm that archives with zero changesets render cleanly by
falling back to an Unknown date instead of crashing.
"""

import json
import zipfile

import pytest

from contribution_reports import offline
from contribution_reports.render import render_report

from _cli_errors_helpers import _run, _valid_archive


def test_offline_missing_archive_clean_error(dummy_env, monkeypatch, capsys):
    run = _run(monkeypatch, ["--offline", str(dummy_env / "nope.zip")])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "ERROR:" in captured.err
    assert "nope.zip" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_offline_missing_quest_file_clean_error(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "ok.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {"workspace": {"id": 1, "title": "T", "type": "osw"}, "changesets": []}
            ),
        )
    run = _run(
        monkeypatch,
        ["--offline", str(archive), "--quest-file", str(dummy_env / "nope.json")],
    )
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "ERROR:" in captured.err
    assert "nope.json" in captured.err
    assert "Traceback" not in captured.err


def test_loader_rejects_offline_non_zip_file_with_value_error(tmp_path):
    archive = tmp_path / "notazip.bin"
    archive.write_text("not a zip file\n")
    with pytest.raises(ValueError) as excinfo:
        offline.load_offline_archive(archive)
    assert str(archive) in str(excinfo.value)
    assert "is neither a proper zip file nor an unpacked folder" in str(excinfo.value)


def test_loader_raises_value_error_when_offline_zip_lacks_manifest(tmp_path):
    archive = tmp_path / "nomanifest.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("other.txt", "hello")
    with pytest.raises(ValueError) as excinfo:
        offline.load_offline_archive(archive)
    assert str(archive) in str(excinfo.value)
    assert "missing manifest.json in archive" in str(excinfo.value)


def test_offline_non_zip_clean_error(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "notazip.bin"
    archive.write_text("not a zip file\n")
    run = _run(monkeypatch, ["--offline", str(archive)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "notazip.bin" in captured.err
    assert "is neither a proper zip file nor an unpacked folder" in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_offline_zip_no_manifest_clean_error(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "nomanifest.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("other.txt", "hello")
    run = _run(monkeypatch, ["--offline", str(archive)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "nomanifest.zip" in captured.err
    assert "missing manifest.json in archive" in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_offline_empty_zip_raises_clean_error(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "empty.zip"
    with zipfile.ZipFile(archive, "w"):
        pass
    run = _run(monkeypatch, ["--offline", str(archive)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "missing manifest.json in archive" in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err


def test_offline_corrupt_zip_file_clean_error(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "broken.zip"
    archive.write_bytes(b"PK\x03\x04garbage-not-a-zip")
    run = _run(monkeypatch, ["--offline", str(archive)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "broken.zip" in captured.err
    assert "is neither a proper zip file nor an unpacked folder" in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err


def test_offline_corrupt_changeset_json_clean_error(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "badmember.zip"
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
        zf.writestr("changesets/1.json", "{corrupt")
    run = _run(monkeypatch, ["--offline", str(archive)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err


def test_offline_oversized_member_clean_error(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "big.zip"
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
        zf.writestr("changesets/1.json", json.dumps({"create": []}))
    monkeypatch.setattr("contribution_reports.offline._MAX_MEMBER_BYTES", 4)
    run = _run(monkeypatch, ["--offline", str(archive)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "changesets/1.json" in captured.err
    assert "Traceback" not in captured.err


def test_offline_archive_with_empty_changesets_renders_unknown_date(tmp_path):
    # We need to verify that a valid archive containing zero changesets renders
    # cleanly. Because such archives lack any created_at field, we need the
    # report to use the Unknown-date fallback instead of crashing while parsing
    # an empty summary date.
    archive = tmp_path / "no-changesets.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {"workspace": {"id": 1, "title": "T", "type": "osw"}, "changesets": []}
            ),
        )
    data = offline.load_offline_archive(archive)
    out = tmp_path / "report.html"
    render_report(data, out)
    assert "Unknown date" in out.read_text(encoding="utf-8")


def test_offline_empty_changesets_render_clean(dummy_env, monkeypatch, capsys):
    archive = dummy_env / "no-changesets.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {"workspace": {"id": 1, "title": "T", "type": "osw"}, "changesets": []}
            ),
        )
    run = _run(monkeypatch, ["--offline", str(archive)])
    run()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    html = (dummy_env / "output" / "report.html").read_text(encoding="utf-8")
    assert "Unknown date" in html


def test_invalid_date_produces_clean_error(dummy_env, monkeypatch, capsys):
    run = _run(monkeypatch, ["1", "--date", "not-a-date"])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "not-a-date" in captured.err
    assert "Traceback" not in captured.err


def test_output_path_is_directory_clean_error(dummy_env, monkeypatch, capsys):
    archive = _valid_archive(dummy_env / "ok.zip")
    out_dir = dummy_env / "out-dir"
    out_dir.mkdir()
    run = _run(monkeypatch, ["--offline", str(archive), "--output", str(out_dir)])
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert str(out_dir) in captured.err
    assert "directory" in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    # We need to fail fast by running the check before we start any ingest
    # work.
    assert "Loading offline archive" not in captured.out
