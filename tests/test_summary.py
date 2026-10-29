"""Verifies the one-page contribution summary program."""

from datetime import date

from contribution_reports.summary import load_event

from _summary_helpers import EVENT_A, EVENT_B, create_cs, quest_cs, write_cache



QUEST_DEF_TWO_Q = {
    "elements": [
        {
            "element_type": "Sidewalks",
            "quests": [
                {
                    "quest_tag": "ext:surface_quality",
                    "quest_title": "Surface quality",
                    "quest_answer_choices": [],
                },
                {
                    "quest_tag": "ext:lighting",
                    "quest_title": "Is it lit?",
                    "quest_answer_choices": [],
                },
            ],
        }
    ],
}


def multi_answer_cs(cs_id, user, ts, answers, created_by="GIG 1.2.2(1)"):
    """Simulates a single changeset that addresses multiple quest tags by
    modifying one node.
    """
    tags_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in answers.items())
    osc = (
        f'<osm><modify><node id="{cs_id}" version="1" changeset="{cs_id}" '
        f'lat="47.6" lon="-122.3">{tags_xml}</node></modify></osm>'
    )
    return {
        "id": cs_id,
        "user": user,
        "created_at": ts,
        "changes_count": 1,
        "tags": {"created_by": created_by},
        "osc_xml": osc,
    }


def _badge_total(q_counts):
    """Replicates the badge labeled 'X total' from *section.html.j2* by summing
    answer counts for every question-tag per element type.
    """
    return sum(
        sum(val_counts.values())
        for tag_counts in q_counts.values()
        for val_counts in tag_counts.values()
    )


def test_load_event_applies_app_filter(tmp_path):
    write_cache(
        tmp_path,
        "b",
        [
            quest_cs(1, "sam", "2026-05-19T18:00:00Z"),
            quest_cs(2, "sam", "2026-05-19T18:20:00Z"),
            {
                "id": 3,
                "user": "editor9",
                "created_at": "2026-05-19T18:30:00Z",
                "changes_count": 5,
                "tags": {"created_by": "Rapid 2.3.2"},
                "osc_xml": "",
            },
        ],
    )
    stats = load_event(EVENT_B, tmp_path)  # `use_window` off: pure filter test
    assert stats.quests == 2


def test_load_event_window_drops_outliers_notes_count_whole(tmp_path):
    write_cache(
        tmp_path,
        "a",
        [
            quest_cs(1, "sam", "2026-05-19T18:00:00Z"),
            quest_cs(2, "sam", "2026-05-19T18:10:00Z"),
            quest_cs(3, "kim", "2026-05-19T18:20:00Z"),
            quest_cs(4, "kim", "2026-05-19T22:00:00Z"),  # isolated late edit
        ],
        notes=[{"lat": 47.6, "lon": -122.3, "text": "missing ramp", "user": "nia"}],
    )
    stats = load_event(EVENT_A, tmp_path)
    assert stats.quests == 3  # the 22:00 outlier falls outside the window
    assert stats.notes == 1  # notes don't use windowing


def test_load_event_contributors_includes_users_from_notes(tmp_path):
    write_cache(
        tmp_path,
        "b",
        [quest_cs(1, "sam", "2026-05-19T18:00:00Z")],
        notes=[
            {"lat": 47.6, "lon": -122.3, "text": "x", "user": "nia"},
            {"lat": 47.6, "lon": -122.3, "text": "no author"},
        ],
    )
    stats = load_event(EVENT_B, tmp_path)
    assert stats.contributors == {"sam", "nia"}


def test_load_event_counts_only_created_features(tmp_path):
    write_cache(
        tmp_path,
        "b",
        [
            quest_cs(1, "sam", "2026-05-19T18:00:00Z"),
            create_cs(2, "sam", "2026-05-19T18:10:00Z"),
        ],
    )
    stats = load_event(EVENT_B, tmp_path)
    assert stats.features == 1


def test_load_event_records_date_range_and_element_mix(tmp_path):
    write_cache(
        tmp_path,
        "b",
        [
            quest_cs(1, "sam", "2026-05-19T18:00:00Z"),
            quest_cs(2, "kim", "2026-05-19T18:10:00Z"),
        ],
    )
    stats = load_event(EVENT_B, tmp_path)
    assert stats.date_min == stats.date_max == date(2026, 5, 19)
    assert stats.element_mix == {"Sidewalks": 2}


def test_load_event_with_missing_cache_warns_and_returns_none(tmp_path, capfd):
    assert load_event(EVENT_A, tmp_path) is None
    assert "changesets_a.json" in capfd.readouterr().err


def test_load_event_returns_none_when_empty_after_filtering(tmp_path, capfd):
    write_cache(
        tmp_path,
        "b",
        [
            {
                "id": 3,
                "user": "e",
                "created_at": "2026-05-19T18:00:00Z",
                "changes_count": 5,
                "tags": {"created_by": "Rapid 2.3.2"},
                "osc_xml": "",
            },
        ],
    )
    assert load_event(EVENT_B, tmp_path) is None
    assert "a" in capfd.readouterr().err


def test_load_event_question_count_matches_published_badge_pipeline(tmp_path):
    # An event contains app changesets that answer 4 quest questions total--one
    # changeset answers two--and an editor changeset with a quest tag the app
    # filter must drop.
    from contribution_reports.analysis import count_questions
    from contribution_reports.quests import build_quest_index

    cs_both = multi_answer_cs(
        1,
        "sam",
        "2026-05-19T18:00:00Z",
        {"ext:surface_quality": "poor", "ext:lighting": "no"},
    )
    cs_one = quest_cs(2, "kim", "2026-05-19T18:10:00Z", quest_def=QUEST_DEF_TWO_Q)
    cs_create = create_cs(3, "sam", "2026-05-19T18:20:00Z")
    cs_editor = multi_answer_cs(
        4,
        "editor9",
        "2026-05-19T18:30:00Z",
        {"ext:lighting": "yes"},
        created_by="Rapid 2.3.2",
    )
    write_cache(
        tmp_path,
        "b",
        [cs_both, cs_one, cs_create, cs_editor],
        quest_def=QUEST_DEF_TWO_Q,
    )
    # load_event reduces the event. This serves as a pure filter test because
    # we set use_window to off.
    stats = load_event(EVENT_B, tmp_path)
    # The question count matches the published badge when both use the same
    # pipeline. This badge comes from an independent computation.
    #
    # Both counts exclude the editor answer.
    app_filter = [cs_both, cs_one, cs_create]
    badge = _badge_total(
        count_questions(app_filter, build_quest_index(QUEST_DEF_TWO_Q))
    )
    assert stats.questions == badge == 4
