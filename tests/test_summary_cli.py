"""Tests the rendering and command-line interface paths for one-page contribution
summaries.
"""

import sys
from datetime import date

import pytest

from contribution_reports.summary import aggregate

from _summary_helpers import EVENT_A, EVENT_B, _stats, quest_cs, write_cache



def _fixture_aggregate():
    return aggregate(
        [
            _stats(
                "Event A",
                date(2024, 12, 26),
                12,
                0,
                {"sam", "kim", "nia"},
                mix={"Sidewalks": 10},
                features=3,
            ),
            _stats(
                "Event B",
                date(2026, 5, 19),
                3,
                2,
                {"jo"},
                mix={"Crossings": 1},
                features=1,
            ),
        ]
    )


def test_render_summary_basic_smoke_test(tmp_path):
    from contribution_reports.summary import render_summary

    out = tmp_path / "summary.html"
    ctx = _fixture_aggregate()
    ctx["skipped"] = 0
    render_summary(ctx, "Test Summary", out)
    html = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "Test Summary" in html
    assert 'id="op-map"' in html
    assert "Event A" in html and "Event B" in html
    assert "Contributors" in html and "New map features" in html
    assert "4" in html  # we find the contributors total in the stat row
    assert "op-map-fallback" in html  # offline map degradation is wired


def test_main_end_to_end(tmp_path, monkeypatch, capsys):
    import contribution_reports.summary as summary

    write_cache(
        tmp_path,
        "a",
        [
            quest_cs(1, "sam", "2026-05-19T18:00:00Z"),
            quest_cs(2, "kim", "2026-05-19T18:10:00Z"),
        ],
    )
    # The slug b cache is absent. The main function must warn the user, skip
    # this entry, and continue execution.
    monkeypatch.setattr(
        summary, "auto_catalog_events", lambda cache_dir: [EVENT_A, EVENT_B]
    )
    out = tmp_path / "onepager.html"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "report-summary",
            "--cache-dir",
            str(tmp_path),
            "--output",
            str(out),
            "--report-title",
            "CLI Summary",
        ],
    )
    summary.main()
    html = out.read_text(encoding="utf-8")
    assert "CLI Summary" in html
    assert "Event A" in html
    assert "1 (1 cache missing)" not in html  # skipped notices only count skips
    captured = capsys.readouterr()
    assert "1 skipped" in captured.out
    assert "changesets_b.json" in captured.err


def _run_summary_main(argv, monkeypatch):
    import contribution_reports.summary as summary

    monkeypatch.setattr(sys, "argv", ["report-summary", *argv])
    return summary.main


def test_main_malformed_events_file_clean_error(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{definitely not json", encoding="utf-8")
    run = _run_summary_main(
        ["--events-file", str(bad), "--output", str(tmp_path / "out.html")], monkeypatch
    )
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "Traceback" not in captured.err
    assert not (tmp_path / "out.html").exists()


def test_main_events_file_non_object_items_clean_error(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "nums.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    run = _run_summary_main(
        ["--events-file", str(bad), "--output", str(tmp_path / "out.html")], monkeypatch
    )
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "Traceback" not in captured.err


def test_main_missing_events_file_clean_error(tmp_path, monkeypatch, capsys):
    run = _run_summary_main(["--events-file", str(tmp_path / "nope.json")], monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        run()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "Traceback" not in captured.err
