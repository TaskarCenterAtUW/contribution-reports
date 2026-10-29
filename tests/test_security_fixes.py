"""Security regression tests checking HTML escaping, JSON in script contexts, zip
limits, and validation of slugs and IDs.
"""

import html as html_mod
import json

import pytest

from contribution_reports.render import _attr_json, render_report
from contribution_reports.summary import render_summary

from _security_fixes_helpers import MARKER, _extract_events, _summary_ctx


BREAKOUT = "</script><script>x</script>"


def _main_report_html(tmp_path, workspace_title=None):
    data = {
        "date": "2026-06-01",
        "workspaces": {"7": {"id": 7, "title": "Clean", "changesets": []}},
    }
    out = tmp_path / "report.html"
    render_report(data, out, workspace_title=workspace_title)
    return out.read_text(encoding="utf-8")


# We enable Jinja autoescape on all templates ending in `.html.j2`.


def test_main_report_escapes_workspace_title(tmp_path):
    html = _main_report_html(tmp_path, workspace_title=MARKER)
    assert MARKER not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_osw_report_escapes_workspace_title(tmp_path):
    from contribution_reports.osw.render import render_report as osw_render_report

    data = {
        "workspaces": {
            "1280": {
                "id": 1280,
                "title": MARKER,
                "type": "osw",
                "changesets": [],
                "adiffs": {},
                "adiff_failures": {},
            }
        }
    }
    out = tmp_path / "osw.html"
    osw_render_report(data, out)
    html = out.read_text(encoding="utf-8")
    assert MARKER not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_summary_escapes_titles_and_keeps_css_literal(tmp_path):
    out = tmp_path / "summary.html"
    render_summary(_summary_ctx("A & B <i>c</i>"), "Report <script>z</script>", out)
    html = out.read_text(encoding="utf-8")
    assert "<i>c</i>" not in html
    assert "&lt;i&gt;c&lt;/i&gt;" in html
    assert "<script>z</script>" not in html
    # We need to keep the injected stylesheet raw because it serves as an
    # explicit opt-out.
    assert "tr.q-row:hover > td" in html


# The EVENTS script context uses tojson escaping.


def test_breakout_title_does_not_close_script_tag(tmp_path):
    out = tmp_path / "summary.html"
    render_summary(_summary_ctx(BREAKOUT), "T", out)
    html = out.read_text(encoding="utf-8")
    assert BREAKOUT not in html
    assert "\\u003c/script" in html
    # The JSON decodes to the intended value, so we preserve semantics visible
    # to the browser.
    assert _extract_events(html)[0]["title"] == BREAKOUT


def test_normal_payload_renders_and_extracts_as_expected(tmp_path):
    ctx = _summary_ctx("Normal Event")
    out = tmp_path / "summary.html"
    render_summary(ctx, "T", out)
    payload = _extract_events(out.read_text(encoding="utf-8"))
    expected = [
        {k: row[k] for k in ("title", "city", "lat", "lon", "r", "quests", "notes")}
        for row in ctx["events"]
    ]
    assert payload == expected


# The `attr_json` value persists after a single browser entity-decode.


@pytest.mark.parametrize(
    "value",
    [
        {"note": "he said &quot;hi&quot; & left"},
        ["safe&quot;,{&quot;evil&quot;:1}&quot;", "plain & legit"],
        {"k": '"quotes" & <angles> &amp;amp; entities'},
    ],
)
def test_attr_json_single_decode(value):
    body = str(_attr_json(value))
    assert '"' not in body  # we're safe inside a double-quoted attribute
    assert json.loads(html_mod.unescape(body)) == value


def test_attr_json_injected_keys_do_not_survive_decode():
    value = {"a": "x&quot;,&quot;injected&quot;:&quot;y"}
    body = str(_attr_json(value))
    parsed = json.loads(html_mod.unescape(body))
    assert parsed == value
    assert list(parsed) == ["a"]
