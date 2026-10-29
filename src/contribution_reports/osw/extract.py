"""Provides optional full-workspace extracts to generate completeness figures
across the dataset.

We keep this payload separate from the main cache because it refreshes on a
different cadence, is optional, and exceeds the size of adiffs by an order of
magnitude.
"""

from pathlib import Path

from .adiff import fetch_json


def extract_path(cache_file: Path) -> Path:
    """Returns the path to an extract file located in the same directory as
    *cache_file*.

    We determine the file stem by stripping `.json.gz` or `.json` from the end
    of the name, then we append `_extract.json.gz` to create the sibling path.
    """
    cache_file = Path(cache_file)
    stem = cache_file.name
    for suffix in (".json.gz", ".json"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return cache_file.parent / f"{stem}_extract.json.gz"


def fetch_map_extract(osm_url: str, ws_id: int, bbox, token: str | None) -> list:
    """Downloads all elements within *bbox* using the OSM map call.

    If we have no known *bbox*, we return [] so a workspace lacking positioned
    changesets can degrade to touched-element figures instead of failing.
    """
    if not bbox:
        return []
    box = ",".join(str(v) for v in bbox)
    url = f"{osm_url.rstrip('/')}/api/0.6/map.json?bbox={box}"
    headers = {"X-Workspace": str(ws_id)}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    print(f"  Fetching full extract for bbox {box}...")
    elements = fetch_json(url, headers).get("elements", [])
    print(f"  Extract: {len(elements)} elements")
    return elements


def elements_to_final(elements: list) -> dict:
    """Converts raw map elements into the `{(type, id): record}` format required
    by `build_state`.
    """
    return {
        (e.get("type", "node"), e.get("id")): {
            "tags": e.get("tags") or {},
            "version": e.get("version", 0),
            "deleted": False,
        }
        for e in elements
    }
