import json

from contribution_reports import overpass


def _capture(monkeypatch):
    seen = {}

    def fake_post(url, params, headers=None):
        seen["url"] = url
        seen["headers"] = headers
        return json.dumps({"elements": []})

    monkeypatch.setattr(overpass, "http_post_form", fake_post)
    return seen


def test_fetch_roads_sends_bearer_token(monkeypatch):
    seen = _capture(monkeypatch)
    overpass.fetch_roads_near_points([(47.66, -122.33)], overpass_url="https://mirror", overpass_token="tok")
    assert seen["url"] == "https://mirror"
    assert seen["headers"]["Authorization"] == "Bearer tok"


def test_fetch_roads_omits_auth_without_token(monkeypatch):
    seen = _capture(monkeypatch)
    overpass.fetch_roads_near_points([(47.66, -122.33)], overpass_url="https://mirror")
    assert "Authorization" not in seen["headers"]
