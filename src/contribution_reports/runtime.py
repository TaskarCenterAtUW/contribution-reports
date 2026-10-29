"""Manages the global `DEBUG` flag and logs HTTP requests.

When we enable `DEBUG`, we can track request methods and full URLs. The logger
masks sensitive data by truncating `Authorization` and `X-api-key` headers.
"""

DEBUG = False


def set_debug(value: bool) -> None:
    global DEBUG
    DEBUG = value


def _dbg(req) -> None:
    if not DEBUG:
        return
    headers = dict(req.headers)
    if "Authorization" in headers:
        headers["Authorization"] = headers["Authorization"][:14] + "…"
    # We mask the Anthropic API key because urllib capitalizes the first
    # letter, which turns the header into "X-api-key".
    if "X-api-key" in headers:
        headers["X-api-key"] = headers["X-api-key"][:8] + "…"
    print(f"  [DEBUG] {req.get_method()} {req.full_url}")
    for k, v in headers.items():
        print(f"          {k}: {v}")
