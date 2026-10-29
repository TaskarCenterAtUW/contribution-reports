from contribution_reports.osw.schema import (
    ATTRIBUTES, BUCKET_ENTITY, BUCKET_NON_OSW, BUCKET_UNTAGGED_WAY,
    BUCKET_VERTEX, bucket_for, classify_tags, core_tags,
)


def test_core_tags_removes_keys_that_start_with_ext():
    tags = {"highway": "footway", "ext:osm_version": "2", "ext:sw_id": "l_1"}
    assert core_tags(tags) == {"highway": "footway"}


def test_curb_ramp_matches_before_generic_curb():
    entity = classify_tags({"barrier": "kerb", "kerb": "lowered"})
    assert entity.name == "Curb Ramp"


def test_generic_curb_matches_when_kerb_value_is_absent():
    assert classify_tags({"barrier": "kerb"}).name == "Generic Curb"


def test_sidewalk_matches_before_footway():
    entity = classify_tags({"highway": "footway", "footway": "sidewalk"})
    assert entity.name == "Sidewalk"


def test_footway_without_subtags_matches_footway():
    assert classify_tags({"highway": "footway"}).name == "Footway"


def test_crossing_sets_crossing_markings_and_surface_attributes():
    entity = classify_tags({"highway": "footway", "footway": "crossing"})
    assert "crossing:markings" in entity.attrs
    assert "surface" in entity.attrs


def test_classify_tags_returns_street_when_highway_is_residential():
    assert classify_tags({"highway": "residential"}).name == "Street"


def test_unrecognized_tags_classify_as_none():
    assert classify_tags({"amenity": "bench"}) is None


def test_untagged_nodes_bucket_as_geometry_vertex():
    bucket, entity = bucket_for("node", {})
    assert bucket == BUCKET_VERTEX
    assert entity is None


def test_ext_only_node_buckets_are_geometry_vertices():
    # Import vertices carry provenance via ext, which doesn't constitute OSW
    # content.
    bucket, _ = bucket_for("node", {"ext:osm_version": "2"})
    assert bucket == BUCKET_VERTEX


def test_bucket_for_matched_entity_is_bucket_entity():
    bucket, entity = bucket_for("node", {"barrier": "kerb", "kerb": "lowered"})
    assert bucket == BUCKET_ENTITY
    assert entity.name == "Curb Ramp"


def test_tagged_features_that_are_not_osw_bucket_separately():
    bucket, entity = bucket_for("node", {"amenity": "bench"})
    assert bucket == BUCKET_NON_OSW
    assert entity is None


def test_untagged_ways_bucket_separately_from_vertices():
    bucket, _ = bucket_for("way", {"ext:osm_version": "2"})
    assert bucket == BUCKET_UNTAGGED_WAY


def test_surface_enum_excludes_bricks_and_includes_paving_stones():
    # OSM values include bricks, but the OSW schema lacks an equivalent term.
    # Instead, we use paving_stones for this category in OSW.
    assert "bricks" not in ATTRIBUTES["surface"].values
    assert "paving_stones" in ATTRIBUTES["surface"].values


def test_width_has_zero_and_zero_point_zero_as_placeholders():
    assert ATTRIBUTES["width"].placeholders == frozenset({"0", "0.0"})
