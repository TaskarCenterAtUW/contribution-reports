"""HTTP helper functions for requests sent to workspace and OSM APIs."""

import json
import urllib.request

from . import runtime


def http_get_json(url: str, headers: dict = None, token: str | None = None) -> dict | list:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    runtime._dbg(req)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def osm_get_json(url_base: str, path: str, ws_id: int, token: str | None = None) -> dict | list:
    url = url_base.rstrip("/") + "/" + path.lstrip("/")
    return http_get_json(url, {"X-Workspace": str(ws_id)}, token=token)


def osm_get_xml(url_base: str, path: str, ws_id: int, token: str | None = None) -> str:
    url = url_base.rstrip("/") + "/" + path.lstrip("/")
    req = urllib.request.Request(url)
    req.add_header("X-Workspace", str(ws_id))
    req.add_header("Accept", "application/xml")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    runtime._dbg(req)
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8")


def http_post_form(url: str, params: dict, headers: dict = None) -> str:
    """POSTs `params` using the `application/x-www-form-urlencoded` content type
    and returns the response body as raw text.

    We use this when calling the Overpass API, which requires `data=<query>`
    form encoding.
    """
    import urllib.parse
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    # We omit the Accept header because Overpass follows the `[out:json]`
    # directive in the query body.
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    runtime._dbg(req)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")
