"""This module constructs road intersection graphs to facilitate one-hop
connectivity propagation.

Public API
----------
build_intersection_graph(ways)

    maps each named-intersection node to all block faces incident to it
    (used for one-hop connectivity propagation)

The geometry helpers defined here are module-private. The :mod:`.overpass`
module re-exports the graph builder and employs these primitives to associate
points with segments.
"""

import math


def build_intersection_graph(ways: list[dict]) -> dict[int, list[dict]]:
    """Maps named intersections to their adjacent block faces as
    ``{node_id: [block_face_info, ...]}``.

    We define an intersection node as any node shared across two or more
    distinct named ways. Each `block_face_info` dictionary represents a block
    face ending at that node:

      way_id        int
      from_idx      int   geometry index of the block-face start
      to_idx        int   geometry index of the block-face end
      name          str   road name
      geometry      [[lat,lon],...]
      label         str   human-readable span label (no side)
      cross_streets list

    The connectivity-propagation step in *issues.py* uses this graph to
    identify all block faces touching a connectivity barrier.
    """
    if not ways:
        return {}

    graph: dict[int, list[dict]] = {}

    for way in ways:
        node_ids = way.get("node_ids", [])
        if not node_ids:
            continue
        intersection_indices = _find_intersection_indices(way, ways)
        if not intersection_indices:
            continue

        sorted_ints = sorted(set(intersection_indices))

        # We identify every block-face span between named intersections.
        #
        # We include 0 and the final index as implicit boundaries so the
        # segments at both the start and end of the way are represented.
        boundaries = sorted(set([0] + sorted_ints + [len(node_ids) - 1]))

        for i in range(len(boundaries) - 1):
            from_idx = boundaries[i]
            to_idx = boundaries[i + 1]

            geom = way["geometry"]
            block_geom = geom[from_idx : to_idx + 1]
            if len(block_geom) < 2:
                continue

            from_street = _cross_street_at(from_idx, way, ways)
            to_street = _cross_street_at(to_idx, way, ways)
            cross_streets = [s for s in [from_street, to_street] if s]

            name = way["name"]
            if from_street and to_street:
                label = f"{name} between {from_street} & {to_street}"
            elif from_street or to_street:
                label = f"{name} near {(from_street or to_street)}"
            else:
                label = name

            bf_info = {
                "way_id": way["id"],
                "from_idx": from_idx,
                "to_idx": to_idx,
                "name": name,
                "geometry": block_geom,
                "label": label,
                "cross_streets": cross_streets,
            }

            # We register only at intersection nodes, which means we skip way
            # endpoints that do not also function as intersections.
            for idx in [from_idx, to_idx]:
                if idx not in intersection_indices:
                    continue
                if idx >= len(node_ids):
                    continue
                nid = node_ids[idx]
                existing = graph.setdefault(nid, [])
                # We need to deduplicate entries that share the same `way_id`,
                # `from_idx`, and `to_idx`.
                if not any(
                    b["way_id"] == way["id"]
                    and b["from_idx"] == from_idx
                    and b["to_idx"] == to_idx
                    for b in existing
                ):
                    existing.append(bf_info)

    return graph


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _dist_m(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Computes an approximate distance in meters between two lat/lon points.
    """
    dlat = (p1[0] - p2[0]) * 111_000
    mid_lat = math.radians((p1[0] + p2[0]) / 2)
    dlon = (p1[1] - p2[1]) * 111_000 * math.cos(mid_lat)
    return math.sqrt(dlat * dlat + dlon * dlon)


def _project_point_to_segment(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> tuple[tuple[float, float], float]:
    """Returns a tuple containing the `projected_point` and a scalar t ∈ [0,1]
    representing the position along the segment a->b.
    """
    ax, ay = a[1], a[0]  # we treat lon as x and lat as y
    bx, by = b[1], b[0]
    px, py = p[1], p[0]
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-18:
        return a, 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    proj = (ay + t * dy, ax + t * dx)  # we return coordinates as (lat, lon)
    return proj, t


def _nearest_on_polyline(
    p: tuple[float, float],
    polyline: list[list[float]],
) -> tuple[tuple[float, float], int, float]:
    """Finds the closest point on a polyline and returns the `projected_point`,
    `segment_index`, and `distance_m`.
    """
    best_pt = (polyline[0][0], polyline[0][1])
    best_idx = 0
    best_dist = float("inf")
    for i in range(len(polyline) - 1):
        a = (polyline[i][0], polyline[i][1])
        b = (polyline[i + 1][0], polyline[i + 1][1])
        proj, _ = _project_point_to_segment(p, a, b)
        d = _dist_m(p, proj)
        if d < best_dist:
            best_dist = d
            best_pt = proj
            best_idx = i
    return best_pt, best_idx, best_dist


def _side_of_point(
    p: tuple[float, float],
    polyline: list[list[float]],
    seg_idx: int,
) -> str:
    """Determines whether a point lies on a relative or cardinal side of a road.

    We use the sign of the cross-product to identify if a point is left or
    right, which we then map to a cardinal direction based on the road segment
    bearing.
    """
    if seg_idx >= len(polyline) - 1:
        seg_idx = max(0, len(polyline) - 2)
    a = polyline[seg_idx]
    b = polyline[seg_idx + 1]
    # We calculate the cross product of (b-a) and (p-a) using flat-earth
    # coordinates.
    dx_road = b[1] - a[1]
    dy_road = b[0] - a[0]
    dx_pt = p[1] - a[1]
    dy_pt = p[0] - a[0]
    cross = dx_road * dy_pt - dy_road * dx_pt
    # We calculate the road bearing as degrees clockwise from north.
    bearing = math.degrees(math.atan2(dx_road, dy_road)) % 360
    # We determine if a point sits left or right of the road direction from A
    # to B by checking if cross > 0. We then use the bearing to translate that
    # side into a cardinal direction.
    if 45 <= bearing < 135:
        return "north" if cross > 0 else "south"
    elif 135 <= bearing < 225:
        return "east" if cross > 0 else "west"
    elif 225 <= bearing < 315:
        return "south" if cross > 0 else "north"
    else:
        return "west" if cross > 0 else "east"


def _find_intersection_indices(
    way: dict,
    all_ways: list[dict],
) -> list[int]:
    """Returns indices into `way['geometry']` where named cross-streets intersect.

    We identify an intersection candidate by checking if its node ID exists in
    any other named way. When `node_ids` are available, we use them; otherwise,
    we fall back to spatial proximity if Overpass didn't return them.
    """
    own_node_ids = way.get("node_ids", [])
    own_id = way["id"]

    if own_node_ids:
        # We collect node IDs from every named way except the one with our own
        # ID.
        other_node_ids: set[int] = set()
        for w in all_ways:
            if w["id"] == own_id:
                continue
            other_node_ids.update(w.get("node_ids", []))
        return [
            i for i, nid in enumerate(own_node_ids)
            if nid in other_node_ids
        ]

    # We use a spatial fallback to identify nodes within roughly 12 m of any
    # other way's geometry.
    intersection_indices = []
    own_geom = way["geometry"]
    for i, node in enumerate(own_geom):
        for w in all_ways:
            if w["id"] == own_id:
                continue
            _, _, d = _nearest_on_polyline((node[0], node[1]), w["geometry"])
            if d < 12:
                intersection_indices.append(i)
                break
    return intersection_indices


def _block_face(
    way: dict,
    proj: tuple[float, float],
    intersection_indices: list[int],
    all_ways: list[dict],
) -> tuple[list[list[float]], str | None, str | None, int | None, int | None]:
    """Returns a tuple containing `block_face_geometry`, `from_street_name`,
    `to_street_name`, `from_idx`, and `to_idx`.

    We identify which pair of intersection indices brackets the projected point
    and retrieve the cross-street name for those indices.
    """
    geom = way["geometry"]
    if not intersection_indices or len(geom) < 2:
        return geom, None, None, None, None

    # We find the position index by projecting the projection point onto the
    # way.
    _, proj_seg_idx, _ = _nearest_on_polyline(proj, geom)
    proj_node_idx = proj_seg_idx  # we use the segment's start node

    sorted_ints = sorted(set(intersection_indices))

    # We'll need to identify the bracketing pair.
    from_idx: int | None = None
    to_idx: int | None = None
    for idx in sorted_ints:
        if idx <= proj_node_idx:
            from_idx = idx
        if idx > proj_node_idx and to_idx is None:
            to_idx = idx

    if from_idx is None and to_idx is None:
        return geom, None, None, None, None

    # Extract block-face geometry
    start = from_idx if from_idx is not None else 0
    end = (to_idx + 1) if to_idx is not None else len(geom)
    block_geom = geom[start:end]
    if len(block_geom) < 2:
        block_geom = geom

    # We identify names for cross-streets.
    from_street = _cross_street_at(from_idx, way, all_ways) if from_idx is not None else None
    to_street = _cross_street_at(to_idx, way, all_ways) if to_idx is not None else None

    return block_geom, from_street, to_street, from_idx, to_idx


def _cross_street_at(
    node_idx: int,
    way: dict,
    all_ways: list[dict],
) -> str | None:
    """Returns the cross-street name at a specific node index for the given *way*.

    First, we check if the node index exists within the `node_ids` of the
    *way*. If it does, we search `all_ways` for any element that contains that
    same node ID and has a different `id` and `name` than the original *way*.
    When we find such a match, we return its `name`.

    If that fails, we use a spatial fallback to find the closest named way node
    at that position. When the node index is within the bounds of the
    `geometry` list, we calculate the distance from that point to each other
    *way* in `all_ways` (excluding those with the same `id` or `name`). We
    return the `name` of the closest *way* if its distance is small enough.
    """
    own_node_ids = way.get("node_ids", [])
    own_id = way["id"]
    own_name = way.get("name", "")

    if own_node_ids and node_idx < len(own_node_ids):
        target_nid = own_node_ids[node_idx]
        for w in all_ways:
            if w["id"] == own_id:
                continue
            # We skip segments of the same road because OSM ways may split a
            # single road across multiple entries.
            if w.get("name") == own_name:
                continue
            if target_nid in (w.get("node_ids") or []):
                return w["name"]

    # We fall back to a spatial approach when we need the name of the closest
    # node on a way relative to this position.
    if node_idx < len(way["geometry"]):
        node_pos = (way["geometry"][node_idx][0], way["geometry"][node_idx][1])
        best_name = None
        best_d = float("inf")
        for w in all_ways:
            if w["id"] == own_id:
                continue
            if w.get("name") == own_name:
                continue
            _, _, d = _nearest_on_polyline(node_pos, w["geometry"])
            if d < 15 and d < best_d:
                best_d = d
                best_name = w["name"]
        return best_name
    return None
