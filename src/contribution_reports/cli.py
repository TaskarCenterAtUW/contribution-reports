"""CLI entry point that handles argument parsing, cache management, and mode
dispatch.
"""

import json
import sys
from pathlib import Path

from .auth import get_token
from .env import load_env
from .events import _compute_event_window, fetch_notes
from .fetch import fetch_all_data, fetch_way_midpoint
from .osc import _extract_all_quest_elements
from .quests import build_quest_index
from . import discover
from . import paths
from . import runtime
from .cache_runs import run_hotspots_from_cache, run_infer_from_cache
from .cli_args import parse_args
from .cli_util import _load_cache, parse_date, resolve_app_filter
from .offline import load_offline_archive
from .render import _ws_event_date, render_report
from .workspace_api import fetch_workspace_info, fetch_quest_definition


def main():
    args = parse_args()
    runtime.set_debug(args.debug)
    env = load_env(Path(args.env_file) if args.env_file else None)

    output_dir = paths.default_output_dir()
    cache_file = (
        Path(args.cache_file) if args.cache_file else output_dir / "changesets_raw.json"
    )
    out_file = Path(args.output) if args.output else output_dir / "report.html"

    # We need to reject directories early because both targets must be files.
    # If we let a directory pass, the program fails mid-run with an
    # IsADirectoryError traceback.
    if cache_file.is_dir():
        print(f"ERROR: {cache_file}: cache path is a directory", file=sys.stderr)
        sys.exit(1)
    if out_file.is_dir():
        print(f"ERROR: {out_file}: output path cannot be a directory", file=sys.stderr)
        sys.exit(1)

    app_filter = resolve_app_filter(args, env)

    if args.discover:
        if args.offline:
            print(
                "ERROR: --discover and --offline cannot be used together", file=sys.stderr
            )
            sys.exit(1)
        if args.cached:
            discover.render_cached_discovered(output_dir, app_filter=app_filter)
            return
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    osm_url = env.get("WS_OSM_URL", "")
    api_url = env.get("WS_NEW_API_URL", "")

    # We make no HTTP calls when we use `--cached` or `--offline`, so these
    # flags require no `WS_*` URLs.
    if not args.offline and not args.cached:
        if not osm_url:
            print("ERROR: WS_OSM_URL is not set in .env", file=sys.stderr)
            sys.exit(1)
        if not api_url:
            print("ERROR: WS_NEW_API_URL is not set in .env", file=sys.stderr)
            sys.exit(1)

    if args.discover:
        token = get_token(env)
        if not token:
            print("ERROR: failed to obtain auth token", file=sys.stderr)
            sys.exit(1)
        data = discover.run_discover(
            args, osm_url, api_url, token, app_filter=app_filter
        )
        if data:
            discover.write_discovered_reports(data, output_dir, app_filter=app_filter)
        return

    try:
        report_date = parse_date(args.date)
    except ValueError:
        print(
            f"ERROR: invalid --date {args.date!r}; use YYYY-MM-DD", file=sys.stderr
        )
        sys.exit(1)

    if args.infer_issues and cache_file.exists():
        data = run_infer_from_cache(args, env, cache_file, app_filter)
    elif args.hotspots and cache_file.exists():
        data = run_hotspots_from_cache(args, cache_file, app_filter)
    elif args.refresh_geoms and cache_file.exists():
        print(f"Refreshing way geometry for quest elements in {cache_file}...")
        token = get_token(env)
        data = _load_cache(cache_file, args.date)
        for ws_id_str, ws_data in data["workspaces"].items():
            ws_id = int(ws_id_str)
            quest_index = build_quest_index(ws_data.get("quest_definition"))
            updated = 0
            for cs in ws_data.get("changesets", []):
                osc_xml = cs.get("osc_xml") or ""
                all_elems = _extract_all_quest_elements(osc_xml, quest_index)
                existing = cs.get("all_elem_geoms") or {}
                new_geoms: dict = {}
                for e_type, e_id, e_pos, _ in all_elems:
                    if e_type == "way" and e_pos is None and e_id not in existing:
                        midpoint, geom = fetch_way_midpoint(osm_url, ws_id, e_id)
                        if midpoint:
                            new_geoms[e_id] = {
                                "lat": midpoint[0],
                                "lon": midpoint[1],
                                "geom": geom,
                            }
                if new_geoms:
                    existing.update(new_geoms)
                    cs["all_elem_geoms"] = existing
                    updated += len(new_geoms)
            print(f"  Workspace {ws_id_str}: fetched geometry for {updated} "
                      "new way(s)")
        cache_file.write_text(json.dumps(data, indent=2, default=str))
        print(f"Cache updated at {cache_file}")

    elif args.refresh_notes and cache_file.exists():
        print(f"Refreshing note counts from {cache_file}...")
        token = get_token(env)
        data = _load_cache(cache_file, args.date)
        for ws_id_str, ws_data in data["workspaces"].items():
            ws_id = int(ws_id_str)
            event_date = _ws_event_date(ws_data, data.get("date", ""))
            print(f"  Workspace {ws_id}: fetching notes for {event_date}")
            win_start, win_end = _compute_event_window(ws_data.get("changesets", []))
            notes = fetch_notes(
                osm_url, ws_id, token, window_start=win_start, window_end=win_end
            )
            ws_data["notes"] = notes
            ws_data.pop("notes_count", None)
            print(f"    {len(notes)} notes")
        cache_file.write_text(json.dumps(data, indent=2, default=str))
        print(f"Cache updated at {cache_file}")

    elif args.cached and cache_file.exists():
        print(f"Loading cached data from {cache_file}")
        data = _load_cache(cache_file, args.date)
    elif args.refresh_meta and cache_file.exists():
        print("Loading cached changesets and refreshing titles and quest "
                  "definitions...")
        data = _load_cache(cache_file, args.date)
        token = get_token(env)
        for ws_id_str, ws_data in data["workspaces"].items():
            ws_id = int(ws_id_str)
            print(f"\nWorkspace {ws_id}:")
            ws_info = fetch_workspace_info(ws_id, api_url, token)
            print(f"  Title: {ws_info['title']}")
            quest_def = fetch_quest_definition(ws_id, api_url, token)
            print("  Quest definition: "
                      f"{'loaded' if quest_def else 'not available'}")
            ws_data.update({**ws_info, "quest_definition": quest_def})
        cache_file.write_text(json.dumps(data, indent=2, default=str))
        print(f"\nCache updated at {cache_file}")
    elif args.offline:
        print(f"Loading offline archive: {args.offline}")
        try:
            data = load_offline_archive(args.offline, args.quest_file)
        except FileNotFoundError as exc:
            print(
                f"ERROR: {exc.filename or args.offline} does not exist",
                file=sys.stderr,
            )
            sys.exit(1)
        except OSError as exc:
            print(
                f"ERROR: {exc.filename or args.offline}: "
                    f"{exc.strerror or exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        except ValueError as exc:
            # Errors from `offline._read_archive` that concern archive shape
            # already include the path, so we print the message without changes
            # to prevent duplication.
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            cache_payload = json.dumps(data, indent=2, default=str)
            cache_file.write_text(cache_payload)
        except Exception as exc:
            # We need to supplement the depth cap in `offline._loads` so that
            # any failure during cache serialization results only in one ERROR
            # line instead of a full traceback. We're limiting this scope to
            # the cache dump and not other `json.dumps` calls.
            print(
                f"ERROR: {cache_file}: failed to cache: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Data cached to {cache_file}")
    else:
        ws_ids = args.workspace_ids
        if not ws_ids:
            print(
                "ERROR: Pass workspace IDs as arguments, e.g.: "
                    "contribution-report 1977 1978 1979",
                file=sys.stderr,
            )
            sys.exit(1)
        token = get_token(env)
        if args.all_dates:
            print(f"Fetching all changesets for workspaces {ws_ids} across "
                      "all dates...")
            data = fetch_all_data(ws_ids, None, osm_url, api_url, token)
        else:
            print(
                f"Fetching data for workspaces {ws_ids} on {report_date} ("
                    f"{args.tz or 'UTC'})..."
            )
            data = fetch_all_data(ws_ids, report_date, osm_url, api_url, token, args.tz)
        cache_file.write_text(json.dumps(data, indent=2, default=str))
        print(f"\nData cached to {cache_file}")

    try:
        render_report(
            data,
            out_file,
            show_positive=not args.no_positive,
            apply_window=args.auto_detect_event_window,
            report_title=args.report_title,
            workspace_title=args.workspace_title,
            app_filter=app_filter,
        )
    except Exception as exc:
        # We need this final guard on the rendering side because a crash can
        # occur after load validation. For instance, a poison string might
        # exist in a field that loaders deliberately leave unguarded. In this
        # case, we must produce exactly one ERROR line and prevent partial
        # reports from staying on disk.
        #
        # Because `SystemExit` is a subclass of `BaseException`, intentional
        # exits inside `render` remain untouched.
        out_file.unlink(missing_ok=True)
        print(f"ERROR: {out_file}: rendering failed: {exc}", file=sys.stderr)
        sys.exit(1)
