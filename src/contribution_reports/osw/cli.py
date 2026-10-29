"""Command line interface that generates change reports for OpenSidewalks
workspaces.
"""

import argparse
import sys
from pathlib import Path

from .. import paths
from .. import runtime
from ..auth import get_token
from ..env import load_env
from ..workspace_api import fetch_workspace_info
from . import adiff
from .extract import elements_to_final, extract_path, fetch_map_extract
from .render import render_report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate an OpenSidewalks workspace change report")
    parser.add_argument("workspace_ids", nargs="*", type=int,
                        help="Workspace IDs to include")
    parser.add_argument("--cached", action="store_true",
                        help="Render from cache without contacting any API")
    parser.add_argument("--force", action="store_true",
                        help="Clear all cached adiffs to trigger a full "
                                 "re-fetch (default: reuse cached adiffs, "
                                 "which are immutable, and fetch only "
                                 "missing or previously-failed ones)")
    parser.add_argument("--include-baseline", action="store_true",
                        help="Add the TDEI import changeset to the edit "
                                 "ledger")
    parser.add_argument("--full-extract", action="store_true",
                        help="Download every raw element within the edited "
                             "extent (the bbox spanning the reported "
                             "changesets — NOT the whole workspace) so "
                             "completeness is measured over that wider "
                             "population instead of touched-elements-only")
    parser.add_argument("--cache-file", type=Path, default=None,
                        help="Path to the cache file (default: "
                                 "output/osw_report.json.gz)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Path to the output HTML file (default: "
                                 "output/osw_report.html)")
    parser.add_argument("--report-title", default=None,
                        help="Set the report <h1> and <title>")
    parser.add_argument("--env-file", type=Path, default=None,
                        help="Path to .env file (default: WS_ENV_FILE env var, else nearest .env walking up from CWD; absence is tolerated when not fetching live data)")
    parser.add_argument("--debug", action="store_true",
                        help="Print each HTTP request URL and headers")
    return parser.parse_args(argv)


def _bbox(changesets: list):
    lats = [float(cs[k]) for cs in changesets for k in ("min_lat", "max_lat")
            if cs.get(k) is not None]
    lons = [float(cs[k]) for cs in changesets for k in ("min_lon", "max_lon")
            if cs.get(k) is not None]
    if not lats or not lons:
        return None
    return [min(lons), min(lats), max(lons), max(lats)]


def fetch_workspace(ws_id: int, osm_url: str, api_url: str, token: str | None,
                    existing: dict | None = None, force: bool = False) -> dict:
    """Retrieves changesets and adiffs for a workspace while utilizing cached
    adiff data.

    Because closed changeset adiffs remain immutable, we avoid re-fetching
    cached entries unless we set `force`. If a changeset fails to retrieve, we
    record it in `adiff_failures` for the report instead of treating it as
    zero.
    """
    print(f"\nWorkspace {ws_id}:")
    info = fetch_workspace_info(ws_id, api_url, token)
    print(f"  Title: {info['title']}")

    changesets = adiff.fetch_changeset_list(osm_url, ws_id, token)
    print(f"  Changesets: {len(changesets)}")

    cached_adiffs = {} if force else dict((existing or {}).get("adiffs", {}))
    failures: dict = {}

    for i, cs in enumerate(changesets, 1):
        cs_id = str(cs["id"])
        if not cs_id.isdigit():
            print(f"  WARNING: skipping changeset with non-numeric id: {cs['id']!r}",
                  file=sys.stderr)
            continue
        if cs_id in cached_adiffs:
            continue
        try:
            cached_adiffs[cs_id] = adiff.fetch_adiff(api_url, ws_id, cs["id"], token)
            print(f"  [{i}/{len(changesets)}] adiff {cs_id}: "
                      f"{len(cached_adiffs[cs_id])} actions")
        except adiff.AdiffFetchError as e:
            print(f"  [{i}/{len(changesets)}] adiff {cs_id}: failed - {e}",
                  file=sys.stderr)
            failures[cs_id] = str(e)

    return {**info, "bbox": _bbox(changesets), "changesets": changesets,
            "adiffs": cached_adiffs, "adiff_failures": failures}


def main(argv=None) -> None:
    args = parse_args(argv)
    runtime.set_debug(args.debug)
    env = load_env(args.env_file)

    cache_file = args.cache_file if args.cache_file else paths.default_output_dir() / "osw_report.json.gz"
    out_file = args.output if args.output else paths.default_output_dir() / "osw_report.html"

    if args.cached:
        if not cache_file.exists():
            print(f"ERROR: {cache_file} does not exist", file=sys.stderr)
            sys.exit(1)
        print(f"Loading cached data from {cache_file}")
        data = adiff.load_cache(cache_file)
    else:
        if not args.workspace_ids:
            print("ERROR: workspace IDs are required, e.g. osw-report 1280 "
                      "...", file=sys.stderr)
            sys.exit(1)

        osm_url = env.get("WS_OSM_URL", "")
        api_url = env.get("WS_NEW_API_URL", "")
        if not osm_url or not api_url:
            print("ERROR: WS_OSM_URL and WS_NEW_API_URL are both required",
                  file=sys.stderr)
            sys.exit(1)

        # We reuse the cache unconditionally because adiffs for closed
        # changesets never change. By loading the existing cache and passing it
        # to `fetch_workspace()`, we only need to fetch gaps--including missing
        # or previously-failed changesets--instead of performing full refreshes
        # on every run.
        existing = (adiff.load_cache(cache_file)
                    if cache_file.exists() else {"workspaces": {}})
        token = get_token(env)
        data = {"workspaces": {}}
        for ws_id in args.workspace_ids:
            prior = existing.get("workspaces", {}).get(str(ws_id))
            data["workspaces"][str(ws_id)] = fetch_workspace(
                ws_id, osm_url, api_url, token, existing=prior, force=args.force)
        adiff.save_cache(data, cache_file)
        if args.full_extract:
            # We use one sibling file per run, which we key by workspace ID to
            # prevent elements from different workspaces from overwriting or
            # being mistaken for each other during multi-workspace runs.
            extract_data = {"workspaces": {}}
            for ws_id_str, ws_data in data["workspaces"].items():
                try:
                    elements = fetch_map_extract(osm_url, int(ws_id_str),
                                                 ws_data.get("bbox"), token)
                except adiff.AdiffFetchError as e:
                    # We'll need to prevent fetch failures--such as a bounding
                    # box that exceeds size limits--from halting the run.
                    # Because we already saved the main cache, this workspace's
                    # report remains useful without a full extract. The process
                    # falls back to touched-element scope for this workspace
                    # and continues.
                    print(f"  WARNING: full extract for workspace {ws_id_str}"
                              f" failed ({e}), so the report falls back to "
                              "touched-element scope.",
                          file=sys.stderr)
                    continue
                if elements:
                    extract_data["workspaces"][ws_id_str] = {"elements": elements}
            if extract_data["workspaces"]:
                adiff.save_cache(extract_data, extract_path(cache_file))
        print(f"\nData cached to {cache_file}")

    extract_file = extract_path(cache_file)
    extracts = {}
    if args.full_extract and extract_file.exists():
        extract_cache = adiff.load_cache(extract_file)
        extracts = {
            ws_id_str: elements_to_final(ws_extract["elements"])
            for ws_id_str, ws_extract in extract_cache.get("workspaces", {}).items()
        }

    render_report(data, out_file, include_baseline=args.include_baseline,
                  report_title=args.report_title, extracts=extracts)
