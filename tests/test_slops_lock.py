"""These tests lock behavior during slop-cleanup across 13 ported modules.

Each test pins one uncovered observable behavior in the existing code that
originated from this repo's deltas or upstream reportgen. These pins record
actual results instead of ideal ones to provide a regression net for per-file
cleanup agents.
"""

import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contribution_reports import auth, env
from contribution_reports.analysis import count_created_features
from contribution_reports.events import find_event_window


REPO_ROOT = Path(__file__).resolve().parent.parent


# This pinned sha256 requires a byte-for-byte match from the offline-rendered
# golden report.
GOLDEN_REPORT_SHA256 = (
    "ea1b53e895c9fe45ab299f5d911add2ce6d00057ed4933a628942a9368770dbb"
)


# The console script processes examples/changeset.zip as a golden test.
def test_offline_report_is_byte_identical_to_golden_file(tmp_path):
    # The harness uses only the console script with a stripped environment and
    # no reachable network inputs. The rendered report must remain
    # byte-identical to the verified hash.
    script = Path(sys.executable).parent / "contribution-report"
    assert script.exists(), f"console script missing: {script}"
    env_file = tmp_path / "empty.env"
    env_file.write_bytes(b"")
    cache = tmp_path / "golden_cache.json"
    out = tmp_path / "golden_report.html"

    proc = subprocess.run(
        [
            str(script),
            "--offline",
            str(REPO_ROOT / "examples" / "changeset.zip"),
            "--quest-file",
            str(REPO_ROOT / "examples" / "renton-quest.json"),
            "--cache-file",
            str(cache),
            "--output",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env={"HOME": "/tmp", "WS_ENV_FILE": str(env_file), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr

    data = out.read_bytes()
    assert data, "golden report is empty"
    assert hashlib.sha256(data).hexdigest() == GOLDEN_REPORT_SHA256
    assert cache.exists() and cache.stat().st_size > 0


# The `__init__.py` file provides the re-export surface for the package root.
#
# We'll skip testing `paths.default_output_dir()` here because
# *tests/test_paths.py* already pins it.


def test_package_root_reexports_all_declared_names():
    import contribution_reports as pkg

    for name in pkg.__all__:
        assert getattr(pkg, name, None) is not None, f"{name} not re-exported"


# auth.py branches
def test_get_token_returns_environment_token_without_prompting(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("must not prompt when WS_REPORT_TOKEN is set")

    monkeypatch.setattr("builtins.input", _boom)
    monkeypatch.setattr(auth.getpass, "getpass", _boom)
    assert auth.get_token({"WS_REPORT_TOKEN": "t0k"}) == "t0k"


def test_get_token_without_backend_url_is_none_and_warns(capsys):
    assert auth.get_token({}) is None
    assert "WS_TDEI_BACKEND_URL" in capsys.readouterr().out


def test_get_token_blank_credentials_warns_and_returns_none(monkeypatch, capsys):
    # Blank inputs and passwords trigger a short-circuit before the code builds
    # any HTTP request.
    monkeypatch.setattr("builtins.input", lambda prompt: "   ")
    monkeypatch.setattr(auth.getpass, "getpass", lambda prompt: "")
    assert auth.get_token({"WS_TDEI_BACKEND_URL": "http://auth.test"}) is None
    out = capsys.readouterr().out
    assert "no credentials provided" in out


def test_auth_headers_presence():
    assert auth.auth_headers(None) == {}
    assert auth.auth_headers("abc") == {"Authorization": "Bearer abc"}


# env.py delta branches
def test_load_env_reports_source_failure_reason(tmp_path, capsys):
    f = tmp_path / ".env"
    f.write_text("WS_BROKEN='unterminated quote\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        env.load_env(f)
    err = capsys.readouterr().err
    assert err.startswith("ERROR")
    assert "could not source" in err
    assert str(f) in err


def test_load_env_keeps_keys_from_file_that_are_non_ws(tmp_path):
    # Shell-side overrides undergo filtering to WS_*, but the returned dict
    # retains all values from the env file regardless of their prefix.
    f = tmp_path / "e.env"
    f.write_text("PLAIN_PIN=keepme\n", encoding="utf-8")
    assert env.load_env(f).get("PLAIN_PIN") == "keepme"


# events.py app_filter param
def test_find_event_window_uses_only_custom_prefixes_to_seed_the_window():
    def cs(by, when):
        return {"tags": {"created_by": by}, "created_at": when}

    items = [
        cs("MyApp 1", "2026-01-01T10:00:00Z"),
        cs("MyApp 1", "2026-01-01T10:01:00Z"),
        cs("Rider 2", "2026-01-05T00:00:00Z"),
    ]
    window = find_event_window(items, ("MyApp",))
    assert window == (
        datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 10, 1, tzinfo=timezone.utc),
    )
    # Built-in prefixes and prefixes that do not match any items seed nothing,
    # so the function returns no window.
    assert find_event_window(items) is None
    assert find_event_window(items, ("Other",)) is None


# These tests guard against analysis.ParseError. This group constitutes the
# count_created_features half of those guards, and they verify that
# count_created_features does not raise when it encounters malformed OSC.
def test_count_created_features_skips_malformed_osc_and_does_not_raise():
    truncated = '<osmChange><create><node id="1">'
    good = (
        '<osmChange><create><node id="2" lat="1.0" lon="2.0">'
        '<tag k="highway" v="footway"/></node></create></osmChange>'
    )
    counts = count_created_features([{"osc_xml": truncated}, {"osc_xml": good}], {})
    assert sum(counts.values()) == 1
