"""Behavior locks for the cleanup pass over *summary.py*.

We use each test to pin an observable behavior from the pre-cleanup code that
isn't covered by the current suite, so the cleanup diff cannot alter what the
one-pager renders.
"""

from datetime import date

from contribution_reports.render import format_date, format_date_range
from contribution_reports.summary import EventStats, aggregate, render_summary


def _event(title="Solo", dmin=date(2026, 5, 19), dmax=None, quests=2, notes=1):
    return EventStats(
        title=title,
        city="Town",
        lat=47.0,
        lon=-122.0,
        quests=quests,
        notes=notes,
        contributors={"sam"},
        element_mix={},
        features=0,
        date_min=dmin,
        date_max=dmax if dmax is not None else dmin,
    )


def test_aggregate_with_single_day_span_records_date_span_as_single_date():
    agg = aggregate([_event()])
    assert agg["date_span"] == format_date(date(2026, 5, 19))


def test_aggregate_uses_range_format_for_multi_day_spans():
    agg = aggregate([_event(dmin=date(2026, 5, 19), dmax=date(2026, 5, 22))])
    assert agg["date_span"] == format_date_range(date(2026, 5, 19), date(2026, 5, 22))


def test_aggregate_undated_events_returns_unknown_date_span():
    agg = aggregate([_event(dmin=None)])
    assert agg["date_span"] == "Unknown dates"


def test_row_date_string_with_single_date_range_and_empty_states():
    agg = aggregate(
        [
            _event(title="One day"),
            _event(title="Range", dmin=date(2026, 5, 1), dmax=date(2026, 5, 9)),
            _event(title="No dates", dmin=None),
        ]
    )
    by_title = {row["title"]: row["date_str"] for row in agg["events"]}
    assert by_title["One day"] == format_date(date(2026, 5, 19))
    assert by_title["Range"] == format_date_range(date(2026, 5, 1), date(2026, 5, 9))
    assert by_title["No dates"] == ""


def test_render_summary_treats_missing_skipped_key_as_zero(tmp_path):
    ctx = aggregate([_event()])
    out_plain = tmp_path / "plain.html"
    out_zero = tmp_path / "zero.html"
    render_summary(dict(ctx), "T", out_plain)
    render_summary(dict(ctx, skipped=0), "T", out_zero)
    html = out_plain.read_text(encoding="utf-8")
    assert html == out_zero.read_text(encoding="utf-8")
    assert "cached report(s) unavailable" not in html


def test_render_summary_renders_note_when_reports_are_skipped(tmp_path):
    out = tmp_path / "skipped.html"
    render_summary(dict(aggregate([_event()]), skipped=2), "T", out)
    assert "(2 cached report(s) unavailable)" in out.read_text(encoding="utf-8")
