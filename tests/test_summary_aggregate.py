"""Aggregates contribution summary data across multiple events."""

from datetime import date

from contribution_reports.constants import ELEMENT_TYPE_COLORS
from contribution_reports.summary import aggregate

from _summary_helpers import _stats



def test_aggregate_totals_and_deduplicate_contributors():
    agg = aggregate(
        [
            _stats(
                "Newer",
                date(2026, 5, 19),
                10,
                2,
                {"sam", "nia"},
                mix={"Sidewalks": 8},
                features=4,
            ),
            _stats(
                "Older",
                date(2024, 12, 26),
                5,
                1,
                {"sam", "jo"},
                mix={"Crossings": 3},
                features=2,
            ),
        ]
    )
    assert agg["totals"] == {
        "events": 2,
        "quests": 15,
        "questions": 0,  # we don't answer quests in the `_stats` fixture
        "notes": 3,
        "contributors": 3,
        "features": 6,
        "question_ratio_str": "0.0%",
    }


def test_aggregate_rows_in_chronological_order_with_scaled_bars():
    agg = aggregate(
        [
            _stats("Newer", date(2026, 5, 19), 10, 2, {"sam"}),
            _stats("Older", date(2024, 12, 26), 5, 1, {"sam"}),
        ]
    )
    assert [r["title"] for r in agg["events"]] == ["Older", "Newer"]
    assert agg["max_total"] == 12
    newer = agg["events"][1]
    assert newer["total"] == 12
    assert newer["q_pct"] == round(100 * 10 / 12, 1)
    assert newer["n_pct"] == round(100 * 2 / 12, 1)
    assert newer["r"] == round(6 + 22 * (12 / 12) ** 0.5, 1)



def test_aggregate_element_mix_merges_counts_and_preserves_order():
    agg = aggregate(
        [
            _stats(
                "A",
                date(2026, 5, 19),
                10,
                0,
                {"sam"},
                mix={"Sidewalks": 3, "Crossings": 1},
            ),
            _stats(
                "B",
                date(2025, 5, 19),
                10,
                0,
                {"kim"},
                mix={"Sidewalks": 2, "Curbs": 2, "other": 1},
            ),
        ]
    )
    assert [(m["type"], m["count"]) for m in agg["element_mix"]] == [
        ("Sidewalks", 5),
        ("Crossings", 1),
        ("Curbs", 2),
        ("other", 1),
    ]
    assert agg["element_mix"][0]["color"] == ELEMENT_TYPE_COLORS["Sidewalks"]
    assert agg["element_mix"][-1]["color"] == "#adb5bd"


def test_aggregate_calculates_date_span_and_handles_empty_input():
    agg = aggregate(
        [
            _stats("A", date(2026, 5, 19), 1, 0, {"sam"}),
            _stats("B", date(2024, 12, 26), 1, 0, {"kim"}),
        ]
    )
    assert "2024" in agg["date_span"] and "2026" in agg["date_span"]
    empty = aggregate([])
    assert empty["totals"]["events"] == 0
    assert empty["date_span"] == "Unknown dates"


def test_aggregate_sums_questions_across_events():
    older = _stats("B", date(2025, 5, 19), 3, 2, {"kim"})
    older.questions = 5
    newer = _stats("A", date(2026, 5, 19), 10, 1, {"sam"})
    newer.questions = 7
    agg = aggregate([older, newer])
    assert agg["totals"]["questions"] == 12


def test_aggregate_question_ratio_string_has_one_decimal_place():
    event = _stats("A", date(2026, 5, 19), 5, 1, {"sam"}, features=1)
    event.questions = 5
    agg = aggregate([event])
    # 5 / (5 + 1 + 1) = 71.428...%.
    assert agg["totals"]["question_ratio_str"] == "71.4%"


def test_aggregate_question_ratio_with_no_questions_returns_em_dash():
    agg = aggregate([])
    assert agg["totals"]["question_ratio_str"] == "—"
