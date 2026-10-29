from datetime import date, datetime, timezone

from contribution_reports import fetch
from contribution_reports.render import _local_date_str, _ws_event_date


def test_day_bounds_defaults_to_utc():
    start, end = fetch.day_bounds(date(2026, 10, 18))
    assert start == datetime(2026, 10, 18, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 19, tzinfo=timezone.utc)


def test_day_bounds_for_pacific_daylight_time():
    start, end = fetch.day_bounds(date(2026, 10, 18), "America/Los_Angeles")
    assert start == datetime(2026, 10, 18, 7, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 19, 7, tzinfo=timezone.utc)


def test_fetch_changesets_for_date_filters_by_created_at(monkeypatch):
    seen = {}

    def fake_fetch_all(osm_url, ws_id, token, lower_bound=None, upper_bound=None):
        seen["bounds"] = (lower_bound, upper_bound)
        return [
            {"id": 1, "created_at": "2026-10-18T06:59:59Z"},  # Oct 17 Pacific
            {"id": 2, "created_at": "2026-10-18T07:00:00Z"},  # midnight Pacific
            {"id": 3, "created_at": "2026-10-19T02:30:00Z"},  # Oct 18 evening Pacific
            {"id": 4, "created_at": "2026-10-19T07:00:00Z"},  # Oct 19 Pacific
        ]

    monkeypatch.setattr(fetch, "fetch_all_changesets", fake_fetch_all)
    result = fetch.fetch_changesets_for_date(
        "http://osm", 2166, date(2026, 10, 18), None, "America/Los_Angeles"
    )
    assert [cs["id"] for cs in result] == [2, 3]
    assert seen["bounds"] == fetch.day_bounds(date(2026, 10, 18), "America/Los_Angeles")


def test_fetch_all_changesets_only_includes_pages_within_bounds(monkeypatch):
    paths = []
    pages = [
        [{"id": i, "created_at": f"2026-10-18T{10 + i // 60:02d}:{i % 60:02d}:00Z"} for i in range(100, 200)],
        [{"id": 7, "created_at": "2026-10-18T08:00:00Z"}],
    ]

    def fake_get(osm_url, path, ws_id, token):
        paths.append(path)
        return {"changesets": pages[len(paths) - 1]}

    monkeypatch.setattr(fetch, "osm_get_json", fake_get)
    start, end = fetch.day_bounds(date(2026, 10, 18), "America/Los_Angeles")
    result = fetch.fetch_all_changesets("http://osm", 2166, None, lower_bound=start, upper_bound=end)
    assert len(result) == 101
    assert "time=2026-10-18T07%3A00%3A00Z%2C2026-10-19T07%3A00%3A00Z" in paths[0]
    assert "time=2026-10-18T07%3A00%3A00Z%2C2026-10-18T11%3A40%3A00Z" in paths[1]


def test_local_date_string_converts_to_time_zone():
    assert _local_date_str("2026-10-19T02:30:00Z") == "2026-10-19"
    assert _local_date_str("2026-10-19T02:30:00Z", "America/Los_Angeles") == "2026-10-18"


def test_ws_event_date_uses_zone():
    ws = {"changesets": [{"created_at": "2026-10-19T02:30:00Z"}]}
    assert _ws_event_date(ws, "x") == "2026-10-19"
    assert _ws_event_date(ws, "x", "America/Los_Angeles") == "2026-10-18"
