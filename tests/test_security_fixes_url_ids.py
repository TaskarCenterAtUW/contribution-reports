"""Security regression tests for slug validation, numeric ID verification, and zip
member limits.

We verify that `offline.load_offline_archive` rejects zip members exceeding the
MiB limit via `offline._MAX_MEMBER_BYTES`.

We check that non-numeric IDs are skipped or rejected before they reach URL
paths in these flows:
- `discover.run_discover` skips invalid changeset IDs.
- `fetch.fetch_all_data` skips invalid changeset IDs.
- `fetch.fetch_prev_tags` rejects non-numeric element IDs.
- `fetch.fetch_way_midpoint` rejects non-numeric IDs.
- `contribution_reports.osw.cli.fetch_workspace` skips invalid changeset IDs
  when calling `osw_cli.adiff.fetch_adiff`.

Finally, we ensure `contribution_reports.summary.load_event` rejects slug paths
that attempt to escape the cache directory through traversal.
"""

import json
import zipfile
from datetime import date, datetime, timezone
from types import SimpleNamespace
from urllib import request as urlrequest

import pytest

from contribution_reports import discover, fetch, offline


# We cap the expansion of zip members.


def test_rejects_zip_member_that_exceeds_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(offline, "_MAX_MEMBER_BYTES", 4)
    zip_path = tmp_path / "a.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {"workspace": {"id": 1, "title": "T", "type": "osw"}, "changesets": []}
            ),
        )
        zf.writestr("changesets/1.json", json.dumps({"create": [{"id": 1}]}))
    with pytest.raises(ValueError) as excinfo:
        offline.load_offline_archive(zip_path)
    message = str(excinfo.value)
    assert "changesets/1.json" in message
    assert "surpasses" in message and "MiB threshold" in message


def test_default_member_byte_limit_is_128_mib():
    assert offline._MAX_MEMBER_BYTES == 128 * 1024 * 1024


# We validate that IDs are numeric before we interpolate them into URL paths.


@pytest.fixture
def no_network(monkeypatch):
    calls = []

    def fake_urlopen(req, *args, **kwargs):
        calls.append(req.full_url if hasattr(req, "full_url") else req)
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(urlrequest, "urlopen", fake_urlopen)
    return calls


def test_discover_loop_skips_non_numeric_changeset_id(monkeypatch, capsys):
    fetched = []
    monkeypatch.setattr(
        discover,
        "fetch_workspace_info",
        lambda wid, api, tok: {"id": wid, "title": "T", "type": "osw"},
    )
    monkeypatch.setattr(discover, "fetch_all_changesets", lambda osm, ws: [{"id": 5}])
    monkeypatch.setattr(
        discover,
        "find_event_window",
        lambda cs, af=None: (
            datetime(2026, 6, 1, tzinfo=timezone.utc),
            datetime(2026, 6, 1, 2, tzinfo=timezone.utc),
        ),
    )
    monkeypatch.setattr(discover, "fetch_quest_definition", lambda ws, api, tok: None)
    monkeypatch.setattr(
        discover,
        "fetch_changesets_in_window",
        lambda osm, ws, s, e: [
            {"id": "bad/../evil", "tags": {}},
            {"id": 5, "tags": {}},
        ],
    )
    monkeypatch.setattr(
        discover, "fetch_osc", lambda osm, ws, cs_id: fetched.append(cs_id) or None
    )
    monkeypatch.setattr(discover, "enrich_with_prev_tags", lambda *a, **k: None)
    monkeypatch.setattr(discover, "fetch_notes", lambda *a, **k: [])
    args = SimpleNamespace(workspace_ids=[1], dry_run=False, title_match=[])

    data = discover.run_discover(args, "http://osm.test", "http://api.test", None)

    assert fetched == [5]
    ids = [cs["id"] for cs in data["workspaces"]["1"]["changesets"]]
    assert ids == [5]
    assert "WARNING" in capsys.readouterr().out


def test_fetch_all_data_skips_non_numeric_changeset_ids(monkeypatch, capsys):
    fetched = []
    monkeypatch.setattr(
        fetch,
        "fetch_workspace_info",
        lambda wid, api, tok: {"id": wid, "title": "T", "type": "osw"},
    )
    monkeypatch.setattr(fetch, "fetch_quest_definition", lambda ws, api, tok: None)
    monkeypatch.setattr(
        fetch,
        "fetch_changesets_for_date",
        lambda osm, ws, d, tok=None, tz=None: [
            {"id": "x y", "tags": {}},
            {"id": 5, "tags": {}},
        ],
    )
    monkeypatch.setattr(
        fetch,
        "fetch_osc",
        lambda osm, ws, cs_id, tok=None: fetched.append(cs_id) or "<osmChange/>",
    )
    monkeypatch.setattr(fetch, "enrich_with_prev_tags", lambda *a, **k: None)
    monkeypatch.setattr(fetch, "_compute_event_window", lambda cs: (None, None))
    monkeypatch.setattr(fetch, "fetch_notes", lambda *a, **k: [])

    data = fetch.fetch_all_data(
        [1], date(2026, 6, 1), "http://osm.test", "http://api.test", None
    )

    assert fetched == [5]
    ids = [cs["id"] for cs in data["workspaces"]["1"]["changesets"]]
    assert ids == [5]
    assert "WARNING" in capsys.readouterr().out


def test_fetch_prev_tags_refuses_non_numeric_element_id(no_network, capsys):
    assert fetch.fetch_prev_tags("http://osm.test", 1, "way", "-/../x", 2) is None
    assert no_network == []
    assert "WARNING" in capsys.readouterr().out


def test_fetch_way_midpoint_rejects_non_numeric_id(no_network, capsys):
    assert fetch.fetch_way_midpoint("http://osm.test", 1, "not a number") == (None, [])
    assert no_network == []
    assert "WARNING" in capsys.readouterr().out


def test_osw_cli_skips_non_numeric_changeset_ids(monkeypatch, capsys):
    from contribution_reports.osw import cli as osw_cli

    monkeypatch.setattr(
        osw_cli,
        "fetch_workspace_info",
        lambda ws, api, tok: {"id": ws, "title": "T", "type": "osw"},
    )
    monkeypatch.setattr(
        osw_cli.adiff,
        "fetch_changeset_list",
        lambda osm, ws, tok: [
            {
                "id": "1;evil",
                "changes_count": 1,
                "created_at": "2026-06-01T00:00:00Z",
                "tags": {},
            },
            {
                "id": 64,
                "changes_count": 1,
                "created_at": "2026-06-02T00:00:00Z",
                "tags": {},
            },
        ],
    )
    fetched = []
    monkeypatch.setattr(
        osw_cli.adiff,
        "fetch_adiff",
        lambda api, ws, cs_id, tok: fetched.append(cs_id) or [],
    )

    result = osw_cli.fetch_workspace(1280, "http://osm", "http://api", None)

    assert fetched == [64]
    assert result["adiffs"] == {"64": []}
    assert result["adiff_failures"] == {}
    assert "WARNING" in capsys.readouterr().err


# We need to prevent slug paths from escaping the cache directory.


def test_traversal_slug_raises_value_error(tmp_path):
    from contribution_reports.summary import load_event

    with pytest.raises(ValueError):
        load_event(
            {"slug": "../../etc/passwd", "title": "T", "use_window": False}, tmp_path
        )


def test_valid_slug_shows_missing_cache_warning(tmp_path, capsys):
    from contribution_reports.summary import load_event

    assert (
        load_event({"slug": "good_slug", "title": "T", "use_window": False}, tmp_path)
        is None
    )
    assert "changesets_good_slug.json does not exist" in capsys.readouterr().err
