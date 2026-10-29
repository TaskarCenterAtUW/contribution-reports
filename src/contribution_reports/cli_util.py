"""Input and cache-shape utilities for the CLI entry point."""

import json
from datetime import date, timedelta
from pathlib import Path

from .constants import APP_CREATED_BY_PREFIXES


def resolve_app_filter(args, env: dict) -> tuple[str, ...]:
    if args.no_app_filter:
        return ()
    if args.app_filter:
        return tuple(args.app_filter)
    env_val = env.get("WS_APP_FILTER", "")
    if env_val:
        prefixes = tuple(v.strip() for v in env_val.split(",") if v.strip())
        if prefixes:
            return prefixes
    return APP_CREATED_BY_PREFIXES


def parse_date(date_str: str | None) -> date:
    if date_str:
        return date.fromisoformat(date_str)
    return date.today() - timedelta(days=1)


def _load_cache(cache_file: Path, date_str: str | None) -> dict:
    raw = json.loads(cache_file.read_text())
    if "workspaces" not in raw:
        raw = {
            "date": date_str or (date.today() - timedelta(days=1)).isoformat(),
            "workspaces": {
                k: {
                    "id": int(k),
                    "title": f"Workspace {k}",
                    "type": "osw",
                    "quest_definition": None,
                    "changesets": v,
                }
                for k, v in raw.items()
                if isinstance(v, list)
            },
        }
    return raw
