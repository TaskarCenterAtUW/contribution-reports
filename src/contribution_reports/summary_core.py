"""Handles data loading and tallies for the program's one-page contribution
summary.
"""

import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .analysis import analyse, count_created_features, count_questions
from .constants import ELEMENT_TYPE_COLORS, ELEMENT_TYPE_ORDER
from .events import _cs_time, find_event_window
from .quests import build_quest_index
from .render import filter_app_changesets, format_date, format_date_range

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_CSS_PATH = Path(__file__).parent / "assets" / "report.css"

# We build cache filenames from event slugs, so we reject any input that might
# escape the cache directory when we join it into a path.
_EVENT_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


def load_catalog(path) -> list[dict]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("a JSON list containing event objects was required")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"item at index {i} must be a dictionary: "
                                 f"{item!r}")
        missing = {"slug", "title", "use_window", "city", "lat", "lon"} - set(item)
        if missing:
            raise ValueError(
                f"event {item.get('slug')!r} missing keys: {sorted(missing)}"
            )
    return items


def _changeset_position(cs: dict) -> tuple[float, float] | None:
    """Determines the optimal coordinates for a changeset by mirroring marker
    priority.

    We first check for a cached element midpoint via `elem_lat` and `elem_lon`.
    If those are missing, we look for any geometry in `all_elem_geoms` that
    provides a `lat` and `lon`. When no element coordinates exist, we fall back
    to the center of the changeset bbox calculated from `min_lat`, `min_lon`,
    `max_lat`, and `max_lon`.
    """
    if cs.get("elem_lat") is not None and cs.get("elem_lon") is not None:
        return float(cs["elem_lat"]), float(cs["elem_lon"])
    for geom in (cs.get("all_elem_geoms") or {}).values():
        if geom.get("lat") is not None and geom.get("lon") is not None:
            return float(geom["lat"]), float(geom["lon"])
    box = [cs.get(k) for k in ("min_lat", "min_lon", "max_lat", "max_lon")]
    if None not in box:
        return (float(box[0]) + float(box[2])) / 2, (float(box[1]) + float(box[3])) / 2
    return None


def _first_workspace(data: dict) -> dict:
    """Returns the sole workspace from a per-event cache payload."""
    return next(iter(data.get("workspaces", {}).values()), {})


@dataclass
class EventStats:
    title: str
    city: str
    lat: float
    lon: float
    quests: int = 0
    questions: int = 0
    notes: int = 0
    contributors: set = field(default_factory=set)
    element_mix: dict = field(default_factory=dict)
    features: int = 0
    date_min: date | None = None
    date_max: date | None = None


def load_event(event: dict, cache_dir: Path) -> EventStats | None:
    """Reduces a single event cache to an `EventStats` object.

    We return `None` if the cache file is absent or the app filter removes all
    entries, which sends a warning to stderr and prevents a stale event from
    aborting the run.

    A `ValueError` is raised if the slug does not match the plain
    discover-style format.
    """
    slug = event["slug"]
    if not _EVENT_SLUG_RE.match(slug):
        raise ValueError(f"invalid event slug: {slug!r}")
    path = cache_dir / f"changesets_{slug}.json"
    if not path.exists():
        print(
            f"  WARNING: cache {path.name} does not exist, so "
                f"{event['title']} is skipped",
            file=sys.stderr,
        )
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    ws = _first_workspace(data)

    cs = filter_app_changesets(ws.get("changesets", []))
    if event["use_window"]:
        win = find_event_window(cs)
        if win:
            start, end = win
            cs = [c for c in cs if (t := _cs_time(c)) is not None and start <= t <= end]
    if not cs:
        print(
            f"  WARNING: no survey-app changesets in {event['slug']}, so "
                f"{event['title']} is skipped",
            file=sys.stderr,
        )
        return None

    notes = ws.get("notes") or []
    quest_index = build_quest_index(ws.get("quest_definition"))
    stats = analyse(cs, quest_index, notes)
    created = count_created_features(cs, quest_index)
    # We match the pipeline and total used for the Questions Answered -> Total
    # badge in published reports. We run count_questions on these filtered
    # changesets and sum all answer counts, which mirrors how section.html.j2
    # sums q_breakdown totals.
    q_counts = count_questions(cs, quest_index) if quest_index else {}
    questions = sum(
        sum(val_counts.values())
        for tag_counts in q_counts.values()
        for val_counts in tag_counts.values()
    )
    times = [t for t in (_cs_time(c) for c in cs) if t is not None]
    return EventStats(
        title=event["title"],
        city=event["city"],
        lat=event["lat"],
        lon=event["lon"],
        quests=len(cs),
        questions=questions,
        notes=len(notes),
        contributors=set(stats["users"]),
        element_mix=stats["quest"],
        features=sum(created.values()),
        date_min=min(t.date() for t in times) if times else None,
        date_max=max(t.date() for t in times) if times else None,
    )


def _row_date_str(event_stats: EventStats) -> str:
    if event_stats.date_min is None:
        return ""
    if event_stats.date_min == event_stats.date_max:
        return format_date(event_stats.date_min)
    return format_date_range(event_stats.date_min, event_stats.date_max)


def aggregate(events: list[EventStats]) -> dict:
    """Combines individual `EventStats` tallies into a render context for the
    one-pager.

    We sort events by `date_min` (using `date.max` as a fallback), which lets
    us establish a `max_total` based on the highest combined count of `quests`
    and `notes`. For each event, we generate a row containing its `title`,
    `city`, `lat`, `lon`, a processed `date_str`, and raw counts for `quests`
    and `notes`. We also calculate a `total` plus normalized percentages
    (`q_pct`, `n_pct`) and a radius value `r` derived from the square root of
    the event's share of `max_total`.

    We build an `element_mix` list by summing all `element_mix` entries across
    events. These entries follow the order in `ELEMENT_TYPE_ORDER`, with any
    additional types appended and sorted by frequency descending. Each entry
    includes the element `type`, its total `count`, a `share` relative to the
    sum of all `quests`, and a `color` fetched from `ELEMENT_TYPE_COLORS`
    (defaulting to `#adb5bd`).

    We determine the `date_span` by finding the min and max dates across all
    events, which we format as a single date or range. If no dates exist, we
    use "Unknown dates".

    Finally, we calculate global totals for `events`, `quests`, `questions`,
    `notes`, `features`, and unique `contributors`. We also compute a
    `question_ratio_str` representing questions as a percentage of the combined
    sum of questions, notes, and features, which we return as a dash if that
    sum is zero.
    """
    ordered = sorted(events, key=lambda e: e.date_min or date.max)
    max_total = max((e.quests + e.notes for e in ordered), default=0) or 1
    rows = []
    for e in ordered:
        total = e.quests + e.notes
        rows.append(
            {
                "title": e.title,
                "city": e.city,
                "lat": e.lat,
                "lon": e.lon,
                "date_str": _row_date_str(e),
                "quests": e.quests,
                "notes": e.notes,
                "total": total,
                "q_pct": round(100 * e.quests / max_total, 1),
                "n_pct": round(100 * e.notes / max_total, 1),
                "r": round(6 + 22 * math.sqrt(total / max_total), 1),
            }
        )

    mix: dict[str, int] = {}
    for e in ordered:
        for etype, count in e.element_mix.items():
            mix[etype] = mix.get(etype, 0) + count
    known = [t for t in ELEMENT_TYPE_ORDER if t in mix]
    extras = sorted(
        (t for t in mix if t not in ELEMENT_TYPE_ORDER), key=lambda t: -mix[t]
    )
    total_quests = sum(e.quests for e in ordered)
    element_mix = [
        {
            "type": t,
            "count": mix[t],
            "share": round(mix[t] / max(total_quests, 1), 3),
            "color": ELEMENT_TYPE_COLORS.get(t, "#adb5bd"),
        }
        for t in known + extras
    ]

    all_dates = [d for e in ordered for d in (e.date_min, e.date_max) if d]
    if all_dates:
        lo, hi = min(all_dates), max(all_dates)
        date_span = format_date(lo) if lo == hi else format_date_range(lo, hi)
    else:
        date_span = "Unknown dates"

    contributors: set = set()
    for e in ordered:
        contributors |= e.contributors

    notes_total = sum(e.notes for e in ordered)
    features_total = sum(e.features for e in ordered)
    questions_total = sum(e.questions for e in ordered)
    answered_total = questions_total + notes_total + features_total
    question_ratio_str = (
        f"{100 * questions_total / answered_total:.1f}%" if answered_total else "—"
    )

    return {
        "events": rows,
        "element_mix": element_mix,
        "totals": {
            "events": len(ordered),
            "quests": total_quests,
            "questions": questions_total,
            "notes": notes_total,
            "contributors": len(contributors),
            "features": features_total,
            "question_ratio_str": question_ratio_str,
        },
        "date_span": date_span,
        "max_total": max_total,
    }


def render_summary(ctx: dict, report_title: str, out_file: Path) -> None:
    """Generates a self-contained HTML page from the aggregate context dict."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )
    data = dict(ctx)
    data["report_title"] = report_title
    data["css"] = _CSS_PATH.read_text(encoding="utf-8")
    map_keys = ("title", "city", "lat", "lon", "r", "quests", "notes")
    data["events_payload"] = [{k: row[k] for k in map_keys} for row in data["events"]]
    out_file.write_text(
        env.get_template("summary.html.j2").render(**data), encoding="utf-8"
    )
