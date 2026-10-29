import json
import urllib.parse
from datetime import datetime, timedelta, timezone

from contribution_reports import cli, discover


def test_title_matches_case_insensitive_prefix():
    assert discover.title_matches("NDA Vancouver Walk/Roll", ("nda",))
    assert not discover.title_matches("Other", ("nda",))
    assert discover.title_matches("NDA X", ("nope", "NDA"))


def test_slugify_generates_slugs_from_plain_strings():
    assert discover.slugify("NDA Pierce County Walk/Roll", 9) == "nda_pierce_county_walk_roll"
    assert discover.slugify("  Weard ## Name! ", 9) == "weard_name"
    assert discover.slugify("", 9) == "ws9"
    assert discover.slugify("###", 42) == "ws42"


def test_discover_flags_parse_correctly():
    a = cli.parse_args(["--discover", "--title-match", "NDA"])
    assert a.discover is True
    assert a.title_match == ["NDA"]


def test_write_discovered_reports_file_names(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(discover, "render_report",
                        lambda data, out, **kw: seen.append(data))
    data = {"date": "2026-01-01", "workspaces": {
        "12": {"id": 12, "title": "NDA Vancouver Walk/Roll",
               "event_date": "2026-01-01", "quest_definition": None,
               "changesets": [], "notes": []},
        "13": {"id": 13, "title": "", "quest_definition": None,
               "changesets": [], "notes": []},
    }}
    discover.write_discovered_reports(data, tmp_path)
    disc = tmp_path / "discovered"
    assert (disc / "changesets_nda_vancouver_walk_roll.json").exists()
    assert (disc / "changesets_ws13.json").exists()
    assert {frozenset(s["workspaces"]) for s in seen} == {frozenset({"12"}), frozenset({"13"})}


def test_write_discovered_reports_threads_app_filter(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(discover, "render_report",
                        lambda data, out, **kw: seen.append(kw))
    data = {"date": "2026-01-01", "workspaces": {
        "12": {"id": 12, "title": "NDA Vancouver Walk/Roll",
               "event_date": "2026-01-01", "quest_definition": None,
               "changesets": [], "notes": []},
    }}
    discover.write_discovered_reports(data, tmp_path, app_filter=())
    assert seen and all(kw["app_filter"] == () for kw in seen)


def _fake_page(changesets):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"changesets": changesets}).encode()

    return _Resp()


def _clock(minutes):
    ts = datetime(2026, 5, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_fetch_changesets_in_window_uses_pagination(monkeypatch):
    # The fake OSM API holds 250 changesets, and a single page contains 100.
    total = 250
    stored = [{"id": 0, "created_at": _clock(-60)}]
    stored += [{"id": i, "created_at": _clock(i)} for i in range(1, total + 1)]
    stored.append({"id": 999, "created_at": _clock(total + 60)})
    pages = []

    def fake_urlopen(req, *args, **kwargs):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        lower, upper = query["time"][0].split(",")
        windowed = [cs for cs in stored if lower < cs["created_at"] < upper]
        windowed.sort(key=lambda cs: cs["created_at"], reverse=True)
        page = windowed[:100]
        pages.append(len(page))
        return _fake_page(page)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=total + 1)

    result = discover.fetch_changesets_in_window("http://osm.test", 7, start, end)

    assert len(pages) > 1  # we test windows spanning multiple pages
    assert {cs["id"] for cs in result} == set(range(1, total + 1))


def test_fetch_all_changesets_does_not_raise_on_unparseable_times(monkeypatch):
    full_page = [{"id": i, "created_at": "nonsense"} for i in range(100)]
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, *a, **k: _fake_page(full_page))
    result = discover.fetch_all_changesets("http://osm.test", 7)
    assert len(result) == 100  # we get one page before the bail-out
