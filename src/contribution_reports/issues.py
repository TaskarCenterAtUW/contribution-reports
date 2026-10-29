"""Infrastructure issue inference pipeline.

We coordinate LLM and geometry operations through these steps:
1. Quest rubric: we use a single LLM call per workspace to map (tag, value)
   pairs to dimension(s) and a signed weight.
2. Note scoring: we score and filter notes via a single batched LLM call per
   workspace to classify dimensions.
3. Road fetch: we perform one Overpass call covering the entire evidence bbox.
4. Side-aware grouping: we assign evidence points to keys containing a side,
   block-face span, and road; points that are co-located on one side of a
   single block form a group. We use distance-based clustering when points
   cannot match a named road.
5. Dimension scoring: we rank groups by a weighted combined score derived from
   separate safety/comfort, connectivity, and traversability scores.
6. Propagation: we materialize "derived" (inferred) issues by propagating
   connectivity barriers near intersection nodes one decayed hop onto adjacent
   block faces that lack direct evidence.
7. Summaries: we make one LLM call for each of the top-N issues.

We store all results in `ws_data["issues"]` and `ws_data["issue_meta"]` so
`--cached` works without repeating API calls.

If we pass `llm=None`, the module prints a warning and returns [].
"""

import sys
from typing import TYPE_CHECKING

from .constants import SEVERITY_SIGN_THRESHOLD
from .issues_evidence import _attach_issue_evidence, _build_note_points
from .issues_geo import _cluster_points, _group_by_segment, _propagate_connectivity
from .issues_parse import _build_rubric
from .issues_points import _extract_quest_points
from .issues_score import (
    _compute_dimension_coverage,
    _empty_meta,
    _generate_summary,
    _score_group,
    _score_notes,
)

# These names have no references later in this file. The `hotspots.py` module
# imports them locally within functions so we can avoid a circular import with
# `hotspots`.
from .issues_parse import _normalise_dims
from .issues_score import _compute_confidence

if TYPE_CHECKING:
    from .llm import LLMClient

# We generate one-line summaries for this many top issues.
_SUMMARY_TOP_N = 10
# We use this radius in meters to cluster orphan points that lack a road match.
_CLUSTER_RADIUS_M = 50
# We require at least this many evidence pieces before a cluster appears in the
# ranked panel.
_MIN_CLUSTER_SIZE = 1

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def infer_issues(
    ws_data: dict,
    llm: "LLMClient | None",
    overpass_url: str | None = None,
    overpass_token: str | None = None,
) -> list[dict]:
    """Executes the complete inference pipeline to produce a list of issues.

    We store findings in `ws_data["issues"]` and metadata in
    `ws_data["issue_meta"]` before the function returns. If we encounter a
    fatal error, we log a warning and return [].
    """
    if llm is None:
        print("  [issues] Skipping inference because no Anthropic API key "
                  "exists", file=sys.stderr)
        ws_data["issues"] = []
        ws_data["hotspots"] = []
        ws_data["issue_meta"] = _empty_meta()
        return []

    from .overpass import (
        DEFAULT_OVERPASS_URL,
        build_intersection_graph,
        fetch_roads_near_points,
        locate_point,
    )

    ov_url = overpass_url or DEFAULT_OVERPASS_URL
    quest_def = ws_data.get("quest_definition")
    changesets = ws_data.get("changesets", [])
    notes = ws_data.get("notes", []) or []

    # We'll generate the quest severity rubric using an LLM. The code
    # implements this as step 1.
    rubric_map: dict = {}
    if quest_def:
        print("  [issues] Generating quest severity rubric with LLM...")
        try:
            rubric_map = _build_rubric(llm, quest_def)
            print(f"  [issues] Rubric contains {len(rubric_map)} quest tags")
            ws_data["_rubric"] = rubric_map  # persist for offline inspection
        except Exception as exc:
            print(f"  WARNING: Could not generate rubric: {exc}", file=sys.stderr)

    # Step 2 extracts and scores quest points.
    quest_points = _extract_quest_points(changesets, rubric_map)
    print(f"  [issues] extracted {len(quest_points)} quest data points")

    # We'll now start step 3 to score notes.
    scored_notes: list[dict] = []
    if notes:
        print(f"  [issues] Scoring {len(notes)} notes with LLM...")
        try:
            scored_notes = _score_notes(llm, notes)
            relevant = sum(1 for n in scored_notes if n.get("is_relevant"))
            print(
                f"  [issues] {relevant} / {len(scored_notes)} notes concern "
                    "infrastructure"
            )
            ws_data["_scored_notes"] = scored_notes
        except Exception as exc:
            print(f"  WARNING: could not score notes: {exc}", file=sys.stderr)
            scored_notes = []

    note_points = _build_note_points(scored_notes)

    all_points = quest_points + note_points

    # We identify consensus hotspots through pure spatial clustering without
    # using Overpass or LLMs.
    from .hotspots import compute_hotspots as _compute_hotspots

    ws_data["hotspots"] = _compute_hotspots(quest_points, note_points)
    print(f"  [hotspots] {len(ws_data['hotspots'])} consensus hotspots found")

    # We compute dimension coverage here as part of step 4.
    coverage = _compute_dimension_coverage(rubric_map, all_points)
    ws_data["issue_meta"] = {"dimension_coverage": coverage}
    print(
        "  [issues] Dimension coverage: "
        + ", ".join(
            f"{d}={'yes' if v['covered'] else 'no'} ({v['tags']} tags, {v['points']} pts)"
            for d, v in coverage.items()
        )
    )

    if not all_points:
        print("  [issues] No scored data points, so cluster and segment "
                  "steps are skipped")
        ws_data["issues"] = []
        return []

    # We fetch roads from Overpass once for the complete set of evidence points
    # (step 5).
    all_latlons = [(p["lat"], p["lon"]) for p in all_points]
    print(
        f"  [issues] Fetching roads near {len(all_latlons)} evidence points "
            "with Overpass"
    )
    ways = fetch_roads_near_points(
        all_latlons, overpass_url=ov_url, overpass_token=overpass_token
    )
    print(f"  [issues] {len(ways)} named roads returned from Overpass")

    # We group evidence by block-face segments to associate it with the
    # appropriate side (6).
    if ways:
        print("  [issues] Associating evidence with block-face segments...")
        groups, orphans = _group_by_segment(all_points, ways, locate_point)
        print(
            f"  [issues] {len(groups)} named block-face groups and "
                f"{len(orphans)} orphan points"
        )
    else:
        groups, orphans = {}, list(all_points)

    # We score every named-segment group.
    scored_groups: list[dict] = []
    for grp in groups.values():
        if not grp["points"]:
            continue
        sg = _score_group(grp["points"], grp["segment"])
        scored_groups.append(sg)

    # We cluster orphan points using distance because they lacked a road match.
    if orphans:
        orphan_clusters = _cluster_points(orphans, _CLUSTER_RADIUS_M)
        for cluster in orphan_clusters:
            if len(cluster) < _MIN_CLUSTER_SIZE:
                continue
            from .overpass import _unknown_segment

            seg = _unknown_segment()
            seg["from_node_id"] = None  # type: ignore[index]
            seg["to_node_id"] = None  # type: ignore[index]
            seg["key"] = None  # type: ignore[index]
            sg = _score_group(cluster, seg)
            scored_groups.append(sg)

    print(
        f"  [issues] {len(scored_groups)} scored groups before the evidence "
            "filter"
    )

    # We filter for minimum evidence, though we keep derived issues that have 0
    # direct evidence.
    scored_groups = [
        sg
        for sg in scored_groups
        if sg.get("derived")
        or (sg["quest_count"] + sg["note_count"] >= _MIN_CLUSTER_SIZE)
    ]

    # We sort by the absolute combined score in descending order so that the
    # most extreme groups appear first.
    scored_groups.sort(key=lambda x: abs(x["combined_score"]), reverse=True)

    if not scored_groups:
        print("  [issues] No groups met the minimum evidence threshold")
        ws_data["issues"] = []
        return []

    # We propagate connectivity across a single hop (7).
    if ways:
        intersection_graph = build_intersection_graph(ways)
        derived = _propagate_connectivity(scored_groups, intersection_graph)
        if derived:
            print(f"  [issues] {len(derived)} derived connectivity issues")
            scored_groups.extend(derived)

    # We assign signs and ranks below in step 8.
    for sg in scored_groups:
        sg.setdefault("derived", False)
        sg.setdefault("derived_from", None)

    problems = sorted(
        [sg for sg in scored_groups if sg["combined_score"] < -SEVERITY_SIGN_THRESHOLD],
        key=lambda x: x["combined_score"] * x["confidence"],
    )
    good = sorted(
        [sg for sg in scored_groups if sg["combined_score"] > SEVERITY_SIGN_THRESHOLD],
        key=lambda x: x["combined_score"] * x["confidence"],
        reverse=True,
    )

    for i, sg in enumerate(problems, 1):
        sg["rank"] = i
        sg["sign"] = "problem"
    for i, sg in enumerate(good, 1):
        sg["rank"] = i
        sg["sign"] = "good"
    for sg in scored_groups:
        if "sign" not in sg:
            sg["sign"] = "neutral"
            sg["rank"] = 0

    # 9. Summaries for top-N issues
    #
    # We'll take a slice of both problems and good issues based on the
    # _SUMMARY_TOP_N limit to generate summaries.
    top_for_summary = problems[:_SUMMARY_TOP_N] + good[:_SUMMARY_TOP_N]
    if top_for_summary:
        print(
            f"  [issues] Generating summaries for {len(top_for_summary)} top "
                "segments..."
        )

    for sg in top_for_summary:
        if sg.get("derived"):
            # We use static text for issues marked as derived so we don't make
            # additional LLM calls.
            barrier = sg.get("derived_from") or "a nearby connectivity barrier"
            sg["summary"] = f"Possible connectivity gap — {barrier}."
            continue
        try:
            sg["summary"] = _generate_summary(llm, sg)
        except Exception as exc:
            print(f"  WARNING: Could not generate summary: {exc}", file=sys.stderr)
            sg["summary"] = sg["segment"].get("label", sg["segment"].get("name", ""))

    for sg in scored_groups:
        if "summary" not in sg:
            sg["summary"] = sg["segment"].get("label", sg["segment"].get("name", ""))

    # We extract evidence and perform cleanup in step 10.
    issues = problems + good + [sg for sg in scored_groups if sg["sign"] == "neutral"]

    _attach_issue_evidence(issues)

    ws_data["issues"] = issues
    print(f"  [issues] Found {len(problems)} problems and {len(good)} good "
              "segments")
    return issues
