from pathlib import Path

import pytest

from contribution_reports.osw import cli


def test_parse_args_uses_defaults():
    args = cli.parse_args(["1280"])
    assert args.workspace_ids == [1280]
    assert args.include_baseline is False
    assert args.cached is False
    assert args.force is False


def test_parse_args_flags_and_booleans():
    args = cli.parse_args(["1280", "--include-baseline", "--force"])
    assert args.include_baseline is True
    assert args.force is True


def test_main_defaults_to_gzipped_cache_under_output_dir(monkeypatch, tmp_path):
    """Checks that runs lacking `--cache-file` place the cache in the `./output`
    directory relative to the CWD instead of beside the installed package.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "load_env",
        lambda p=None: {"WS_OSM_URL": "http://osm", "WS_NEW_API_URL": "http://api"},
    )
    monkeypatch.setattr(cli, "get_token", lambda env: None)
    monkeypatch.setattr(
        cli,
        "fetch_workspace",
        lambda ws_id, osm, api, tok, existing=None, force=False: {
            "id": ws_id,
            "bbox": None,
            "changesets": [],
            "adiffs": {},
            "adiff_failures": {},
        },
    )
    monkeypatch.setattr(cli, "render_report", lambda *a, **k: None)
    saved = []
    monkeypatch.setattr(
        cli.adiff, "save_cache", lambda data, path: saved.append(Path(path))
    )
    cli.main(["1280"])
    assert saved == [tmp_path / "output" / "osw_report.json.gz"]


def test_fetch_workspace_skips_adiffs_in_cache(monkeypatch):
    monkeypatch.setattr(
        cli,
        "fetch_workspace_info",
        lambda ws, api, tok: {"id": ws, "title": "T", "type": "osw"},
    )
    monkeypatch.setattr(
        cli.adiff,
        "fetch_changeset_list",
        lambda osm, ws, tok: [
            {
                "id": 63,
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

    def fake_adiff(api, ws, cs_id, tok):
        fetched.append(cs_id)
        return [{"type": "create"}]

    monkeypatch.setattr(cli.adiff, "fetch_adiff", fake_adiff)
    existing = {"adiffs": {"63": [{"type": "create"}]}, "adiff_failures": {}}
    result = cli.fetch_workspace(1280, "http://osm", "http://api", None, existing)
    assert fetched == [64]
    assert set(result["adiffs"]) == {"63", "64"}


def test_fetch_workspace_with_force_refetches_all_adiffs(monkeypatch):
    monkeypatch.setattr(
        cli,
        "fetch_workspace_info",
        lambda ws, api, tok: {"id": ws, "title": "T", "type": "osw"},
    )
    monkeypatch.setattr(
        cli.adiff,
        "fetch_changeset_list",
        lambda osm, ws, tok: [
            {
                "id": 63,
                "changes_count": 1,
                "created_at": "2026-06-01T00:00:00Z",
                "tags": {},
            }
        ],
    )
    fetched = []
    monkeypatch.setattr(
        cli.adiff,
        "fetch_adiff",
        lambda api, ws, cs_id, tok: fetched.append(cs_id) or [],
    )
    existing = {"adiffs": {"63": [{"type": "create"}]}, "adiff_failures": {}}
    cli.fetch_workspace(1280, "http://osm", "http://api", None, existing, force=True)
    assert fetched == [63]


def test_fetch_workspace_records_failures_instead_of_raising(monkeypatch):
    monkeypatch.setattr(
        cli,
        "fetch_workspace_info",
        lambda ws, api, tok: {"id": ws, "title": "T", "type": "osw"},
    )
    monkeypatch.setattr(
        cli.adiff,
        "fetch_changeset_list",
        lambda osm, ws, tok: [
            {
                "id": 63,
                "changes_count": 1,
                "created_at": "2026-06-01T00:00:00Z",
                "tags": {},
            }
        ],
    )

    def boom(api, ws, cs_id, tok):
        raise cli.adiff.AdiffFetchError("truncated")

    monkeypatch.setattr(cli.adiff, "fetch_adiff", boom)
    result = cli.fetch_workspace(1280, "http://osm", "http://api", None)
    assert "63" in result["adiff_failures"]
    assert result["adiffs"] == {}


def test_fetch_workspace_calculates_bounding_box(monkeypatch):
    monkeypatch.setattr(
        cli,
        "fetch_workspace_info",
        lambda ws, api, tok: {"id": ws, "title": "T", "type": "osw"},
    )
    monkeypatch.setattr(
        cli.adiff,
        "fetch_changeset_list",
        lambda osm, ws, tok: [
            {
                "id": 63,
                "changes_count": 0,
                "created_at": "2026-06-01T00:00:00Z",
                "tags": {},
                "min_lat": 46.1,
                "max_lat": 46.3,
                "min_lon": -119.4,
                "max_lon": -119.2,
            }
        ],
    )
    monkeypatch.setattr(cli.adiff, "fetch_adiff", lambda api, ws, cs_id, tok: [])
    result = cli.fetch_workspace(1280, "http://osm", "http://api", None)
    assert result["bbox"] == [-119.4, 46.1, -119.2, 46.3]


def test_main_needs_workspace_ids_when_uncached(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli,
        "load_env",
        lambda p=None: {"WS_OSM_URL": "http://osm", "WS_NEW_API_URL": "http://api"},
    )
    with pytest.raises(SystemExit):
        cli.main([])


def test_fetch_workspace_retries_failures_and_skips_successes(monkeypatch):
    """Checks that changesets in `adiff_failures` without corresponding entries in
    `adiffs` trigger retries, while those already present in `adiffs` skip
    re-fetching.

    We see this gap-filling occur whenever we omit `--force`. The operation
    runs unconditionally because no `--refresh-adiffs` flag gates it.
    """
    monkeypatch.setattr(
        cli,
        "fetch_workspace_info",
        lambda ws, api, tok: {"id": ws, "title": "T", "type": "osw"},
    )
    monkeypatch.setattr(
        cli.adiff,
        "fetch_changeset_list",
        lambda osm, ws, tok: [
            {
                "id": 63,
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

    def fake_adiff(api, ws, cs_id, tok):
        fetched.append(cs_id)
        return [{"type": "create"}]

    monkeypatch.setattr(cli.adiff, "fetch_adiff", fake_adiff)
    # We've cached success for 63, but 64 failed and lacks a cached adiff
    # entry.
    existing = {
        "adiffs": {"63": [{"type": "create"}]},
        "adiff_failures": {"64": "truncated"},
    }
    result = cli.fetch_workspace(1280, "http://osm", "http://api", None, existing)
    assert fetched == [64]
    assert set(result["adiffs"]) == {"63", "64"}
    assert result["adiff_failures"] == {}


def test_main_passes_loaded_cache_to_fetch_workspace(monkeypatch, tmp_path):
    """Checks that `main()` loads a present cache file and passes it as the
    `existing` argument to `fetch_workspace()` during a live-fetch
    (non-`--cached`) run to enable automatic retry and gap-filling.

    We test this specific path because it hosted the `--refresh-adiffs` bug.
    Since `main()` previously ignored the flag entirely, testing
    `fetch_workspace()` in isolation cannot detect a regression here.
    """
    cache_file = tmp_path / "cache.json.gz"
    cache_file.write_bytes(b"")  # only needs to exist; `load_cache` is stubbed

    monkeypatch.setattr(
        cli,
        "load_env",
        lambda p=None: {"WS_OSM_URL": "http://osm", "WS_NEW_API_URL": "http://api"},
    )
    monkeypatch.setattr(cli, "get_token", lambda env: None)

    prior_workspace = {"adiffs": {"63": [{"type": "create"}]}, "adiff_failures": {}}
    monkeypatch.setattr(
        cli.adiff, "load_cache", lambda path: {"workspaces": {"1280": prior_workspace}}
    )
    saved = []
    monkeypatch.setattr(cli.adiff, "save_cache", lambda data, path: saved.append(data))

    seen_existing = []

    def fake_fetch_workspace(ws_id, osm, api, tok, existing=None, force=False):
        seen_existing.append(existing)
        return {"id": ws_id, "adiffs": {}, "adiff_failures": {}}

    monkeypatch.setattr(cli, "fetch_workspace", fake_fetch_workspace)
    monkeypatch.setattr(cli, "render_report", lambda *a, **k: None)

    cli.main(["1280", "--cache-file", str(cache_file)])

    assert seen_existing == [prior_workspace]
    assert saved  # we verify `save_cache` received the newly fetched data


def test_full_extract_fetches_map_extract_and_saves_it_to_keyed_sibling_file(
    monkeypatch, tmp_path
):
    """Checks that `--full-extract` triggers a whole-workspace map extract fetch
    and writes the result to a sibling file via `extract_path`.

    We save this data under a `"workspaces"` object keyed by workspace ID to
    mirror the shape of the main cache. This keeps the extract separate so it
    never merges into the main cache itself. By keying the data this way, we
    prevent elements from one workspace from being overwritten by another
    during multi-workspace runs.
    """
    cache_file = tmp_path / "cache.json.gz"

    monkeypatch.setattr(
        cli,
        "load_env",
        lambda p=None: {"WS_OSM_URL": "http://osm", "WS_NEW_API_URL": "http://api"},
    )
    monkeypatch.setattr(cli, "get_token", lambda env: None)
    monkeypatch.setattr(
        cli,
        "fetch_workspace",
        lambda ws_id, osm, api, tok, existing=None, force=False: {
            "id": ws_id,
            "bbox": [-119.4, 46.1, -119.2, 46.3],
            "changesets": [],
            "adiffs": {},
            "adiff_failures": {},
        },
    )
    monkeypatch.setattr(cli, "render_report", lambda *a, **k: None)

    fetch_calls = []
    monkeypatch.setattr(
        cli,
        "fetch_map_extract",
        lambda osm, ws_id, bbox, tok: (
            fetch_calls.append((ws_id, bbox))
            or [{"type": "node", "id": 1, "version": 1, "tags": {}}]
        ),
    )

    saved = []
    monkeypatch.setattr(
        cli.adiff,
        "save_cache",
        lambda data, path: saved.append((dict(data), Path(path))),
    )

    cli.main(["1280", "--full-extract", "--cache-file", str(cache_file)])

    assert fetch_calls == [(1280, [-119.4, 46.1, -119.2, 46.3])]
    # We write to the main cache first, then save the extract to a sibling
    # path. The extract never shares a path with the main cache file.
    assert [p for _, p in saved] == [cache_file, cli.extract_path(cache_file)]
    extract_payload = saved[1][0]
    assert extract_payload == {
        "workspaces": {
            "1280": {"elements": [{"type": "node", "id": 1, "version": 1, "tags": {}}]}
        }
    }


def test_main_without_full_extract_skips_extract_fetch(monkeypatch, tmp_path):
    """Confirms that executing without `--full-extract` results in zero calls to
    `fetch_map_extract`.

    Because the default run remains touched-elements-only, we expect no
    extract-fetch operations.
    """
    cache_file = tmp_path / "cache.json.gz"

    monkeypatch.setattr(
        cli,
        "load_env",
        lambda p=None: {"WS_OSM_URL": "http://osm", "WS_NEW_API_URL": "http://api"},
    )
    monkeypatch.setattr(cli, "get_token", lambda env: None)
    monkeypatch.setattr(
        cli,
        "fetch_workspace",
        lambda ws_id, osm, api, tok, existing=None, force=False: {
            "id": ws_id,
            "bbox": None,
            "changesets": [],
            "adiffs": {},
            "adiff_failures": {},
        },
    )
    monkeypatch.setattr(cli, "render_report", lambda *a, **k: None)
    monkeypatch.setattr(cli.adiff, "save_cache", lambda data, path: None)

    def boom(*a, **k):
        raise AssertionError(
            "fetch_map_extract must not be called without --full-extract"
        )

    monkeypatch.setattr(cli, "fetch_map_extract", boom)

    cli.main(["1280", "--cache-file", str(cache_file)])  # no --full-extract


def test_main_full_extract_catches_adiff_fetch_error_and_calls_render_report(
    monkeypatch, tmp_path, capsys
):
    """Checks that `main()` handles an `AdiffFetchError` raised by
    `fetch_map_extract` when a `bbox` exceeds limits.

    If the main cache is already saved, we need to ensure this error does not
    abort the run. Instead, `main()` must catch the exception and print a
    warning, then call `render_report` so the workspace falls back to
    touched-element scope.
    """
    cache_file = tmp_path / "cache.json.gz"

    monkeypatch.setattr(
        cli,
        "load_env",
        lambda p=None: {"WS_OSM_URL": "http://osm", "WS_NEW_API_URL": "http://api"},
    )
    monkeypatch.setattr(cli, "get_token", lambda env: None)
    monkeypatch.setattr(
        cli,
        "fetch_workspace",
        lambda ws_id, osm, api, tok, existing=None, force=False: {
            "id": ws_id,
            "bbox": [-119.4, 46.1, -119.2, 46.3],
            "changesets": [],
            "adiffs": {},
            "adiff_failures": {},
        },
    )

    def boom(osm, ws_id, bbox, tok):
        raise cli.adiff.AdiffFetchError("bbox too large")

    monkeypatch.setattr(cli, "fetch_map_extract", boom)
    monkeypatch.setattr(cli.adiff, "save_cache", lambda data, path: None)

    rendered = []
    monkeypatch.setattr(cli, "render_report", lambda *a, **k: rendered.append(True))

    cli.main(["1280", "--full-extract", "--cache-file", str(cache_file)])

    assert rendered  # the run completes and renders despite the fetch error
    err = capsys.readouterr().err
    assert "1280" in err
    assert "falls back to touched-element scope" in err


def test_cached_full_extract_loads_existing_sibling_without_api_calls(
    monkeypatch, tmp_path
):
    """Checks that `--cached` and `--full-extract` load an existing sibling
    extract file to provide a per-workspace mapping to `render_report()`.

    Because `--cached` requires zero API calls, we need to ensure no HTTP fetch
    occurs.
    """
    cache_file = tmp_path / "cache.json.gz"
    cache_file.write_bytes(b"")  # needs to exist; `load_cache` is stubbed
    extract_file = cli.extract_path(cache_file)
    extract_file.write_bytes(b"")

    ws_data = {
        "id": 1280,
        "title": "T",
        "bbox": None,
        "changesets": [],
        "adiffs": {},
        "adiff_failures": {},
    }
    main_cache = {"workspaces": {"1280": ws_data}}
    extract_cache = {
        "workspaces": {
            "1280": {
                "elements": [
                    {"type": "node", "id": 1, "version": 1, "tags": {"barrier": "kerb"}}
                ]
            }
        }
    }

    def fake_load_cache(path):
        return extract_cache if Path(path) == extract_file else main_cache

    monkeypatch.setattr(cli, "load_env", lambda p=None: {})
    monkeypatch.setattr(cli.adiff, "load_cache", fake_load_cache)

    def boom(*a, **k):
        raise AssertionError("fetch_map_extract must not be called in --cached mode")

    monkeypatch.setattr(cli, "fetch_map_extract", boom)

    seen = {}
    monkeypatch.setattr(
        cli,
        "render_report",
        lambda data, out, include_baseline=False, report_title=None, extracts=None: (
            seen.update(data=data, extracts=extracts)
        ),
    )

    cli.main(["--cached", "--full-extract", "--cache-file", str(cache_file)])

    assert seen["data"] == main_cache
    assert seen["extracts"] == {
        "1280": {
            ("node", 1): {"tags": {"barrier": "kerb"}, "version": 1, "deleted": False}
        }
    }
