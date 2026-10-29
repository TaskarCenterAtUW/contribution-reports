"""TDEI authentication manages the acquisition and transport of Bearer tokens.
"""

import getpass
import json
import sys
import urllib.request


def auth_headers(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def get_token(env: dict) -> str | None:
    if env.get("WS_REPORT_TOKEN"):
        return env["WS_REPORT_TOKEN"]

    tdei_url = env.get("WS_TDEI_BACKEND_URL", "")
    if not tdei_url:
        print("WARNING: WS_TDEI_BACKEND_URL is not set, so auth is skipped")
        return None

    try:
        username = env.get("WS_REPORT_USER") or input("TDEI username: ").strip()
        password = env.get("WS_REPORT_PASS") or getpass.getpass("TDEI password: ")
    except EOFError:
        print(
            "ERROR: no input on stdin; run interactively or set "
                "WS_REPORT_USER and WS_REPORT_PASS",
            file=sys.stderr,
        )
        sys.exit(1)

    if not username or not password:
        print("WARNING: no credentials provided, so auth is skipped")
        return None

    try:
        url = tdei_url.rstrip("/") + "/authenticate"
        print(f"Authenticating as {username}...")
        body = json.dumps({"username": username, "password": password}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req) as resp:
            token = json.loads(resp.read()).get("access_token")
        if token:
            print("  Authenticated")
        return token
    except Exception as e:
        print(f"WARNING: Authentication failed: {e}")
        return None
