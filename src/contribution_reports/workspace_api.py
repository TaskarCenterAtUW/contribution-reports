"""Fetches workspace information and quest definitions from the FastAPI backend.
"""

import json

from .auth import auth_headers
from .net import http_get_json


def fetch_workspace_info(ws_id: int, api_url: str, token: str | None) -> dict:
    try:
        data = http_get_json(f"{api_url.rstrip('/')}/workspaces/{ws_id}", auth_headers(token))
        return {
            "id": ws_id,
            "title": data.get("title", f"Workspace {ws_id}"),
            "type": data.get("type", "osw"),
        }
    except Exception as e:
        print(f"  WARNING: failed to fetch workspace {ws_id} info: {e}")
        return {"id": ws_id, "title": f"Workspace {ws_id}", "type": "osw"}


def _normalize_quest_def(raw):
    """Wraps raw element lists into a dictionary with an `elements` key.

    Some sources return a bare-list URL definition or come from legacy
    `/quests/long`, so they provide the list directly instead of using the
    `{"elements": [...]}` format. When we encounter a list, we normalize it to
    the latter.
    """
    if raw is None:
        return None
    return {"elements": raw} if isinstance(raw, list) else raw


def fetch_quest_definition(ws_id: int, api_url: str, token: str | None) -> dict | None:
    base = api_url.rstrip("/")
    headers = auth_headers(token)
    try:
        settings = http_get_json(f"{base}/workspaces/{ws_id}/quests/long/settings", headers)
        # We handle both snake_case from FastAPI and camelCase from legacy
        # systems.
        quest_type = settings.get("type") or settings.get("quest_type", "NONE")
        if quest_type == "DEFINITION":
            raw = settings.get("definition")
            return _normalize_quest_def(json.loads(raw)) if raw else None
        if quest_type == "URL":
            url = settings.get("url")
            return _normalize_quest_def(http_get_json(url)) if url else None
        # When `quest_type` is `"NONE"`, we let the execution fall through to
        # the `/quests/long` fallback below.
    except Exception as e:
        print(f"  WARNING: /quests/long/settings failed for workspace {ws_id}"
                  f": {e}")

    # We can fall back to the raw definition endpoint, which returns either the
    # definition JSON or a 204 No Content if no definition exists.
    try:
        return _normalize_quest_def(http_get_json(f"{base}/workspaces/{ws_id}/quests/long", headers))
    except Exception:
        pass
    return None
