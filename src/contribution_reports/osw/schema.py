"""Catalog of OpenSidewalks entities, attributes, and classification rules.

We treat the catalog as data instead of code, so we can add an attribute or
entity through table edits. We transcribed these values from the published
OpenSidewalks schema.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Attr:
    """Defines an OSW attribute and the rules that validate its values."""
    kind: str  # we choose from enum, numeric, integer, or text
    values: frozenset | None = None  # we need these when `kind` is `"enum"`
    placeholders: frozenset | None = None  # values that represent unmeasured data
    unit: str | None = None


@dataclass(frozen=True)
class Entity:
    """An OSW entity type and its optional schema attributes.

    We use `match` as a tuple of (tag_key, allowed_values) pairs; if we leave
    the allowed_values tuple empty, it means any non-empty value paired with
    that key satisfies the match.
    """
    name: str
    match: tuple
    geom: str                                  # node | way
    attrs: tuple


EDGE_ATTRS = ("width", "surface", "incline", "length", "description", "name", "foot")

STREET_VALUES = ("primary", "secondary", "tertiary", "residential", "service",
                 "unclassified", "trunk", "living_street")

# We order these from most specific to least, so the first match wins.
ENTITIES = (
    Entity("Curb Ramp",       (("barrier", ("kerb",)), ("kerb", ("lowered",))),
           "node", ("tactile_paving",)),
    Entity("Raised Curb",     (("barrier", ("kerb",)), ("kerb", ("raised",))),
           "node", ("tactile_paving",)),
    Entity("Rolled Curb",     (("barrier", ("kerb",)), ("kerb", ("rolled",))),
           "node", ("tactile_paving",)),
    Entity("Flush Curb",      (("barrier", ("kerb",)), ("kerb", ("flush",))),
           "node", ("tactile_paving",)),
    Entity("Generic Curb",    (("barrier", ("kerb",)),),
           "node", ("tactile_paving",)),
    Entity("Sidewalk",        (("highway", ("footway",)), ("footway", ("sidewalk",))),
           "way", EDGE_ATTRS),
    Entity("Crossing",        (("highway", ("footway",)), ("footway", ("crossing",))),
           "way", EDGE_ATTRS + ("crossing:markings",)),
    Entity("Traffic Island",  (("highway", ("footway",)), ("footway", ("traffic_island",))),
           "way", EDGE_ATTRS),
    Entity("Footway",         (("highway", ("footway",)),),
           "way", EDGE_ATTRS),
    Entity("Steps",           (("highway", ("steps",)),),
           "way", EDGE_ATTRS + ("step_count", "climb")),
    Entity("Pedestrian Road", (("highway", ("pedestrian",)),),
           "way", EDGE_ATTRS),
    Entity("Street",          (("highway", STREET_VALUES),),
           "way", EDGE_ATTRS),
)

ATTRIBUTES = {
    "surface": Attr("enum", frozenset({
        "asphalt", "concrete", "gravel", "grass", "paved", "paving_stones",
        "unpaved", "dirt", "grass_paver"})),
    "tactile_paving": Attr("enum", frozenset({"yes", "no", "contrasted", "primitive"})),
    "crossing:markings": Attr("enum", frozenset({
        "yes", "no", "surface", "lines", "lines:paired", "dashes", "dots",
        "zebra", "zebra:double", "zebra:paired", "zebra:bicolour", "ladder",
        "skewed", "ladder:paired", "rainbow", "lines:rainbow", "zebra:rainbow",
        "ladder:skewed", "pictograms"})),
    "foot": Attr("enum", frozenset({
        "yes", "no", "designated", "permissive", "use_sidepath", "private",
        "destination"})),
    "climb": Attr("enum", frozenset({"up", "down"})),
    "width": Attr("numeric", placeholders=frozenset({"0", "0.0"}), unit="m"),
    "incline": Attr("numeric"),
    "length": Attr("numeric", unit="m"),
    "step_count": Attr("integer"),
    "name": Attr("text"),
    "description": Attr("text"),
}

BUCKET_ENTITY = "osw_entity"
BUCKET_VERTEX = "geometry_vertex"
BUCKET_NON_OSW = "non_osw_feature"
BUCKET_UNTAGGED_WAY = "untagged_way"


def core_tags(tags: dict) -> dict:
    """Removes provenance tags that start with `ext:`, while retaining content
    tags for OSW and OSM.
    """
    return {k: v for k, v in tags.items() if not k.startswith("ext:")}


def _matches(entity: Entity, tags: dict) -> bool:
    for key, allowed in entity.match:
        value = tags.get(key)
        if not value:
            return False
        if allowed and value not in allowed:
            return False
    return True


def classify_tags(tags: dict) -> Entity | None:
    """Returns the first matching OSW entity, or None.

    We strip `ext:`-prefixed tags before we run the match. Because of this, we
    can pass raw tags or tags already filtered by `core_tags()`. The second
    strip performs a defensive no-op and does not impose a requirement on the
    caller.
    """
    core = core_tags(tags)
    for entity in ENTITIES:
        if _matches(entity, core):
            return entity
    return None


def bucket_for(elem_type: str, tags: dict) -> tuple:
    """Assigns an element to a single classification bucket.

    We need to pass `adiff.effective_tags(action)` to ensure deletes use tags
    from before they were removed (Rule C).
    """
    core = core_tags(tags)
    if not core:
        return (BUCKET_VERTEX if elem_type == "node" else BUCKET_UNTAGGED_WAY, None)
    entity = classify_tags(core)
    if entity is not None:
        return BUCKET_ENTITY, entity
    return BUCKET_NON_OSW, None
