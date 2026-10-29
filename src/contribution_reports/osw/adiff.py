"""Data models and access methods for augmented-diffs.

The adiff endpoint provides the complete old and new states for each element a
changeset modified. It also includes *context rows*, which are elements the
changeset referenced without altering. We define three contract rules here to
ensure accounting remains accurate.
"""

import gzip
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from .. import runtime


def is_own_action(action: dict, changeset_id: int | str) -> bool:
    """Returns `True` when the `changeset_id` authored the `action` (Rule A).

    We need to filter context rows from the adiff because they represent
    elements authored elsewhere that the changeset merely references. Since
    these rows retain their original changeset and author, including them would
    misattribute work and inflate edit volume.
    """
    return str(action.get("new", {}).get("changeset")) == str(changeset_id)


def own_actions(actions: list[dict], changeset_id: int | str) -> list[dict]:
    """Filters a list of actions to include only those authored by the specified
    *changeset_id*.
    """
    return [a for a in actions if is_own_action(a, changeset_id)]


def effective_tags(action: dict) -> dict:
    """Provides classification tags that describe the element's previous state
    (Rule C).

    When a delete type action clears tags in `new`, we'd see every deleted way
    as untagged if we classified from `new`.
    """
    if action.get("type") == "delete":
        old_tags = (action.get("old") or {}).get("tags")
        if old_tags:
            return old_tags
    return action.get("new", {}).get("tags") or {}


def geometry_of(element: dict) -> list[list[float]]:
    """Returns a list of coordinate pairs, each containing lat and lon, for an
    adiff element, returning an empty list if no position exists.

    Because adiff responses include way geometry directly, we never need to
    call `/way/{id}/full`.
    """
    nodes = element.get("nodes")
    if nodes:
        return [[n["lat"], n["lon"]] for n in nodes
                if n.get("lat") is not None and n.get("lon") is not None]
    if element.get("lat") is not None and element.get("lon") is not None:
        return [[element["lat"], element["lon"]]]
    return []


PAGE_SIZE = 25  # we'll avoid this server's ~64 KB changeset-list truncation
FETCH_ATTEMPTS = 3
REQUEST_TIMEOUT = 600  # we set this because baseline import adiffs are large


class AdiffFetchError(Exception):
    """An exception raised when every attempt to retrieve a response intact fails.
    """


def fetch_json(url: str, headers: dict, attempts: int = FETCH_ATTEMPTS,
               sleep=time.sleep) -> dict:
    """Retrieves parsed JSON from *url* via GET or raises AdiffFetchError.

    We cannot accept truncated bodies. We guard against partial responses
    because they might look like valid data--such as half a changeset--which
    would corrupt the report without triggering a failure.
    """
    last_error = None
    for attempt in range(attempts):
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        req.add_header("Accept-Encoding", "gzip")
        for key, value in headers.items():
            req.add_header(key, value)
        runtime._dbg(req)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            parsed = json.loads(body)
            if not isinstance(parsed, dict):
                raise ValueError("required a JSON object but received "
                                     f"{type(parsed).__name__}")
            return parsed
        except Exception as e:                       # noqa: BLE001 - retry everything
            last_error = e
            if attempt < attempts - 1:
                sleep(2 ** attempt)
    raise AdiffFetchError(f"{url} failed after {attempts} attempts: "
                              f"{last_error}") from last_error


def _auth(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def fetch_changeset_list(osm_url: str, ws_id: int, token: str | None) -> list:
    """Retrieves all changesets from a workspace by paging backward through time.

    We use `PAGE_SIZE` because the server truncates responses that exceed that
    limit. Since the server returns HTTP 400 when we use the bare `time=,<ts>`
    upper-bound format, we always supply an explicit lower bound.
    """
    base = osm_url.rstrip("/")
    headers = {"X-Workspace": str(ws_id), **_auth(token)}
    collected: list = []
    seen: set = set()
    upper: datetime | None = None

    while True:
        query = f"limit={PAGE_SIZE}"
        if upper is not None:
            span = "1970-01-01T00:00:00Z," + upper.strftime("%Y-%m-%dT%H:%M:%SZ")
            query += "&time=" + urllib.parse.quote(span)
        batch = fetch_json(f"{base}/api/0.6/changesets.json?{query}",
                           headers).get("changesets", [])
        if not batch:
            break
        fresh = [cs for cs in batch if cs["id"] not in seen]
        seen.update(cs["id"] for cs in fresh)
        collected.extend(fresh)
        print(f"  {len(collected)} changesets...")
        if len(batch) < PAGE_SIZE or not fresh:
            break
        upper = min(datetime.fromisoformat(cs["created_at"].replace("Z", "+00:00"))
                    for cs in batch)
    return collected


def fetch_adiff(api_url: str, ws_id: int, cs_id: int, token: str | None) -> list:
    """Retrieves the augmented diff for a specific changeset and returns its raw
    actions list.
    """
    url = f"{api_url.rstrip('/')}/workspaces/{ws_id}/changesets/{cs_id}/adiff"
    return fetch_json(url, _auth(token)).get("actions", [])


def load_cache(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def save_cache(data: dict, path: Path) -> None:
    """Writes the cache as a gzipped file. Raw adiffs occupy ~25 MB in large
    workspaces, so we use compression.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f, default=str)
