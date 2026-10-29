"""Generates a self-contained HTML file representing the OSW workspace change
report.
"""

from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from ..constants import MODIFY_KIND_LABELS
from ..render import _attr_json, format_date, format_date_range
from .changes import CLASS_APP, CLASS_EDITOR, CLASS_IMPORT, build_ledger
from .rules import evaluate
from .state import build_state, final_elements

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_ASSETS_DIR = Path(__file__).parent / "assets"
_SHARED_ASSETS_DIR = Path(__file__).parent.parent / "assets"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)
_env.filters["attr_json"] = _attr_json

_CSS = (_SHARED_ASSETS_DIR / "report.css").read_text(encoding="utf-8")
_JS = (_ASSETS_DIR / "osw_map.js").read_text(encoding="utf-8")

# We use these changeset tags to track the validation trail from the editor.
_RESOLVED_PREFIX = "resolved:"
_WARNING_PREFIX = "warnings:"
_SOURCE_KEYS = ("imagery_used", "photos_used", "source", "created_by")


def _int_or_one(value: str) -> int:
    """Returns a validation-trail tag count as an integer, defaulting to 1 if the
    input lacks a plain non-negative integer format.

    We use this default for malformed values or bare marker tags missing count
    suffixes. For instance:
        "3.5" or "-1"

    If the tag exists, we treat it as at least one occurrence instead of
    triggering a parse failure.
    """
    return int(value) if value.isdigit() else 1


def _validation_trail(changesets: list) -> dict:
    resolved: Counter = Counter()
    outstanding: Counter = Counter()
    for cs in changesets:
        for key, value in cs.get("tags", {}).items():
            if key.startswith(_RESOLVED_PREFIX):
                resolved[key[len(_RESOLVED_PREFIX):]] += _int_or_one(value)
            elif key.startswith(_WARNING_PREFIX):
                outstanding[key[len(_WARNING_PREFIX):]] += _int_or_one(value)
    return {"resolved": dict(resolved.most_common()),
            "outstanding": dict(outstanding.most_common())}


def _sources(changesets: list) -> dict:
    collected: dict = defaultdict(set)
    for cs in changesets:
        for key in _SOURCE_KEYS:
            value = cs.get("tags", {}).get(key)
            if value:
                for part in value.split(";"):
                    if part.strip():
                        collected[key].add(part.strip())
    return {k: sorted(v) for k, v in collected.items()}


def _date_range_from_days(days) -> str:
    """Generates a min-max range string from an iterable of days formatted as
    "YYYY-MM-DD".

    We use this single implementation for both `_date_range` (which handles
    changesets per-workspace) and `render_report` (which handles days from
    every workspace across the whole-report) to prevent the two call sites from
    drifting apart.
    """
    days = sorted(d for d in days if d)
    if not days:
        return "Unknown date"
    first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    return format_date(first) if first == last else format_date_range(first, last)


def _date_range(changesets: list) -> str:
    return _date_range_from_days(cs["created_at"][:10] for cs in changesets
                                 if cs.get("created_at"))


def build_context(ws_data: dict, include_baseline: bool = False,
                  extract: dict | None = None) -> dict:
    """Computes data for each panel in a single workspace.

    When we provide an `extract` dict, it replaces the touched-element
    denominator. The resulting `state["scope"]` becomes `"dataset"` if an
    `extract` exists, otherwise it remains `"touched"`.
    """
    changesets = ws_data.get("changesets", [])
    adiffs = ws_data.get("adiffs", {})

    ledger = build_ledger(changesets, adiffs, include_baseline=include_baseline)
    final = final_elements(changesets, adiffs, include_baseline=include_baseline)
    # When we supply a full extract, it replaces the denominator of touched
    # elements.
    measured = extract if extract else final
    state = build_state(measured)
    state["scope"] = "dataset" if extract else "touched"
    findings = evaluate(measured)

    reported = [cs for cs in changesets
                if include_baseline or cs["id"] not in
                {c["id"] for c in ledger["provenance"].get(CLASS_IMPORT, [])}]

    return {
        "title": ws_data.get("title", f"Workspace {ws_data.get('id')}"),
        "bbox": ws_data.get("bbox"),
        "ledger": ledger,
        "modify_kind_labels": MODIFY_KIND_LABELS,
        "state": state,
        "findings": findings,
        "validation": _validation_trail(reported),
        "sources": _sources(reported),
        "date_range": _date_range(reported or changesets),
        "contributor_count": len(ledger["contributors"]),
        "include_baseline": include_baseline,
        "adiff_failures": ws_data.get("adiff_failures") or {},
        "provenance_counts": {
            CLASS_EDITOR: len(ledger["provenance"].get(CLASS_EDITOR, [])),
            CLASS_APP: len(ledger["provenance"].get(CLASS_APP, [])),
            CLASS_IMPORT: len(ledger["provenance"].get(CLASS_IMPORT, [])),
        },
    }


def render_report(data: dict, out_file: Path, include_baseline: bool = False,
                  report_title: str | None = None,
                  extracts: dict | None = None) -> None:
    """Renders each workspace in *data* into a single self-contained HTML file.

    If we provide *extracts*, it maps workspace IDs (strings that match keys in
    `data["workspaces"]`) to the `final` full-extract dict for that workspace.
    When a workspace lacks an entry, we fall back to the touched-element
    denominator instead of borrowing another workspace's extract.
    """
    section_tmpl = _env.get_template("osw_section.html.j2")
    workspaces = data.get("workspaces", {})
    extracts = extracts or {}

    body = ""
    titles = []
    all_days: list = []
    for ws_id_str, ws_data in workspaces.items():
        ctx = build_context(ws_data, include_baseline=include_baseline,
                            extract=extracts.get(ws_id_str))
        titles.append(ctx["title"])
        all_days += [cs["created_at"][:10] for cs in ws_data.get("changesets", [])
                     if cs.get("created_at")]
        body += section_tmpl.render(**ctx)

    date_str = _date_range_from_days(all_days)

    html = _env.get_template("osw_page.html.j2").render(
        report_title=report_title or "OSW Workspace Change Report",
        date=date_str,
        workspaces=Markup(" &nbsp;·&nbsp; ").join(titles),
        css=_CSS, js=_JS, body=body,
    )
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html)
    print(f"\nReport written to {out_file}")
