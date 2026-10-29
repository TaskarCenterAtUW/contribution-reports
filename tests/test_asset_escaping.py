"""Static XSS guards for shipped JS assets supporting M3 and M4 asset-side logic.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = (
    Path(__file__).resolve().parent.parent / "src" / "contribution_reports" / "assets"
)


def _read(name):
    return (ASSETS / name).read_text(encoding="utf-8")


def test_util_esc_includes_all_html_metacharacters():
    esc_src = re.search(r"function esc\(s\)[^\n]*", _read("util.js")).group(0)
    for needle in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert needle in esc_src


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_util_esc_escapes_every_metacharacter_using_node():
    script = (
        "eval(require('node:fs').readFileSync(process.argv[1],'utf8'));"
        "process.stdout.write(esc('<a href=\"x\">&\\''))"
    )
    out = subprocess.run(
        ["node", "-e", script, str(ASSETS / "util.js")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out == "&lt;a href=&quot;x&quot;&gt;&amp;&#39;"


def test_modals_gallery_lacks_inline_onclick_attributes():
    src = _read("modals.js")
    assert "onclick=" not in src
    assert "window.open" in src  # opens via an attached listener
    assert re.search(r"_galleryGrid\.addEventListener\(\s*'click'", src)


def test_modals_gallery_src_attribute_uses_escape_function():
    src = _read("modals.js")
    assert re.search(r'<img src="\$\{esc\(u\)\}"', src)


def test_modals_evidence_table_escapes_question_fields():
    src = _read("modals.js")
    for pattern in (
        r"\$\{esc\(q\.tag\)\}",
        r"\$\{esc\(q\.value\)\}",
        r"\$\{esc\(q\.label \|\| '—'\)\}",
    ):
        assert re.search(pattern, src), pattern


def test_popups_escape_user_mtype_and_label():
    src = _read("popups.js")
    assert "${esc(v.user)}" in src
    assert "${esc(mType)}" in src
    assert "${signIcon} ${esc(m.label)}" in src


def test_render_tag_table_escapes_key():
    src = _read("util.js")
    assert "${esc(k)}</td>" in src


def test_js_files_do_not_unescape_quot_entities():
    paths = sorted(ASSETS.glob("*.js")) + sorted(
        (ASSETS.parent / "osw" / "assets").glob("*.js")
    )
    assert paths
    for path in paths:
        assert "&quot;/g" not in path.read_text(encoding="utf-8"), path.name


def test_photo_button_html_escapes_ampersand_before_double_quote():
    src = _read("popups.js")
    line = next(l for l in src.splitlines() if "JSON.stringify(photos)" in l)
    amp = line.find("&/g")
    quot = line.find('"/g')
    assert amp != -1 and quot != -1 and amp < quot


# Count fields from the cache undergo coercion instead of raw insertion.


def test_util_ascount_helper_coerces_to_finite_number():
    body = re.search(r"function _asCount\(v\) \{[^}]*\}", _read("util.js"))
    assert body, "_asCount helper missing from util.js"
    assert "Number(" in body.group(0)
    assert "Number.isFinite" in body.group(0)


def test_modals_evidence_modal_contains_no_raw_count_interpolations():
    src = _read("modals.js")
    for raw in (
        "(m.quest_count||0)",
        "(m.note_count||0)",
        "${m.quest_count}",
        "${m.note_count}",
        "${q.count}",
        "q.count != null ? q.count :",
    ):
        assert raw not in src, raw


def test_modals_evidence_modal_coerces_all_count_fields():
    src = _read("modals.js")
    for coerced in (
        "_asCount(m.quest_count)",
        "_asCount(m.note_count)",
        "_asCount(q.count)",
    ):
        assert coerced in src, coerced


def test_popups_js_contains_no_raw_count_interpolations():
    src = _read("popups.js")
    for raw in (
        "h.count || 0",
        "h.voices || 0",
        "${h.quest_count}",
        "${h.note_count}",
        "${m.quest_count}",
        "${m.note_count}",
    ):
        assert raw not in src, raw


def test_popups_coerces_all_count_fields():
    src = _read("popups.js")
    for coerced in (
        "_asCount(h.count)",
        "_asCount(h.voices)",
        "_asCount(h.quest_count)",
        "_asCount(h.note_count)",
        "_asCount(m.quest_count)",
        "_asCount(m.note_count)",
    ):
        assert coerced in src, coerced


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_popup_builders_coerce_poisoned_counts_in_node():
    payload = "<img src=x onerror=alert(1)>"
    script = (
        "const fs=require('node:fs');"
        "const dir=process.argv[1];"
        "for (const f of ['colors.js','util.js','popups.js'])"
        " eval(fs.readFileSync(dir+'/'+f,'utf8'));"
        f"const payload={json.dumps(payload)};"
        "const poisoned=buildHotspotPopup({count:payload,voices:payload,"
        "quest_count:payload,note_count:payload,confidence:0.6,intensity:-0.5,"
        "evidence_points:[]});"
        "const poisonedIssue=makeIssuePopup({sign:'problem',score:-0.8,"
        "quest_count:payload,note_count:payload,quest_evidence:[{tag:'t',"
        "count:payload}],note_evidence:[],evidence_points:[]});"
        "const clean=buildHotspotPopup({count:5,voices:2,quest_count:'3',"
        "note_count:2,confidence:0.6,intensity:-0.5,evidence_points:[]});"
        "const cleanIssue=makeIssuePopup({sign:'problem',score:-0.8,"
        "quest_count:4,note_count:1,quest_evidence:[{}],note_evidence:[]});"
        "process.stdout.write(JSON.stringify({poisoned,poisonedIssue,clean,"
        "cleanIssue}));"
    )
    out = subprocess.run(
        ["node", "-e", script, str(ASSETS)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rendered = json.loads(out)
    joined = "".join(rendered.values())
    # The payload terminates at `_asCount`, so it doesn't reach the popup HTML.
    assert "onerror" not in joined
    assert "<img" not in joined
    assert "0 problem reports from 0 surveyors" in rendered["poisoned"]
    assert "quest answer" not in rendered["poisoned"]
    assert "Evidence" not in rendered["poisonedIssue"]
    # Numbers and numeric strings that contain no poisoning render without
    # changes.
    assert "5 problem reports from 2 surveyors" in rendered["clean"]
    assert "3 quest answers" in rendered["clean"]
    assert "2 notes" in rendered["clean"]
    assert "Evidence: 4 quest answers, 1 note" in rendered["cleanIssue"]
