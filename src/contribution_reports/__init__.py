"""Generates reports for TDEI Workspaces.

We re-export the public API here so we can access entry points through a single
`import contribution_reports`.
"""

from .auth import auth_headers, get_token
from .env import load_env
from .fetch import enrich_with_prev_tags
from .net import http_get_json
from .quests import build_quest_index
from .render import _ws_event_date, render_report
from .runtime import set_debug
from .workspace_api import fetch_quest_definition, fetch_workspace_info
from .events import fetch_notes

__all__ = [
    "load_env",
    "get_token",
    "auth_headers",
    "http_get_json",
    "fetch_workspace_info",
    "fetch_quest_definition",
    "fetch_notes",
    "_ws_event_date",
    "render_report",
    "build_quest_index",
    "enrich_with_prev_tags",
    "set_debug",
]
