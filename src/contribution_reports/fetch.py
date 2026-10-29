"""Fetches live data including full workspace information, element geometry, OSC
XML, and changesets.
"""

import json
import math
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import runtime
from .events import _compute_event_window, fetch_notes
from .net import osm_get_json, osm_get_xml
from .osc import _extract_all_quest_elements, _extract_quest_element_info
from .quests import build_quest_index
from .workspace_api import fetch_workspace_info, fetch_quest_definition


def day_bounds(report_date: date, tz: str | None = None) -> tuple[datetime, datetime]:
    """Calculates the [start, end) UTC instants for a given report_date within a
    specified time zone.

    If we don't provide a zone, the function defaults to UTC.
    """
    zone = ZoneInfo(tz) if tz else timezone.utc
    start = datetime.combine(report_date, time.min, tzinfo=zone)
    end = datetime.combine(report_date + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def fetch_changesets_for_date(
    osm_url: str,
    ws_id: int,
    report_date: date,
    token: str | None = None,
    tz: str | None = None,
) -> list:
    """Retrieves changesets created on report_date within the specified timezone
    (defaulting to UTC).

    Because the OSM API's `time=T1,T2` includes changesets closed after T1 but
    created before T2, we might see items opened on the previous day. We filter
    these results by `created_at` so we only keep changesets opened during the
    target day.
    """
    start, end = day_bounds(report_date, tz)
    changesets = fetch_all_changesets(
        osm_url, ws_id, token, lower_bound=start, upper_bound=end
    )
    return [
        cs
        for cs in changesets
        if start
        <= datetime.fromisoformat(cs["created_at"].replace("Z", "+00:00"))
        < end
    ]


def fetch_all_changesets(
    osm_url: str,
    ws_id: int,
    token: str | None = None,
    lower_bound: datetime | None = None,
    upper_bound: datetime | None = None,
) -> list:
    """Retrieves every changeset in a workspace by paginating on `created_at`.

    We page backward through time by passing the
    `time=<lower_bound>,<upper_bound>` parameter to the OSM API. Since
    boundaries may overlap, we deduplicate the results by changeset ID.
    """
    all_changesets: list = []
    seen_ids: set[int] = set()
    t_lower = lower_bound.strftime("%Y-%m-%dT%H:%M:%SZ") if lower_bound else ""

    while True:
        if upper_bound or lower_bound:
            t_upper = upper_bound.strftime("%Y-%m-%dT%H:%M:%SZ") if upper_bound else ""
            path = f"api/0.6/changesets.json?time={urllib.parse.quote(t_lower + ',' + t_upper)}&limit=100"
        else:
            path = "api/0.6/changesets.json?limit=100"
        print(f"  Fetching changesets ({len(all_changesets)} found so far)...")
        data = osm_get_json(osm_url, path, ws_id, token)
        batch = data.get("changesets", [])
        if not batch:
            break
        for cs in batch:
            if cs["id"] not in seen_ids:
                seen_ids.add(cs["id"])
                all_changesets.append(cs)
        if len(batch) < 100:
            break
        # We set `upper_bound` to a point immediately preceding the oldest
        # changeset we found on this page.
        oldest = min(
            datetime.fromisoformat(cs["created_at"].replace("Z", "+00:00"))
            for cs in batch
        )
        if upper_bound is not None and oldest >= upper_bound:
            break  # we guard against infinite loops if no progress occurs--unlikely
        upper_bound = oldest

    return all_changesets


def fetch_osc(osm_url: str, ws_id: int, cs_id: int, token: str | None = None) -> str:
    print(f"    OSC {cs_id}...")
    return osm_get_xml(osm_url, f"api/0.6/changeset/{cs_id}/download", ws_id, token)


def fetch_prev_tags(
    osm_url: str,
    ws_id: int,
    elem_type: str,
    elem_id: str,
    version: int,
    token: str | None = None,
) -> dict | None:
    """Retrieves tags associated with an element's preceding version.

    If the version is 1, we return {} because no earlier version exists and all
    tags count as new.

    We return None if a fetch error occurs, which lets the caller fall back to
    the quest_index heuristic.
    """
    if version <= 1:
        return {}
    if not str(elem_id).isdigit():
        print(f"    WARNING: skipping non-numeric element ID: {elem_id!r}")
        return None
    url = f"{osm_url.rstrip('/')}/api/0.6/{elem_type}/{elem_id}/{version - 1}.json"
    req = urllib.request.Request(url)
    req.add_header("X-Workspace", str(ws_id))
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    runtime._dbg(req)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        elements = data.get("elements", [])
        return elements[0].get("tags", {}) if elements else None
    except Exception as e:
        print(f"    WARNING: Failed to fetch {elem_type}/{elem_id} v{version - 1}: {e}")
        return None


def _polyline_midpoint(positions: list[tuple[float, float]]) -> tuple[float, float]:
    """Calculates the point at half the total arc length of a polyline.

    We interpolate between the two nodes surrounding that halfway mark, which
    means the output need not match any existing node position. Only when all
    nodes are coincident do we fall back to the index-midpoint node.
    """
    if len(positions) == 1:
        return positions[0]

    def seg_len(a, b):
        # We use an equirectangular approximation here because it provides
        # sufficient accuracy for ways shorter than 1 km.
        dlat = math.radians(b[0] - a[0])
        dlon = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
        return math.sqrt(dlat * dlat + dlon * dlon)

    segments = [
        seg_len(positions[i], positions[i + 1]) for i in range(len(positions) - 1)
    ]
    total = sum(segments)
    if total == 0:
        return positions[len(positions) // 2]

    half = total / 2
    dist = 0.0
    for i, seg in enumerate(segments):
        if dist + seg >= half:
            t = (half - dist) / seg if seg > 0 else 0.0
            lat = positions[i][0] + t * (positions[i + 1][0] - positions[i][0])
            lon = positions[i][1] + t * (positions[i + 1][1] - positions[i][1])
            return lat, lon
        dist += seg
    return positions[-1]


def fetch_way_midpoint(
    osm_url: str, ws_id: int, way_id: str, token: str | None = None
) -> tuple[tuple[float, float] | None, list[list[float]]]:
    """Retrieves the full geometry for a way using `/way/{id}/full`.

    We get a tuple containing the true arc-length midpoint (which we
    interpolate between nodes) and the geometry as a list of
    `[[lat, lon], ...]` following node order.

    If the `way_id` lacks only digits or an error occurs, we return
    `(None, [])`.
    """
    if not str(way_id).isdigit():
        print(f"    WARNING: skipping non-numeric way ID: {way_id!r}")
        return None, []
    url = f"{osm_url.rstrip('/')}/api/0.6/way/{way_id}/full.json"
    req = urllib.request.Request(url)
    req.add_header("X-Workspace", str(ws_id))
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    runtime._dbg(req)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        elements = data.get("elements", [])
        nodes = {
            e["id"]: (e["lat"], e["lon"])
            for e in elements
            if e.get("type") == "node" and "lat" in e
        }
        way = next((e for e in elements if e.get("type") == "way"), None)
        if not way:
            return None, []
        positions = [nodes[nid] for nid in way.get("nodes", []) if nid in nodes]
        if not positions:
            return None, []
        lat, lon = _polyline_midpoint(positions)
        geom = [[round(p[0], 6), round(p[1], 6)] for p in positions]
        return (round(lat, 6), round(lon, 6)), geom
    except Exception as e:
        print(f"    WARNING: Could not fetch geometry for way {way_id}: {e}")
        return None, []


def enrich_with_prev_tags(
    entry: dict, osm_url: str, ws_id: int, quest_index: dict, token: str | None = None
) -> None:
    """Updates a changeset entry in-place with `elem_type`, `elem_id`,
    `elem_version`, and `prev_tags`.

    We call this after we store `osc_xml` because the data gets cached to disk.
    This lets us compute the true tag diff during rendering without another API
    call.
    """
    osc_xml = entry.get("osc_xml") or ""
    info = _extract_quest_element_info(osc_xml, quest_index)
    if not info:
        return
    etype, eid, eversion = info
    entry["elem_type"] = etype
    entry["elem_id"] = eid
    entry["elem_version"] = eversion
    entry["prev_tags"] = fetch_prev_tags(osm_url, ws_id, etype, eid, eversion, token)

    # We need geometry for all quest ways in the changeset instead of only the
    # first one. Because GIG changesets can affect multiple sidewalk ways, we
    # require individual midpoints to place markers at their actual locations
    # instead of the bounding box center.
    all_elems = _extract_all_quest_elements(osc_xml, quest_index)
    all_elem_geoms: dict[str, dict] = {}
    for e_type, e_id, e_pos, _ in all_elems:
        if not str(e_id).isdigit():
            print(f"    WARNING: skipping non-numeric element ID: {e_id!r}")
            continue
        if e_type == "way" and e_pos is None:
            midpoint, geom = fetch_way_midpoint(osm_url, ws_id, e_id, token)
            if midpoint:
                all_elem_geoms[e_id] = {
                    "lat": midpoint[0],
                    "lon": midpoint[1],
                    "geom": geom,
                }
    if all_elem_geoms:
        entry["all_elem_geoms"] = all_elem_geoms
        # We need to populate flat fields with data from the first element when
        # we encounter a way. This maintains compatibility with legacy
        # rendering code.
        if etype == "way" and eid in all_elem_geoms:
            entry["elem_lat"] = all_elem_geoms[eid]["lat"]
            entry["elem_lon"] = all_elem_geoms[eid]["lon"]
            entry["elem_geom"] = all_elem_geoms[eid]["geom"]


def fetch_all_data(
    ws_ids: list[int],
    report_date: date | None,
    osm_url: str,
    api_url: str,
    token: str | None,
    tz: str | None = None,
) -> dict:
    date_str = report_date.isoformat() if report_date else date.today().isoformat()
    data: dict = {"date": date_str, "workspaces": {}}
    if tz:
        data["tz"] = tz
    for ws_id in ws_ids:
        print(f"\nWorkspace {ws_id}:")
        ws_info = fetch_workspace_info(ws_id, api_url, token)
        print(f"  Title: {ws_info['title']}")
        quest_def = fetch_quest_definition(ws_id, api_url, token)
        print(f"  Quest definition: {'loaded' if quest_def else 'not available'}")
        quest_index = build_quest_index(quest_def)
        if report_date is None:
            changesets = fetch_all_changesets(osm_url, ws_id, token)
        else:
            changesets = fetch_changesets_for_date(
                osm_url, ws_id, report_date, token, tz
            )
        print(f"  Changesets: {len(changesets)}")
        enriched = []
        for cs in changesets:
            if not str(cs["id"]).isdigit():
                print(f"    WARNING: skipping non-numeric changeset ID: {cs['id']!r}")
                continue
            entry = dict(cs)
            try:
                entry["osc_xml"] = fetch_osc(osm_url, ws_id, cs["id"], token)
                enrich_with_prev_tags(entry, osm_url, ws_id, quest_index, token)
            except Exception as e:
                print(f"    WARNING: failed to fetch OSC for {cs['id']}: {e}")
                entry["osc_xml"] = None
            enriched.append(entry)
        print(f"  Fetching notes...")
        win_start, win_end = _compute_event_window(enriched)
        notes = fetch_notes(
            osm_url, ws_id, token, window_start=win_start, window_end=win_end
        )
        print(f"  Notes: {len(notes)}")

        data["workspaces"][str(ws_id)] = {
            **ws_info,
            "quest_definition": quest_def,
            "changesets": enriched,
            "notes": notes,
        }
    return data
