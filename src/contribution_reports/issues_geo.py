"""Geometry utility functions for the issue pipeline.

We can use these helpers to cluster orphan evidence points by distance, group
block faces while respecting side via a passed locator function, and propagate
connectivity-barrier scores a single hop across intersection nodes.
"""

import math

from .constants import CONNECTIVITY_DECAY

# A dimension-specific score counts as a connectivity barrier when it falls
# below this threshold.
_CONN_BARRIER_THRESHOLD = -0.1
# Evidence counts as relevant when it falls within this distance (meters) from
# a propagation node.
#
# This prevents false positives--such as those seen on K-Street--where we might
# otherwise pick up quests located one block away.
_MAX_NODE_EVIDENCE_DIST = 60

def _dist_m(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    dlat = (p1[0] - p2[0]) * 111_000
    mid_lat = math.radians((p1[0] + p2[0]) / 2)
    dlon = (p1[1] - p2[1]) * 111_000 * math.cos(mid_lat)
    return math.sqrt(dlat * dlat + dlon * dlon)


def _cluster_points(
    points: list[dict], radius_m: float
) -> list[list[dict]]:
    """Performs greedy single-linkage clustering on orphan points.

    We assign each point to the first cluster with a centroid within *radius_m*
    meters. If no existing cluster fits, we start a new cluster for that point.
    """
    clusters: list[list[dict]] = []
    centroids: list[tuple[float, float]] = []

    for pt in points:
        pos = (pt["lat"], pt["lon"])
        assigned = False
        for i, centroid in enumerate(centroids):
            if _dist_m(pos, centroid) <= radius_m:
                clusters[i].append(pt)
                lats = [p["lat"] for p in clusters[i]]
                lons = [p["lon"] for p in clusters[i]]
                centroids[i] = (sum(lats) / len(lats), sum(lons) / len(lons))
                assigned = True
                break
        if not assigned:
            clusters.append([pt])
            centroids.append(pos)

    return clusters

def _group_by_segment(
    all_points: list[dict],
    ways: list[dict],
    locate_fn,
) -> tuple[dict, list[dict]]:
    """Groups scored points using a key composed of road, block-face span, and
    side.

    We use *locate_fn* (= overpass.locate_point) on each point to identify its
    side and nearest block face. If a point lacks a match, we return it as an
    orphan to allow for distance-based fallback clustering.

    Returns `(groups, orphans)` where:
      groups   dict keyed by the locate_fn ``key`` field;
               each value is ``{"points": [...], "segment": segment_dict}``
      orphans  list of unmatched points
    """
    groups: dict = {}
    orphans: list[dict] = []

    for pt in all_points:
        seg = locate_fn((pt["lat"], pt["lon"]), ways)
        if seg is None:
            orphans.append(pt)
            continue
        key = seg["key"]
        if key not in groups:
            groups[key] = {"points": [], "segment": seg}
        groups[key]["points"].append(pt)

    return groups, orphans

def _segment_centroid(geometry: list) -> list[float]:
    if not geometry:
        return [0.0, 0.0]
    lats = [g[0] for g in geometry]
    lons = [g[1] for g in geometry]
    return [round(sum(lats) / len(lats), 6), round(sum(lons) / len(lons), 6)]


def _propagate_connectivity(
    scored_groups: list[dict],
    intersection_graph: dict,
) -> list[dict]:
    """Creates derived issues for block faces that touch connectivity barriers.

    For scored groups with a negative `conn_score`, we locate their incident
    intersection nodes. We only consider evidence points within
    `_MAX_NODE_EVIDENCE_DIST` meters of each node to be relevant. This keeps a
    long block face from propagating through its far endpoint via evidence
    gathered at the opposite end.

    If multiple barriers reach the same target block face, the barrier with the
    most negative `conn_score` wins, as the strongest barrier takes precedence.

    We return a list of new issue dictionaries to add to `scored_groups`.
    """
    # We use this set to track which (way_id, from_idx, to_idx) combinations
    # already have direct evidence.
    existing_keys: set = set()
    for sg in scored_groups:
        sk = sg.get("_segment_key")
        if sk:
            existing_keys.add(sk[:3])   # drop side

    # We identify the best propagation candidate for each block face by
    # selecting the most negative `conn_score`. The `pending` dictionary maps
    # each `bf_key` to a set containing `conn_score`, `source_pts`,
    # `barrier_label`, and `bf_info`.
    pending: dict = {}

    for sg in scored_groups:
        conn_score = sg.get("conn_score")
        if conn_score is None or conn_score >= _CONN_BARRIER_THRESHOLD:
            continue

        barrier_geom = sg["segment"].get("geometry", [])
        all_pts = sg.get("points", [])

        for node_id, node_pos in [
            (sg.get("_from_node_id"), barrier_geom[0] if barrier_geom else None),
            (sg.get("_to_node_id"),   barrier_geom[-1] if barrier_geom else None),
        ]:
            if node_id is None or node_pos is None:
                continue

            # We filter for evidence collected near this specific node.
            #
            # This prevents K-Street-style false positives, because a barrier's
            # far endpoint might otherwise propagate using evidence from the
            # opposite end.
            node_latlon = (node_pos[0], node_pos[1])
            nearby_pts = [
                p for p in all_pts
                if _dist_m((p["lat"], p["lon"]), node_latlon) <= _MAX_NODE_EVIDENCE_DIST
                and (
                    "connectivity" in (p.get("dim_weights") or {})
                    or p.get("kind") == "note"
                )
            ]
            if not nearby_pts:
                continue  # we skip intersections that lack relevant evidence

            propagated = round(conn_score * CONNECTIVITY_DECAY, 3)
            barrier_label = (
                sg["segment"].get("label") or sg["segment"].get("name", "nearby")
            )

            for bf_info in intersection_graph.get(node_id, []):
                bf_key = (bf_info["way_id"], bf_info["from_idx"], bf_info["to_idx"])
                if bf_key in existing_keys:
                    continue
                # We store the barrier with the most negative connection score
                # for each block face.
                if bf_key not in pending or propagated < pending[bf_key]["conn_score"]:
                    pending[bf_key] = {
                        "conn_score": propagated,
                        "source_pts": nearby_pts,
                        "barrier_label": barrier_label,
                        "bf_info": bf_info,
                    }

    derived: list[dict] = []
    for bf_key, entry in pending.items():
        source_pts = entry["source_pts"]
        bf_info    = entry["bf_info"]
        propagated = entry["conn_score"]

        derived.append({
            "combined_score": propagated,
            "quest_score": None,
            "note_score": None,
            "trav_score": None,
            "conn_score": propagated,
            "safety_score": None,
            "centroid": _segment_centroid(bf_info.get("geometry", [])),
            "quest_count": sum(1 for p in source_pts if p.get("kind") == "quest"),
            "note_count": sum(1 for p in source_pts if p.get("kind") == "note"),
            "segment": {
                "name": bf_info["name"],
                "side": "nearby",
                "cross_streets": bf_info.get("cross_streets", []),
                "geometry": bf_info.get("geometry", []),
                "way_id": bf_info["way_id"],
                "label": bf_info["label"],
            },
            "points": source_pts,
            "derived": True,
            "derived_from": f"connectivity barrier at {entry['barrier_label']}",
            "confidence": 0.25,
            "conf_quantity": 0.0,
            "conf_agreement": 0.5,
            "conf_corroboration": 0.3,
            "_from_node_id": None,
            "_to_node_id": None,
            "_segment_key": None,
        })

    return derived
