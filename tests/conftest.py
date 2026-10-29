"""Pytest configuration shared across the contribution-reports package."""

import pytest

from contribution_reports import cli


@pytest.fixture
def dummy_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "load_env",
        lambda p=None: {
            "WS_OSM_URL": "http://osm.test",
            "WS_NEW_API_URL": "http://api.test",
        },
    )
    return tmp_path


def make_element(
    elem_type="node",
    elem_id=1,
    version=1,
    changeset=10,
    tags=None,
    lat=None,
    lon=None,
    nodes=None,
    user="Mapper",
    uid=341,
    visible=True,
):
    """Generates an adiff element dictionary that matches the shape of
    `AugmentedDiffResponse`.
    """
    return {
        "type": elem_type,
        "id": elem_id,
        "version": version,
        "changeset": changeset,
        "timestamp": "2026-06-01T00:00:00Z",
        "user": user,
        "uid": uid,
        "visible": visible,
        "tags": tags or {},
        "lat": lat,
        "lon": lon,
        "nodes": nodes,
        "members": None,
    }


def make_action(action_type="modify", new=None, old=None):
    return {"type": action_type, "new": new or make_element(), "old": old}
