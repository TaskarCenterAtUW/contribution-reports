"""An Overpass API client that retrieves named road geometry near survey hotspots.

Public API
----------
fetch_roads_near_points(points, radius_m, overpass_url, overpass_token)
    returns a list of way dicts containing geometry and intersection-node metadata

locate_point(point, ways)
    returns a full segment dict with a hashable key and incident node IDs
    (used for side-aware block-face grouping in issues.py)

build_intersection_graph(ways)
    returns {node_id: [block_face_info, ...]}
    maps each named-intersection node to all incident block faces
    (used for one-hop connectivity propagation)

The block-face algorithm:
  1. Build a node to way_ids membership map from the fetched ways.
  2. Any node appearing in two or more distinct *named* ways qualifies as an
     intersection.
  3. We take the way closest to the centroid and chop its geometry at these
     intersection nodes to create block-face segments.
  4. We project the centroid onto the nearest segment and use a cross-product
     to identify which side it falls on.
  5. We fall back to the full way name and side if we cannot identify a valid
     block-face (because of ambiguous geometry or no named cross-streets).
"""

import json
import math
import sys

from .net import http_post_form
from .overpass_graph import (
    _block_face,
    _find_intersection_indices,
    _nearest_on_polyline,
    _side_of_point,
    build_intersection_graph,
)

DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_RADIUS_M = 250

# We treat these highway values as named roads to determine block faces.
_ROAD_HIGHWAY_RE = (
    "primary|secondary|tertiary|residential|unclassified|service|living_street"
)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_roads_near_points(
    points: list[tuple[float, float]],
    radius_m: float = DEFAULT_RADIUS_M,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    overpass_token: str | None = None,
) -> list[dict]:
    """Retrieves named highway ways, including node IDs and geometry, located near
    *points*.

    If we provide an *overpass_token*, the client includes it as a Bearer token
    to authenticate with mirrors.

    We get an empty list when Overpass returns an error, so the caller can
    degrade gracefully.
    """
    if not points:
        return []

    min_lat, min_lon, max_lat, max_lon = _bbox_from_points(points, radius_m)
    bbox = f"{min_lat:.6f},{min_lon:.6f},{max_lat:.6f},{max_lon:.6f}"

    query = (
        f"[out:json][timeout:30];\n"
        f'way["highway"~"^({_ROAD_HIGHWAY_RE})$"]["name"]({bbox});\n'
        f"out body geom;"
    )

    headers = {"User-Agent": "TDEI-Workspaces-Reports/1.0"}
    if overpass_token:
        headers["Authorization"] = f"Bearer {overpass_token}"
    try:
        raw = http_post_form(overpass_url, {"data": query}, headers=headers)
        result = json.loads(raw)
    except Exception as exc:
        print(f"WARNING: Overpass query failed: {exc}", file=sys.stderr)
        return []

    ways = []
    for el in result.get("elements", []):
        if el.get("type") != "way":
            continue
        name = (el.get("tags") or {}).get("name", "").strip()
        if not name:
            continue
        geom_nodes = el.get("geometry", [])
        geom = [[n["lat"], n["lon"]] for n in geom_nodes if "lat" in n]
        node_ids = el.get("nodes", [])
        if len(geom) < 2:
            continue
        ways.append(
            {
                "id": el["id"],
                "name": name,
                "geometry": geom,
                "node_ids": node_ids,
                "tags": el.get("tags", {}),
            }
        )
    return ways


# ---------------------------------------------------------------------------
# Segment Association Public API.
# ---------------------------------------------------------------------------


def locate_point(
    point: tuple[float, float],
    ways: list[dict],
    max_dist_m: float = 200.0,
) -> dict | None:
    """Associates a *point* with a particular side of a block-face.

    If no named road exists within *max_dist_m* meters, we return None.

    The caller in *issues.py* groups points by their block face and side using
    the returned key before they undergo distance-based clustering.
    """
    if not ways:
        return None

    best_way = None
    best_dist = float("inf")
    best_proj: tuple[float, float] = (0.0, 0.0)
    best_seg_idx = 0

    for way in ways:
        proj, seg_idx, dist = _nearest_on_polyline(point, way["geometry"])
        if dist < best_dist:
            best_dist = dist
            best_way = way
            best_proj = proj
            best_seg_idx = seg_idx

    if best_way is None or best_dist > max_dist_m:
        return None

    side = _side_of_point(point, best_way["geometry"], best_seg_idx)
    intersection_indices = _find_intersection_indices(best_way, ways)
    block_face_geom, from_street, to_street, from_idx, to_idx = _block_face(
        best_way, best_proj, intersection_indices, ways
    )

    cross_streets = [s for s in [from_street, to_street] if s]
    name = best_way["name"]

    if from_street and to_street:
        label = f"{side} side of {name} between {from_street} & {to_street}"
    elif from_street or to_street:
        cross = from_street or to_street
        label = f"{side} side of {name} near {cross}"
    else:
        label = f"{side} side of {name}"

    # We resolve node IDs at block-face boundaries so connectivity penalties
    # can propagate across them.
    node_ids = best_way.get("node_ids", [])
    from_node_id = (
        node_ids[from_idx]
        if from_idx is not None and from_idx < len(node_ids)
        else None
    )
    to_node_id = (
        node_ids[to_idx] if to_idx is not None and to_idx < len(node_ids) else None
    )

    # We use -1 instead of None for indices so the key remains hashable.
    key = (
        best_way["id"],
        from_idx if from_idx is not None else -1,
        to_idx if to_idx is not None else -1,
        side,
    )

    return {
        "name": name,
        "side": side,
        "cross_streets": cross_streets,
        "geometry": block_face_geom if block_face_geom else best_way["geometry"],
        "way_id": best_way["id"],
        "label": label,
        # These fields exist so we can group and propagate data.
        "key": key,
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
    }


def _bbox_from_points(
    points: list[tuple[float, float]],
    radius_m: float,
) -> tuple[float, float, float, float]:
    """Computes a bounding box as (min_lat, min_lon, max_lat, max_lon) padded by
    *radius_m*.
    """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    mean_lat = sum(lats) / len(lats)
    lat_deg = radius_m / 111_000
    lon_deg = radius_m / (111_000 * max(0.001, math.cos(math.radians(mean_lat))))
    return (
        min(lats) - lat_deg,
        min(lons) - lon_deg,
        max(lats) + lat_deg,
        max(lons) + lon_deg,
    )


def _unknown_segment() -> dict:
    return {
        "name": "Unknown road",
        "side": "nearby",
        "cross_streets": [],
        "geometry": [],
        "way_id": None,
        "label": "Unknown road location",
    }
