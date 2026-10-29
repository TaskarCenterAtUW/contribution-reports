"""Provides utilities for detecting event windows, fetching notes, and parsing
changeset timestamps.
"""

import json
import urllib.request
from datetime import datetime, timedelta, timezone

from . import runtime
from .constants import APP_CREATED_BY_PREFIXES


def _parse_note_time(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _cs_time(cs: dict) -> datetime | None:
    """Extracts the creation timestamp from a changeset."""
    for field in ("created_at", "closed_at"):
        t_str = cs.get(field, "")
        if t_str:
            try:
                return datetime.fromisoformat(t_str.replace("Z", "+00:00"))
            except ValueError:
                pass
    return None


# We detect event windows by splitting days into sessions at gaps that exceed
# typical inter-edit intervals, then we keep the densest session. Gaps between
# survey events and setup or test edits last longer than pauses during active
# surveying.
#
# The threshold uses a multiple of the average inter-edit gap to adapt to the
# pace of each event, though it never falls below a floor. This prevents
# ordinary pauses when walking to another block from fracturing a session.
SESSION_GAP_FLOOR = timedelta(minutes=20)
SESSION_GAP_FACTOR = 4


def find_event_window(changesets: list, app_filter: tuple[str, ...] | None = None) -> tuple[datetime, datetime] | None:
    """Returns the time span of the most dense contiguous cluster of app
    changesets.

    We seed the search using changesets that match *app_filter* (which defaults
    to the package constant). The caller then filters all changesets to this
    window, including those that are not app-related.

    We divide the day into *sessions* when the gap between successive app
    changesets exceeds an adaptive threshold:

        ``max(SESSION_GAP_FLOOR, SESSION_GAP_FACTOR × median gap)``

    We identify the session with the highest count of changesets as the event
    and use its first and last timestamps to bound our window. That approach
    includes the full event duration while removing isolated setup or testing
    edits that appear earlier or later in the day.

    We return (window_start, window_end), or None if no clear cluster exists
    (because we have fewer than 2 app changesets or the data arrives already
    pre-filtered).
    """
    prefixes = APP_CREATED_BY_PREFIXES if app_filter is None else app_filter
    app_cs = [
        cs for cs in changesets
        if not prefixes
        or cs.get("tags", {}).get("created_by", "").startswith(prefixes)
    ]
    timestamps = sorted(filter(None, (_cs_time(cs) for cs in app_cs)))

    if len(timestamps) < 2:
        return None

    gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
    sorted_gaps = sorted(gaps)
    median_gap = sorted_gaps[len(sorted_gaps) // 2]
    threshold = max(SESSION_GAP_FLOOR, SESSION_GAP_FACTOR * median_gap)

    # We split timestamps into sessions when gaps exceed the threshold.
    sessions: list[list[datetime]] = [[timestamps[0]]]
    for prev_t, t, gap in zip(timestamps, timestamps[1:], gaps):
        if gap > threshold:
            sessions.append([t])
        else:
            sessions[-1].append(t)

    # We select the session with the most elements, then use the largest time
    # span to break ties.
    best = max(sessions, key=lambda s: (len(s), s[-1] - s[0]))
    if len(best) < 2:
        return None
    return best[0], best[-1]


def _compute_event_window(
    changesets: list,
) -> tuple[datetime | None, datetime | None]:
    """Calculates the earliest start (`earliest_start`) and latest end
    (`latest_end`) times from a list of changeset timestamps.

    We collect all valid timestamps from the `created_at` and `closed_at`
    fields in each changeset. If these fields contain ISO format strings, we
    convert them to `datetime` objects after replacing `Z` with `+00:00`. We
    ignore any field values that raise a `ValueError` during parsing.

    When no valid timestamps exist, we return `None, None`.
    """
    times: list[datetime] = []
    for cs in changesets:
        for field in ("created_at", "closed_at"):
            t_str = cs.get(field, "")
            if t_str:
                try:
                    times.append(datetime.fromisoformat(t_str.replace("Z", "+00:00")))
                except ValueError:
                    pass
    if not times:
        return None, None
    return min(times), max(times)


def fetch_notes(
    osm_url: str,
    ws_id: int,
    token: str = "",
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> list[dict]:
    """Retrieves workspace notes with optional filtering by an event time window.

    If we supply `window_start` or `window_end`, we only get notes where
    `date_created` falls in that range. We should use the event window from
    changeset timestamps to exclude notes created before or after the event.

    We need to pass a Bearer token because the `osm-rails` `notes/search`
    endpoint returns 500 without authentication (which matches the constraint
    in the frontend's `getNotes`).

    The function returns a list of simplified dicts containing
    `{lat, lon, text, user}` for map rendering and caching. The `user` field
    contains the author's name or `None` if the note is anonymous.
    """
    url = f"{osm_url.rstrip('/')}/api/0.6/notes/search.json?limit=10000&closed=-1"
    req = urllib.request.Request(url)
    req.add_header("X-Workspace", str(ws_id))
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    runtime._dbg(req)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        simplified = []
        for f in data.get("features", []):
            coords = (f.get("geometry") or {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            props = f.get("properties", {})
            opened = next(
                (c for c in props.get("comments", []) if c.get("action") == "opened"),
                {},
            )
            if window_start or window_end:
                note_time = _parse_note_time(props.get("date_created", ""))
                if note_time is not None:
                    if window_start and note_time < window_start:
                        continue
                    if window_end and note_time > window_end:
                        continue
            simplified.append({
                "lat": round(coords[1], 6),
                "lon": round(coords[0], 6),
                "text": opened.get("text", ""),
                "user": opened.get("user"),
            })
        return simplified
    except Exception as e:
        print(f"  WARNING: Failed to fetch notes: {e}")
        return []
