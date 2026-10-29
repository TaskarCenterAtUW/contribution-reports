"""Context builders that transform cached data into Jinja template contexts."""

from .analysis import analyse, count_created_features, count_questions
from .classify import split_note_photos
from .constants import (
    DIMENSION_LABELS,
    DIMENSIONS,
    ELEMENT_TYPE_ORDER,
    TEAM_LABELS,
)
from .markers import build_created_markers, build_map_markers
from .popup import _map_choice_value
from .render_mapdata import (
    _build_hotspots_map_data,
    _build_issues_map_data,
    _split_evidence_photos,
)
from .segments import format_segment_ref


def _build_q_breakdown(
    q_counts: dict,
    quest_index: dict,
    choices_index: dict,
    _ctr: list,
) -> list[dict]:
    """Transforms question-count data into a list of dictionaries for use in a
    Jinja template.

    We follow the group-ID and ordering logic from the original
    `question_breakdown_html()` function to maintain compatibility with
    accordion JS. To keep `qd-N` group IDs unique across a full rendered page,
    we share the mutable `_ctr` list among all sections.
    """
    if not q_counts:
        return []

    ordered = [e for e in ELEMENT_TYPE_ORDER if e in q_counts]
    ordered += [e for e in q_counts if e not in ELEMENT_TYPE_ORDER]

    result = []
    for etype in ordered:
        tag_counts = q_counts[etype]
        if not tag_counts:
            continue
        total = sum(sum(vd.values()) for vd in tag_counts.values())
        max_val = max(sum(vd.values()) for vd in tag_counts.values())
        questions = []
        for tag, val_counts in sorted(
            tag_counts.items(), key=lambda x: -sum(x[1].values())
        ):
            count = sum(val_counts.values())
            title = quest_index.get(tag, {}).get("title", tag)
            val_max = max(val_counts.values())
            choices = (choices_index or {}).get(tag, {})
            group_id = f"qd-{_ctr[0]}"
            _ctr[0] += 1
            values = []
            for v, c in sorted(val_counts.items(), key=lambda x: -x[1]):
                if choices:
                    mapped = _map_choice_value(v, choices)
                    display_choice = mapped
                    display_label = v if mapped != v else ""
                else:
                    display_choice = v
                    display_label = ""
                values.append(
                    {
                        "value": v,
                        "count": c,
                        "val_max": val_max,
                        "display_choice": display_choice,
                        "display_label": display_label,
                    }
                )
            questions.append(
                {
                    "tag": tag,
                    "title": title,
                    "count": count,
                    "max_val": max_val,
                    "group_id": group_id,
                    "answer_values": values,
                }
            )
        result.append(
            {"etype": etype, "total": total, "max_val": max_val, "questions": questions}
        )
    return result


def _merge_dim_coverage(coverage_list: list[dict | None]) -> dict:
    """Merges dimension coverage from multiple workspaces for the "All Workspaces"
    section.

    We mark a dimension as covered if any workspace in the list provides
    coverage for it.
    """
    merged: dict = {}
    for dim in DIMENSIONS:
        tags = sum((c or {}).get(dim, {}).get("tags", 0) for c in coverage_list)
        points = sum((c or {}).get(dim, {}).get("points", 0) for c in coverage_list)
        covered = any(
            (c or {}).get(dim, {}).get("covered", False) for c in coverage_list
        )
        merged[dim] = {"tags": tags, "points": points, "covered": covered}
    return merged


def _build_section_context(
    title: str,
    changesets: list,
    quest_index: dict,
    choices_index: dict,
    notes: list | None,
    formatted_date: str | None,
    _ctr: list,
    issues: list | None = None,
    show_positive: bool = True,
    dim_coverage: dict | None = None,
    hotspots: list | None = None,
) -> dict:
    """Generates a Jinja context dictionary containing all required data for a
    single report section.

    We gather stats via `analyse`, question counts through `count_questions`
    (assuming `quest_index` exists), and feature creation totals with
    `count_created_features`. Map data combines output from `build_map_markers`
    and `build_created_markers`, which we supplement with note data processed
    by `split_note_photos`. We then produce a question breakdown using
    `_build_q_breakdown`.

    For the issues panels, we process each entry with `_split_evidence_photos`.
    We annotate these with a `seg_ref` via `format_segment_ref` and assign a
    per-section `seg_uid` to link table rows to map layers. These entries split
    into `problems` (where `sign` is `"problem"`) and `good_segments` (where
    `sign` is `"good"`, provided `show_positive` is true). We generate the
    remaining map data with `_build_issues_map_data`.

    We also build a dimension coverage summary from `dim_coverage` using
    `DIMENSIONS` and `DIMENSION_LABELS`. For each dimension, we record its key,
    label, tag count, and whether it is covered (which we default to true for
    old caches). This lets the template show a "not assessed" note or omit
    uncovered columns.

    Finally, we process hotspots with `_split_evidence_photos`, assign each a
    `hs_uid`, and extract unique photo URLs from `evidence_points`. The final
    map data for these entries comes from `_build_hotspots_map_data`.
    """
    stats = analyse(changesets, quest_index, notes)
    q_counts = count_questions(changesets, quest_index) if quest_index else {}
    created = count_created_features(changesets, quest_index)
    markers = build_map_markers(changesets, quest_index, choices_index)
    created_markers = build_created_markers(changesets, quest_index)

    all_map_data: list[dict] = list(markers) + list(created_markers)
    for n in notes or []:
        text, photos = split_note_photos(n.get("text", ""))
        all_map_data.append(
            {
                "lat": n["lat"],
                "lon": n["lon"],
                "kind": "note",
                "text": text,
                "user": n.get("user"),
                "photos": photos,
            }
        )

    q_breakdown = _build_q_breakdown(q_counts, quest_index, choices_index, _ctr)

    # Issues panels
    all_issues = [_split_evidence_photos(i) for i in (issues or [])]
    # We attach a structured `seg_ref` to each issue during rendering without
    # making API calls. We also assign a per-section UID to connect table rows
    # with map layers.
    for i, iss in enumerate(all_issues):
        iss["seg_ref"] = format_segment_ref(iss.get("segment", {}))
        iss["seg_uid"] = i
    problems = [i for i in all_issues if i.get("sign") == "problem"]
    good_segments = (
        [i for i in all_issues if i.get("sign") == "good"] if show_positive else []
    )
    all_issues_data = _build_issues_map_data(all_issues, show_positive)

    # We generate dimension coverage summaries for the template. This provides
    # a label and a `covered` boolean for each dimension, which lets the
    # template hide uncovered columns and display a note that they were not
    # assessed.
    dim_cov_info: list[dict] = []
    for dim in DIMENSIONS:
        cov = (dim_coverage or {}).get(dim, {})
        dim_cov_info.append(
            {
                "key": dim,
                "label": DIMENSION_LABELS[dim],
                "covered": cov.get("covered", True),  # default True for old caches
                "tags": cov.get("tags", 0),
            }
        )

    # Hotspots panel
    all_hotspots = [_split_evidence_photos(h) for h in (hotspots or [])]
    for i, h in enumerate(all_hotspots):
        h["hs_uid"] = i
        h["photos"] = list(
            dict.fromkeys(
                url for p in h.get("evidence_points", []) for url in p.get("photos", [])
            )
        )
    all_hotspots_data = _build_hotspots_map_data(all_hotspots)

    return {
        "title": title,
        "formatted_date": formatted_date,
        "stats": stats,
        "q_breakdown": q_breakdown,
        "created": created,
        "all_map_data": all_map_data,
        "notes_count": len(notes) if notes is not None else 0,
        "team_labels": TEAM_LABELS,
        # Issues
        "problems": problems,
        "good_segments": good_segments,
        "all_issues_data": all_issues_data,
        "show_positive": show_positive,
        "has_issues": bool(all_issues),
        "dim_coverage": dim_cov_info,
        # Hotspots
        "hotspots": all_hotspots,
        "all_hotspots_data": all_hotspots_data,
        "has_hotspots": bool(all_hotspots),
    }
