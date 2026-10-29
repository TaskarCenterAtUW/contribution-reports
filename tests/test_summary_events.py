import json
from pathlib import Path

import pytest

from contribution_reports import summary

EXAMPLES_CATALOG = Path(__file__).resolve().parent.parent / "examples" / "events.json"
REQUIRED_SLUGS = {"nda_vancouver", "nda_pierce", "nda_sedro_woolley", "nda_everett",
                  "leavenworth", "hth_renton", "hth_kirkland", "otp_seattle", "otp_redmond"}


def test_examples_catalog_loads_required_slugs_and_schema():
    catalog = summary.load_catalog(EXAMPLES_CATALOG)
    assert {e["slug"] for e in catalog} == REQUIRED_SLUGS
    for e in catalog:
        assert set(e) >= {"slug", "title", "use_window", "city", "lat", "lon"}
    assert not any(e["use_window"] for e in catalog
                   if e["slug"] in ("hth_kirkland", "otp_redmond"))


def test_load_catalog_raises_value_error_on_bad_items(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps([{"slug": "x"}]))
    with pytest.raises(ValueError):
        summary.load_catalog(f)


def test_load_catalog_rejects_non_list_top_level(tmp_path):
    f = tmp_path / "obj.json"
    f.write_text(json.dumps({"slug": "x"}))
    with pytest.raises(ValueError):
        summary.load_catalog(f)


def test_load_catalog_raises_value_error_when_items_are_not_objects(tmp_path):
    f = tmp_path / "nums.json"
    f.write_text(json.dumps([1, 2, 3]))
    with pytest.raises(ValueError):
        summary.load_catalog(f)


def test_auto_catalog_discovers_events_from_workspace_files(tmp_path):
    # Changeset entries contain the actual cache-schema positions in `elem_lat`
    # and `elem_lon`. Way changesets lack top-level `lat` and `lon` keys.
    cache = {"date": "2026-02-02", "workspaces": {
        "7": {"id": 7, "title": "Winter Walk", "quest_definition": None,
              "changesets": [
                  {"id": 3, "elem_lat": 10.0, "elem_lon": 20.0,
                   "created_at": "2026-02-02T10:00:00Z",
                   "tags": {"created_by": "GIG 1", "workspace": "7"}},
                  {"id": 4, "elem_lat": 12.0, "elem_lon": 24.0,
                   "created_at": "2026-02-02T10:05:00Z",
                   "tags": {"created_by": "GIG 1", "workspace": "7"}},
              ], "notes": []}}}
    (tmp_path / "changesets_winter_walk.json").write_text(json.dumps(cache))
    events = summary.auto_catalog_events(tmp_path)
    assert len(events) == 1
    event = events[0]
    assert event["slug"] == "winter_walk"
    assert event["title"] == "Winter Walk"
    assert event["use_window"] is True
    assert event["city"] == "Winter Walk"
    assert event["lat"] == pytest.approx(11.0)
    assert event["lon"] == pytest.approx(22.0)


def test_auto_catalog_falls_back_to_changeset_bbox_center(tmp_path):
    # The changeset bbox center provides the fallback when element coordinates
    # lack cache entries, which prevents the use of null island.
    cache = {"date": "2026-02-02", "workspaces": {
        "7": {"id": 7, "title": "Silent City", "quest_definition": None,
              "changesets": [
                  {"id": 5, "min_lat": 47.2, "min_lon": -122.6,
                   "max_lat": 47.6, "max_lon": -122.2,
                   "created_at": "2026-02-02T10:00:00Z",
                   "tags": {"created_by": "GIG 1", "workspace": "7"}},
              ], "notes": []}}}
    (tmp_path / "changesets_silent_city.json").write_text(json.dumps(cache))
    events = summary.auto_catalog_events(tmp_path)
    assert events[0]["lat"] == pytest.approx(47.4)
    assert events[0]["lon"] == pytest.approx(-122.4)


def test_auto_catalog_falls_back_to_per_element_geometries(tmp_path):
    cache = {"date": "2026-02-02", "workspaces": {
        "7": {"id": 7, "title": "Batched", "quest_definition": None,
              "changesets": [
                  {"id": 5, "all_elem_geoms": {"111": {"lat": 47.4, "lon": -122.4}},
                   "min_lat": 0.0, "min_lon": 0.0, "max_lat": 0.0, "max_lon": 0.0,
                   "created_at": "2026-02-02T10:00:00Z",
                   "tags": {"created_by": "GIG 1", "workspace": "7"}},
              ], "notes": []}}}
    (tmp_path / "changesets_batched.json").write_text(json.dumps(cache))
    events = summary.auto_catalog_events(tmp_path)
    assert events[0]["lat"] == pytest.approx(47.4)
    assert events[0]["lon"] == pytest.approx(-122.4)


def test_events_file_flag_assigns_the_provided_path():
    args = summary.parse_args(["--events-file", "x.json"])
    assert str(args.events_file) == "x.json"
