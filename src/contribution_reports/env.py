"""Resolves and loads environment variables from the active *.env* file.

We always source *.env* files through a bash subprocess using
`set -a && source` instead of parsing them in Python. If no *.env* file exists,
we return only shell `WS_*` variables. Live fetches do not fail here; they fail
later during their own URL checks.
"""

import os
import shlex
import subprocess
import sys
from pathlib import Path


def resolve_env_file(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        if not explicit.exists():
            print(f"ERROR: .env does not exist at {explicit}", file=sys.stderr)
            sys.exit(1)
        return explicit
    ws_env = os.environ.get("WS_ENV_FILE")
    if ws_env:
        path = Path(ws_env)
        if not path.exists():
            print(
                "ERROR: WS_ENV_FILE is set but the .env file does not exist "
                    f"at {path}", file=sys.stderr
            )
            sys.exit(1)
        return path
    cwd = Path.cwd()
    for d in [cwd, *cwd.parents]:
        candidate = d / ".env"
        if candidate.exists():
            return candidate
    return None


def load_env(env_file: Path | str | None = None) -> dict:
    explicit = Path(env_file) if env_file is not None else None
    path = resolve_env_file(explicit)
    env: dict = {}
    if path is not None:
        result = subprocess.run(
            ["bash", "-c", f"set -a && source {shlex.quote(str(path))} && env"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            err_lines = result.stderr.strip().splitlines()
            reason = (
                err_lines[0]
                if err_lines
                else f"bash failed with exit code {result.returncode}"
            )
            print(f"ERROR: could not source {path}: {reason}", file=sys.stderr)
            sys.exit(1)
        for line in result.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                env[k] = v
    # Environment variables starting with WS_ override values from the .env
    # file, so we can pass WS_OSM_URL=... via the command line to take
    # precedence.
    for k, v in os.environ.items():
        if k.startswith("WS_"):
            env[k] = v
    return env
