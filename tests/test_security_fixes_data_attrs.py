"""Verifies that report data attributes properly escape cache-derived payloads.
"""

import html as html_mod
import json
import re

from contribution_reports.render import render_report
from contribution_reports.summary import render_summary

from _security_fixes_helpers import MARKER, _extract_events, _summary_ctx


# Cache-derived counts and titles cannot reach popup HTML raw.


def _poisoned_report_html(tmp_path):
    data = {
        "date": "2026-06-01",
        "workspaces": {
            "7": {
                "id": 7,
                "title": "WS",
                "changesets": [],
                "notes": [],
                "hotspots": [
                    {
                        "rank": 1,
                        "centroid": [1.0, 2.0],
                        "count": MARKER,
                        "voices": MARKER,
                        "quest_count": MARKER,
                        "note_count": MARKER,
                        "intensity": -0.5,
                        "confidence": 0.5,
                        "conf_quantity": 0.5,
                        "conf_agreement": 0.5,
                        "conf_corroboration": 0.6,
                        "label": 'label " & <b>meta</b>',
                        "evidence_points": [],
                    }
                ],
                "issues": [
                    {
                        "rank": 1,
                        "centroid": [1.5, 2.5],
                        "combined_score": -0.8,
                        "trav_score": None,
                        "conn_score": -0.8,
                        "safety_score": None,
                        "derived": False,
                        "derived_from": None,
                        "segment": {
                            "name": 'Main <&"> St',
                            "side": "east",
                            "label": "Main St",
                            "geometry": [[1.5, 2.5], [1.6, 2.6]],
                        },
                        "summary": "summary & <i>payload</i>",
                        "quest_count": MARKER,
                        "note_count": MARKER,
                        "quest_evidence": [
                            {
                                "tag": "ext:surface",
                                "value": MARKER,
                                "label": "rough",
                                "weight": -0.3,
                                "dimensions": ["traversability"],
                                "count": MARKER,
                            }
                        ],
                        "note_evidence": [],
                        "evidence_points": [],
                        "confidence": 0.5,
                        "sign": "problem",
                    }
                ],
            }
        },
    }
    out = tmp_path / "report.html"
    render_report(data, out, app_filter=())
    return out.read_text(encoding="utf-8")


def _data_attr(html, name):
    return next(
        html_mod.unescape(m) for m in re.findall(rf'data-{name}="([^"]*)"', html)
    )


def test_new1_poisoned_counts_round_trip_in_data_attributes(tmp_path):
    html = _poisoned_report_html(tmp_path)
    hotspots = json.loads(_data_attr(html, "hotspots"))
    assert hotspots[0]["count"] == MARKER
    assert hotspots[0]["quest_count"] == MARKER
    issues = json.loads(_data_attr(html, "issues"))
    assert issues[0]["quest_count"] == MARKER
    assert issues[0]["quest_evidence"][0]["count"] == MARKER
    evidence_btn = json.loads(_data_attr(html, "m"))
    assert evidence_btn["quest_count"] == MARKER


def test_new1_poisoned_payload_stays_raw_only_in_data_attrs(tmp_path):
    html = _poisoned_report_html(tmp_path)
    stripped = re.sub(r'data-(?:markers|issues|hotspots|m)="[^"]*"', "", html)
    assert MARKER not in stripped
    # We also need to verify that no inline script block receives the raw
    # payload. Because the report's assets undergo concatenation into a single
    # file, payload text can only arrive through data attributes.
    for script in re.findall(r"<script>(.*?)</script>", stripped, re.S):
        assert MARKER not in script


def test_new1_summary_popup_title_is_escaped(tmp_path):
    out = tmp_path / "summary.html"
    render_summary(_summary_ctx(MARKER), "T", out)
    html = out.read_text(encoding="utf-8")
    # We see no raw output in either the autoescaped body or the tojson script
    # context.
    assert MARKER not in html
    # We can decode the EVENTS payload once while maintaining context
    # awareness. Because the popup reads the live value, we pass it through
    # esc() when rendering the popup.
    assert _extract_events(html)[0]["title"] == MARKER
    assert "'<b>' + esc(p.title)" in html
    assert "esc(p.quests)" in html
    assert "esc(p.notes)" in html
    assert " + p.title" not in html
    # We verify that the inline escape processes all five HTML metacharacters.
    script = re.search(r"<script>\n(.*?)</script>", html, re.S).group(1)
    for needle in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert needle in script
