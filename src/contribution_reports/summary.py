"""Aggregates cached per-event contribution reports into a one-page summary.

We maintain parity with counting rules in published reports by using the filter
functions from the per-event `report-summary --events-file <catalog>` flow.
"""

import argparse
import json
import sys
from pathlib import Path

from . import paths
from . import runtime
from .summary_core import (
    EventStats,
    _changeset_position,
    _first_workspace,
    aggregate,
    load_catalog,
    load_event,
    render_summary,
)

DEFAULT_SUMMARY_TITLE = "Contribution Summary"


def auto_catalog_events(cache_dir: Path) -> list[dict]:
    """Generates event lists from all `changesets_<slug>.json` cache files found
    in the specified directory.

    Because the code cannot automatically determine per-event `use_window`
    values, we default every event to `True`. To get exact published figures,
    we need to pass `--events-file`.
    """
    events: list[dict] = []
    for path in sorted(cache_dir.glob("changesets_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"  WARNING: could not read cache {path.name}: {exc}", file=sys.stderr
            )
            continue
        slug = path.stem.removeprefix("changesets_")
        ws = _first_workspace(data)
        title = ws.get("title") or slug
        positions = [
            p for p in (_changeset_position(cs) for cs in ws.get("changesets", [])) if p
        ]
        events.append(
            {
                "slug": slug,
                "title": title,
                "use_window": True,
                "city": title,
                "lat": sum(p[0] for p in positions) / len(positions)
                if positions
                else 0.0,
                "lon": sum(p[1] for p in positions) / len(positions)
                if positions
                else 0.0,
            }
        )
    return events


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the program one-page contribution summary "
        "from cached event reports (no API calls)"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory for changesets_<slug>.json caches (default: ./output)",
    )
    parser.add_argument(
        "--events-file",
        type=Path,
        default=None,
        help="JSON file containing event objects (overrides cache-dir auto-discovery)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to save the rendered one-pager (default: "
        "<cache-dir>/summary_contributions.html)",
    )
    parser.add_argument(
        "--report-title",
        default=DEFAULT_SUMMARY_TITLE,
        help=f"Set the page <h1> and <title> text (default: '{DEFAULT_SUMMARY_TITLE}')",
    )
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    runtime.set_debug(args.debug)

    cache_dir = args.cache_dir if args.cache_dir else paths.default_output_dir()
    out_file = args.output if args.output else cache_dir / "summary_contributions.html"

    if args.events_file:
        try:
            events = load_catalog(Path(args.events_file))
        except (OSError, ValueError) as exc:
            print(f"ERROR: {args.events_file}: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        events = auto_catalog_events(cache_dir)
    loaded, skipped = [], 0
    for event in events:
        try:
            stats = load_event(event, cache_dir)
        except Exception as exc:  # one corrupt cache must not kill the poster
            print(f"  WARNING: {event['slug']}: {exc}", file=sys.stderr)
            stats = None
        if stats is None:
            skipped += 1
        else:
            loaded.append(stats)

    ctx = aggregate(loaded)
    ctx["skipped"] = skipped
    render_summary(ctx, args.report_title, out_file)
    print(f"Wrote {out_file} ({len(loaded)} events, {skipped} skipped)")
