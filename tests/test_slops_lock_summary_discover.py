"""Regression tests for the summary and discover modules that prevent reappearance
of bugs found during slop-cleanup.
"""

import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from contribution_reports import discover, summary


# These tests lock the behavior of the auto-catalog within summary.py and how
# it handles default-path deltas.
def _one_ws_cache(title="WS"):
    return {
        "date": "2026-02-02",
        "workspaces": {
            "7": {
                "id": 7,
                "title": title,
                "quest_definition": None,
                "changesets": [
                    {
                        "id": 1,
                        "user": "sam",
                        "created_at": "2026-02-02T10:00:00Z",
                        "changes_count": 1,
                        "tags": {"created_by": "GIG 1"},
                    },
                ],
                "notes": [],
            },
        },
    }


def test_auto_catalog_warns_and_skips_unreadable_cache(tmp_path, capsys):
    (tmp_path / "changesets_good.json").write_text(
        json.dumps(_one_ws_cache()), encoding="utf-8"
    )
    (tmp_path / "changesets_broken.json").write_text("{not json", encoding="utf-8")
    events = summary.auto_catalog_events(tmp_path)
    assert [e["slug"] for e in events] == ["good"]
    err = capsys.readouterr().err
    assert "WARNING" in err and "changesets_broken.json" in err


def test_auto_catalog_positionless_cache_uses_zero_coordinates(tmp_path):
    cache = _one_ws_cache()
    cache["workspaces"]["7"]["changesets"] = []
    (tmp_path / "changesets_flat.json").write_text(json.dumps(cache), encoding="utf-8")
    event = summary.auto_catalog_events(tmp_path)[0]
    assert event["lat"] == 0.0 and event["lon"] == 0.0
    assert event["use_window"] is True


def test_summary_main_output_defaults_to_cache_dir(tmp_path, monkeypatch, capsys):
    (tmp_path / "changesets_evt.json").write_text(
        json.dumps(_one_ws_cache()), encoding="utf-8"
    )
    monkeypatch.setattr(sys, "argv", ["report-summary", "--cache-dir", str(tmp_path)])
    summary.main()
    out = tmp_path / "summary_contributions.html"
    assert out.exists() and out.read_text(encoding="utf-8")
    captured = capsys.readouterr().out
    assert captured.startswith("Wrote")
    assert "1 events, 0 skipped" in captured


def test_summary_main_defaults_cache_dir_to_cwd_output(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    (output / "changesets_evt.json").write_text(
        json.dumps(_one_ws_cache()), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["report-summary"])
    summary.main()
    assert (output / "summary_contributions.html").exists()


def test_summary_catalog_missing_keys_raises_value_error(tmp_path):
    f = tmp_path / "cat.json"
    f.write_text(json.dumps([{"slug": "x", "title": "T"}]), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        summary.load_catalog(f)
    msg = str(excinfo.value)
    for key in ("use_window", "city", "lat", "lon"):
        assert key in msg


# discover.py flows
def test_parse_cs_time_precedence_and_garbage():
    expected = datetime(2026, 5, 1, 12, 30, tzinfo=timezone.utc)
    assert discover.parse_cs_time({"created_at": "2026-05-01T12:30:00Z"}) == expected
    assert discover.parse_cs_time({"closed_at": "2026-05-01T12:30:00Z"}) == expected
    assert (
        discover.parse_cs_time(
            {"created_at": "2026-05-01T12:30:00Z", "closed_at": "2020-01-01T00:00:00Z"}
        )
        == expected
    )
    assert discover.parse_cs_time({"created_at": "garbage"}) is None
    assert discover.parse_cs_time({}) is None


def test_fetch_osc_os_error_warns_and_returns_none(monkeypatch, capsys):
    def _boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert discover.fetch_osc("http://osm.test", 3, 99) is None
    out = capsys.readouterr().out
    assert "WARNING" in out and "99" in out


def test_render_cached_discovered_no_files_message(tmp_path, capsys):
    discover.render_cached_discovered(tmp_path / "discovered")
    assert "No cached discovered-workspace files exist" in capsys.readouterr().out
    assert not (tmp_path / "discovered").exists()


def test_render_cached_discovered_renders_each_slug_sorted(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        discover,
        "render_report",
        lambda data, out, **kw: seen.append((out, kw)),
    )
    disc = tmp_path / "discovered"
    disc.mkdir()
    (disc / "changesets_beta.json").write_text(json.dumps({"workspaces": {}}))
    (disc / "changesets_alpha.json").write_text(json.dumps({"workspaces": {}}))

    discover.render_cached_discovered(tmp_path, app_filter=("Q",))

    outs = [str(out) for out, _kw in seen]
    assert outs == [str(disc / "report_alpha.html"), str(disc / "report_beta.html")]
    assert all(kw["app_filter"] == ("Q",) for _out, kw in seen)


def test_run_discover_raises_system_exit_when_selector_is_missing():
    args = SimpleNamespace(workspace_ids=[], dry_run=False, title_match=[])
    with pytest.raises(SystemExit) as excinfo:
        discover.run_discover(args, "http://osm.test", "http://api.test", None)
    assert excinfo.value.code == 1


def test_run_discover_exits_zero_when_no_title_matches(monkeypatch):
    monkeypatch.setattr(
        discover,
        "http_get_json",
        lambda url, headers: [{"id": 1, "title": "Zulu Project"}],
    )
    args = SimpleNamespace(workspace_ids=[], dry_run=False, title_match=["NDA"])
    with pytest.raises(SystemExit) as excinfo:
        discover.run_discover(args, "http://osm.test", "http://api.test", None)
    assert excinfo.value.code == 0


def test_run_discover_returns_none_without_workspace_windows(monkeypatch):
    monkeypatch.setattr(
        discover,
        "fetch_workspace_info",
        lambda wid, api, tok: {"id": wid, "title": "T", "type": "osw"},
    )
    monkeypatch.setattr(discover, "fetch_all_changesets", lambda osm, ws: [])
    args = SimpleNamespace(workspace_ids=[1], dry_run=False, title_match=[])
    assert (
        discover.run_discover(args, "http://osm.test", "http://api.test", None) is None
    )


def test_run_discover_dry_run_does_not_fetch_quest_definitions(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("dry run must not fetch quest definitions or OSC")

    monkeypatch.setattr(
        discover,
        "fetch_workspace_info",
        lambda wid, api, tok: {"id": wid, "title": "T", "type": "osw"},
    )
    monkeypatch.setattr(
        discover,
        "fetch_all_changesets",
        lambda osm, ws: [
            {
                "id": 1,
                "created_at": "2026-05-01T10:00:00Z",
                "tags": {"created_by": "GIG 1"},
            },
            {
                "id": 2,
                "created_at": "2026-05-01T10:01:00Z",
                "tags": {"created_by": "GIG 1"},
            },
        ],
    )
    monkeypatch.setattr(discover, "fetch_quest_definition", _boom)
    monkeypatch.setattr(discover, "fetch_changesets_in_window", _boom)
    args = SimpleNamespace(workspace_ids=[1], dry_run=True, title_match=[])
    assert (
        discover.run_discover(args, "http://osm.test", "http://api.test", None) is None
    )
