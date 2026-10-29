"""Implements `--discover` mode to locate workspaces by title, determine event
windows, and generate individual reports.

This module recreates the logic from the previous *fetch_nda.py* workflow,
though we now use `--title-match NDA` to specify NDAs instead of hardcoding
them. To prevent collisions with manually named caches, we store workspace
reports and caches in:

    <output>/discovered/
"""

import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .auth import auth_headers
from .events import fetch_notes, find_event_window
from .fetch import enrich_with_prev_tags
from .fetch import fetch_all_changesets as fetch_changesets_paginated
from .net import http_get_json
from .quests import build_quest_index
from .render import render_report
from .workspace_api import fetch_quest_definition, fetch_workspace_info


def slugify(title: str, ws_id: int) -> str:
    t = re.sub(r"[^a-zA-Z0-9]+", "_", title.strip()).strip("_").lower()
    return t or f"ws{ws_id}"


def title_matches(title: str, prefixes: tuple[str, ...]) -> bool:
    upper = title.upper()
    return any(upper.startswith(p.upper()) for p in prefixes)


def write_discovered_reports(
    data: dict, output_dir: Path, app_filter: tuple[str, ...] | None = None
) -> None:
    disc = output_dir / "discovered"
    disc.mkdir(parents=True, exist_ok=True)
    for ws_id_str, ws_data in data["workspaces"].items():
        slug = slugify(ws_data.get("title", ""), int(ws_id_str))
        single = {
            "date": ws_data.get("event_date") or data.get("date", ""),
            "workspaces": {ws_id_str: ws_data},
        }
        (disc / f"changesets_{slug}.json").write_text(
            json.dumps(single, indent=2, default=str)
        )
        render_report(single, disc / f"report_{slug}.html", app_filter=app_filter)
        print(f"  [{ws_id_str}] {slug} written to {slug}.json and {slug}.html")


def render_cached_discovered(
    output_dir: Path, app_filter: tuple[str, ...] | None = None
) -> None:
    disc = output_dir / "discovered"
    files = sorted(disc.glob("changesets_*.json"))
    if not files:
        print(f"No cached discovered-workspace files exist in {disc}")
        return
    for cache_path in files:
        slug = cache_path.stem.removeprefix("changesets_")
        data = json.loads(cache_path.read_text())
        render_report(data, disc / f"report_{slug}.html", app_filter=app_filter)
        print(f"  {slug} -> report_{slug}.html")


def fetch_all_changesets(osm_url: str, ws_id: int) -> list:
    """Retrieves all changesets from 2024-01-01 onward by requesting pages of 100
    items each.
    """
    since = datetime(2024, 1, 1, tzinfo=timezone.utc)
    until = datetime.now(timezone.utc)
    all_changesets = []

    while True:
        time_param = f"{since.strftime('%Y-%m-%dT%H:%M:%SZ')},{until.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        path = (
            f"api/0.6/changesets.json?time={urllib.parse.quote(time_param)}&limit=100"
        )
        url = osm_url.rstrip("/") + "/" + path
        req = urllib.request.Request(url)
        req.add_header("X-Workspace", str(ws_id))
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        page = data.get("changesets", [])
        all_changesets.extend(page)

        # OSM returns results in reverse-chronological order. When we receive a
        # full page, we need to traverse the changesets backwards through time.
        if len(page) < 100:
            break
        oldest = min((t for cs in page if (t := parse_cs_time(cs))), default=None)
        if oldest is None or oldest <= since:
            break
        until = oldest

    return all_changesets


def fetch_changesets_in_window(
    osm_url: str, ws_id: int, start: datetime, end: datetime
) -> list:
    """Retrieves changesets occurring between the start and end times while
    paginating results beyond 100 items.
    """
    return fetch_changesets_paginated(
        osm_url, ws_id, lower_bound=start, upper_bound=end
    )


def fetch_osc(osm_url: str, ws_id: int, cs_id: int) -> str | None:
    url = osm_url.rstrip("/") + f"/api/0.6/changeset/{cs_id}/download"
    req = urllib.request.Request(url)
    req.add_header("X-Workspace", str(ws_id))
    req.add_header("Accept", "application/xml")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"    WARNING: Could not fetch OSC for {cs_id}: {e}")
        return None


def parse_cs_time(cs: dict) -> datetime | None:
    t_str = cs.get("created_at") or cs.get("closed_at", "")
    if not t_str:
        return None
    try:
        return datetime.fromisoformat(t_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def run_discover(
    args,
    osm_url: str,
    api_url: str,
    token: str,
    app_filter: tuple[str, ...] | None = None,
) -> dict | None:
    """Locates workspaces, identifies event windows for each, and gathers report
    information.

    We return a cache-style data dictionary containing the results, though we
    return None if the `args.dry_run` flag is set or if no workspaces yield an
    event window. This function does not perform any disk writes.
    """
    if args.workspace_ids:
        print(
            f"Fetching info for {len(args.workspace_ids)} workspace ID(s)..."
        )
        workspaces = [
            fetch_workspace_info(wid, api_url, token) for wid in args.workspace_ids
        ]
        print(f"Using {len(workspaces)} workspace(s):")
    else:
        prefixes = tuple(args.title_match or ())
        if not prefixes:
            print(
                "ERROR: --discover needs --title-match PREFIX (repeatable) "
                    "or workspace IDs",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Fetching {len(prefixes)}-match workspaces...")
        mine = http_get_json(
            f"{api_url.rstrip('/')}/workspaces/mine", auth_headers(token)
        )
        listed = mine if isinstance(mine, list) else []
        workspaces = [w for w in listed if title_matches(w.get("title", ""), prefixes)]
        if not workspaces:
            print("No workspaces match the given prefix(es)")
            sys.exit(0)
        print(f"Found {len(workspaces)} matching workspace(s):")
    for w in workspaces:
        print(f"  [{w['id']}] {w['title']}")

    data: dict = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "workspaces": {},
    }
    earliest_event_date = None

    for ws in workspaces:
        ws_id = ws["id"]
        ws_title = ws.get("title", f"Workspace {ws_id}")
        print(f"\nWorkspace {ws_id} — {ws_title}:")

        print("  Scanning changesets for event window...")
        all_cs = fetch_all_changesets(osm_url, ws_id)
        print(f"  Total changesets found: {len(all_cs)}")

        event_window = find_event_window(all_cs, app_filter)
        if not event_window:
            print(
                "  WARNING: No app changeset clump found, so the event "
                    "window cannot be identified - skipping"
            )
            continue

        win_start, win_end = event_window
        event_date = win_start.date()
        print(
            f"  Event window: {win_start.strftime('%Y-%m-%d %H:%M')}--"
                f"{win_end.strftime('%H:%M')} UTC"
        )
        print(f"  Event date:   {event_date}")

        if args.dry_run:
            continue

        quest_def = fetch_quest_definition(ws_id, api_url, token)
        print("  Quest definition: "
                  f"{'loaded' if quest_def else 'not available'}")
        quest_index = build_quest_index(quest_def)

        event_cs = fetch_changesets_in_window(osm_url, ws_id, win_start, win_end)
        print(f"  Event changesets: {len(event_cs)}")

        enriched = []
        for cs in event_cs:
            if not str(cs["id"]).isdigit():
                print(
                    f"    WARNING: skipping changeset because {cs['id']!r} "
                        "is not numeric"
                )
                continue
            entry = dict(cs)
            print(f"    OSC {cs['id']}...")
            entry["osc_xml"] = fetch_osc(osm_url, ws_id, cs["id"])
            enrich_with_prev_tags(entry, osm_url, ws_id, quest_index)
            enriched.append(entry)

        print("  Fetching notes...")
        notes = fetch_notes(
            osm_url, ws_id, token, window_start=win_start, window_end=win_end
        )
        print(f"  Notes: {len(notes)}")

        data["workspaces"][str(ws_id)] = {
            "id": ws_id,
            "title": ws_title,
            "type": ws.get("type", "osw"),
            "event_date": event_date.isoformat(),
            "quest_definition": quest_def,
            "changesets": enriched,
            "notes": notes,
        }

        if earliest_event_date is None or event_date < earliest_event_date:
            earliest_event_date = event_date

    if args.dry_run:
        return None

    if not data["workspaces"]:
        print("\nNo event windows found — nothing to report.")
        return None

    data["date"] = earliest_event_date.isoformat()

    return data
