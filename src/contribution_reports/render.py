"""Generates self-contained HTML reports by processing analysis data through
Jinja2 templates.
"""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from .constants import APP_CREATED_BY_PREFIXES, diverging_color, text_on_color
from .events import _cs_time, find_event_window
from .quests import build_choices_index, build_quest_index
from .render_builders import _build_section_context, _merge_dim_coverage
from .render_format import (
    _attr_json,
    _local_date_str,
    _ws_event_date,
    format_date,
    format_date_range,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_ASSETS_DIR = Path(__file__).parent / "assets"

DEFAULT_REPORT_TITLE = "Contribution Report"


def filter_app_changesets(
    changesets: list, app_filter: tuple[str, ...] | None = None
) -> list:
    """Filters for changesets that survey-app clients created.

    We can use *app_filter* to specify the `created_by` prefixes. If we pass
    `None`, we use the package constant; if we pass an empty tuple, we disable
    filtering and all changesets pass.
    """
    prefixes = APP_CREATED_BY_PREFIXES if app_filter is None else app_filter
    if not prefixes:
        return list(changesets)
    return [
        cs
        for cs in changesets
        if cs.get("tags", {}).get("created_by", "").startswith(prefixes)
    ]


_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)
_env.filters["attr_json"] = _attr_json
_env.filters["diverging_color"] = diverging_color
_env.filters["text_on_color"] = text_on_color

# We read static assets into memory during module import so we only load them
# once.
_CSS = (_ASSETS_DIR / "report.css").read_text(encoding="utf-8")
_GALLERY_MODAL = (_TEMPLATES_DIR / "gallery_modal.html.j2").read_text(encoding="utf-8")

_JS_MODULES = ["colors.js", "util.js", "popups.js", "modals.js", "ui.js", "map.js"]
_js_body = "\n\n".join(
    (_ASSETS_DIR / f).read_text(encoding="utf-8") for f in _JS_MODULES
)
_GALLERY_JS = f"<script>\n(function () {{\n{_js_body}\n}})();\n</script>\n"


def render_report(
    data: dict,
    out_file: Path,
    show_positive: bool = True,
    apply_window: bool = True,
    report_title: str | None = None,
    workspace_title: str | None = None,
    app_filter: tuple[str, ...] | None = None,
) -> None:
    """Generates a self-contained HTML report file from a cached data dict."""
    # We filter each workspace so it contains only changesets that survey-app
    # clients created.
    for ws_data in data.get("workspaces", {}).values():
        all_cs = ws_data.get("changesets", [])
        filtered = filter_app_changesets(all_cs, app_filter)
        if len(filtered) != len(all_cs):
            print(
                f"  App filter: {len(all_cs)} → {len(filtered)} changesets "
                f"(ws {ws_data.get('id', '?')})"
            )
        ws_data["changesets"] = filtered

    # If `apply_window` is true, we can trim each workspace to the window
    # containing its densest events. The detected window stretches to the
    # session's true duration with no fixed cap, and find_event_window states
    # how the window is found.
    if apply_window:
        for ws_data in data.get("workspaces", {}).values():
            all_cs = ws_data.get("changesets", [])
            window = find_event_window(all_cs, app_filter)
            if window:
                win_start, win_end = window
                filtered = [
                    cs
                    for cs in all_cs
                    if (t := _cs_time(cs)) is not None and win_start <= t <= win_end
                ]
                if len(filtered) != len(all_cs):
                    print(
                        f"  Window filter: {len(all_cs)} → {len(filtered)} changesets "
                        f"(ws {ws_data.get('id', '?')}, "
                        f"{win_start.strftime('%Y-%m-%d %H:%M')}–{win_end.strftime('%H:%M')} UTC)"
                    )
                ws_data["changesets"] = filtered

    workspaces = data.get("workspaces", {})

    if workspace_title:
        for ws_data in workspaces.values():
            ws_data["title"] = workspace_title

    fallback_date = data.get("date", date.today().isoformat())
    tz = data.get("tz")
    ws_dates = {
        ws_id: _ws_event_date(ws_data, fallback_date, tz)
        for ws_id, ws_data in workspaces.items()
    }
    # Archives that lack dated changesets contain empty summary dates. We drop
    # falsy entries to ensure the Unknown-date fallback below remains
    # reachable.
    unique_dates = sorted({d for d in ws_dates.values() if d})
    multiple_dates = len(unique_dates) > 1

    # We determine the header date range by examining timestamps from rendered
    # changesets.
    all_cs_dates = [
        _local_date_str(cs["created_at"], tz)
        for ws_data in workspaces.values()
        for cs in ws_data.get("changesets", [])
        if cs.get("created_at")
    ]
    if all_cs_dates:
        min_d = date.fromisoformat(min(all_cs_dates))
        max_d = date.fromisoformat(max(all_cs_dates))
        report_date_str = (
            format_date(min_d) if min_d == max_d else format_date_range(min_d, max_d)
        )
    elif unique_dates:
        report_date_str = format_date(date.fromisoformat(unique_dates[0]))
    else:
        report_date_str = "Unknown date"

    merged_index: dict = {}
    merged_choices: dict = {}
    for ws_data in workspaces.values():
        merged_index.update(build_quest_index(ws_data.get("quest_definition")))
        merged_choices.update(build_choices_index(ws_data.get("quest_definition")))

    _ctr = [0]  # tracks unique group-IDs across all sections

    section_tmpl = _env.get_template("section.html.j2")

    # We render the All Workspaces combined section only when multiple
    # workspaces exist.
    body = ""
    if len(workspaces) > 1:
        all_changesets = [
            cs for ws in workspaces.values() for cs in ws.get("changesets", [])
        ]
        combined_notes: list | None = None
        if any(w.get("notes") is not None for w in workspaces.values()):
            combined_notes = [
                n for w in workspaces.values() for n in (w.get("notes") or [])
            ]
        combined_issues = [
            i for ws in workspaces.values() for i in (ws.get("issues") or [])
        ]
        combined_hotspots = [
            h for ws in workspaces.values() for h in (ws.get("hotspots") or [])
        ]
        combined_coverage = _merge_dim_coverage(
            [
                ws.get("issue_meta", {}).get("dimension_coverage")
                for ws in workspaces.values()
            ]
        )
        ctx = _build_section_context(
            "All Workspaces",
            all_changesets,
            merged_index,
            merged_choices,
            combined_notes,
            None,
            _ctr,
            issues=combined_issues,
            show_positive=show_positive,
            dim_coverage=combined_coverage,
            hotspots=combined_hotspots,
        )
        body = section_tmpl.render(**ctx)

    workspace_names = []
    for ws_id_str, ws_data in workspaces.items():
        title = ws_data.get("title", f"Workspace {ws_id_str}")
        workspace_names.append(title)
        changesets = ws_data.get("changesets", [])
        idx = build_quest_index(ws_data.get("quest_definition")) or merged_index
        choices_idx = (
            build_choices_index(ws_data.get("quest_definition")) or merged_choices
        )
        notes = ws_data.get("notes")
        ws_issues = ws_data.get("issues")
        ws_hotspots = ws_data.get("hotspots")
        ws_dim_coverage = (ws_data.get("issue_meta") or {}).get("dimension_coverage")
        ws_formatted_date = (
            format_date(date.fromisoformat(ws_dates[ws_id_str]))
            if multiple_dates
            else None
        )
        ctx = _build_section_context(
            title,
            changesets,
            idx,
            choices_idx,
            notes,
            ws_formatted_date,
            _ctr,
            issues=ws_issues,
            show_positive=show_positive,
            dim_coverage=ws_dim_coverage,
            hotspots=ws_hotspots,
        )
        body += section_tmpl.render(**ctx)

    page_tmpl = _env.get_template("page.html.j2")
    html = page_tmpl.render(
        date=report_date_str,
        workspaces=Markup(" &nbsp;·&nbsp; ").join(workspace_names),
        css=_CSS,
        body=body,
        modal=_GALLERY_MODAL,
        js=_GALLERY_JS,
        report_title=report_title or DEFAULT_REPORT_TITLE,
    )
    out_file.write_text(html)
    print(f"\nReport written to {out_file}")
