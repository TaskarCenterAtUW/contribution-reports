from pathlib import Path

from contribution_reports.osw.extract import elements_to_final, extract_path, fetch_map_extract
from contribution_reports.osw.state import build_state


def test_extract_path_places_result_in_same_directory_as_cache():
    assert extract_path(Path("/out/osw_richland.json.gz")) == \
        Path("/out/osw_richland_extract.json.gz")


def test_fetch_map_extract_includes_bounding_box_in_request_url(monkeypatch):
    seen = {}

    def fake(url, headers, **kw):
        seen["url"] = url
        seen["headers"] = headers
        return {"elements": [{"type": "node", "id": 1, "tags": {}}]}

    monkeypatch.setattr("contribution_reports.osw.extract.fetch_json", fake)
    result = fetch_map_extract("http://osm", 1280, [-119.4, 46.1, -119.2, 46.3], "tok")
    assert "bbox=-119.4,46.1,-119.2,46.3" in seen["url"]
    assert seen["headers"]["X-Workspace"] == "1280"
    assert len(result) == 1


def test_fetch_map_extract_returns_empty_list_when_bbox_is_none():
    assert fetch_map_extract("http://osm", 1280, None, "tok") == []


def test_elements_to_final_shape_feeds_build_state_unchanged():
    elements = [
        {"type": "node", "id": 1, "version": 3,
         "tags": {"barrier": "kerb", "kerb": "lowered", "tactile_paving": "no"}},
        {"type": "way", "id": 2, "version": 1, "tags": {}},
    ]
    final = elements_to_final(elements)
    assert final[("node", 1)] == {
        "tags": {"barrier": "kerb", "kerb": "lowered", "tactile_paving": "no"},
        "version": 3, "deleted": False}
    # feeds build_state unchanged
    state = build_state(final)
    assert state["entities"]["Curb Ramp"]["count"] == 1
    assert state["live"] == 2


def test_elements_to_final_sets_missing_tags_to_empty():
    final = elements_to_final([{"type": "node", "id": 1, "version": 1}])
    assert final[("node", 1)]["tags"] == {}
