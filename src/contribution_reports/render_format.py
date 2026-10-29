"""Formatting helpers for dates and attributes used in rendered reports."""

import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from markupsafe import Markup


def _attr_json(v) -> Markup:
    """Serializes *v* to JSON for use in double-quoted HTML data attributes.

    We escape `&` before we escape `"` because the browser's HTML parser
    performs exactly one entity-decode pass: first `&` becomes `&amp;`, then
    `"` becomes `&quot;`. JS must read the value straight from `dataset`; if we
    added `.replace(/&quot;/g, '"')` there, a literal `&quot;` inside a value
    would become a raw quote in the `JSON.parse` input.
    """
    return Markup(json.dumps(v).replace("&", "&amp;").replace('"', "&quot;"))


def format_date(d: date) -> str:
    return d.strftime("%B %-d, %Y")


def format_date_range(min_d: date, max_d: date) -> str:
    """Formats a date range by collapsing shared months or years where possible.
    """
    if min_d.year == max_d.year:
        if min_d.month == max_d.month:
            return f"{min_d.strftime('%B %-d')} – {max_d.strftime('%-d, %Y')}"
        return f"{min_d.strftime('%B %-d')} – {max_d.strftime('%B %-d, %Y')}"
    return f"{format_date(min_d)} – {format_date(max_d)}"


def _local_date_str(t_str: str, tz: str | None = None) -> str:
    """Returns an ISO UTC timestamp as a YYYY-MM-DD date string within a specified
    zone.

    If we don't provide a `tz`, the function defaults to UTC.
    """
    if not tz:
        return t_str[:10]
    t = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(ZoneInfo(tz)).date().isoformat()


def _ws_event_date(ws_data: dict, fallback: str, tz: str | None = None) -> str:
    """Returns the workspace event date in YYYY-MM-DD format."""
    if ws_data.get("event_date"):
        return ws_data["event_date"]
    for cs in ws_data.get("changesets", []):
        t_str = cs.get("created_at", "")
        if t_str:
            return _local_date_str(t_str, tz)
    return fallback
