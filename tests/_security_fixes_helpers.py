"""Provides shared builders for security regression suites."""

import json
from datetime import date

from contribution_reports.summary import EventStats, aggregate


MARKER = "<img src=x onerror=alert(1)>"


def _summary_ctx(title):
    stats = EventStats(
        title=title,
        city="X",
        lat=1.0,
        lon=2.0,
        quests=1,
        notes=0,
        contributors={"u"},
        element_mix={},
        features=0,
        date_min=date(2026, 5, 19),
        date_max=date(2026, 5, 19),
    )
    ctx = aggregate([stats])
    ctx["skipped"] = 0
    return ctx


def _extract_events(html):
    line = next(l for l in html.splitlines() if "const EVENTS" in l)
    return json.loads(line.split("=", 1)[1].strip().rstrip(";"))
