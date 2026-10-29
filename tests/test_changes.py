from conftest import make_action, make_element

from contribution_reports.osw.changes import (
    CLASS_APP, CLASS_EDITOR, CLASS_IMPORT, build_ledger, classify_changeset,
    diff_tags, geometry_changed, modify_kind,
)


def cs(cs_id=63, user="Mapper", created_by="Rapid 2.5.5", changes_count=1,
       created_at="2026-06-01T10:00:00Z", extra_tags=None):
    tags = {"created_by": created_by, "comment": "fixes"}
    tags.update(extra_tags or {})
    return {"id": cs_id, "user": user, "uid": 341, "created_at": created_at,
            "changes_count": changes_count, "tags": tags}


def test_import_changeset_is_classified_as_baseline_import():
    changeset = cs(1, created_by="TDEI Workspaces", extra_tags={"workspace": "1280"})
    assert classify_changeset(changeset) == CLASS_IMPORT


def test_survey_app_changeset_returns_app_classification():
    assert classify_changeset(cs(5, created_by="AVIV ScoutRoute 1.2")) == CLASS_APP


def test_rapid_changeset_becomes_editor():
    assert classify_changeset(cs(5, created_by="Rapid 2.5.5")) == CLASS_EDITOR


def test_diff_tags_separates_added_changed_and_removed_tags():
    added, changed, removed = diff_tags(
        {"kerb": "lowered", "gone": "1"},
        {"kerb": "flush", "tactile_paving": "no"})
    assert added == {"tactile_paving": "no"}
    assert changed == {"kerb": ("lowered", "flush")}
    assert removed == {"gone": "1"}


def test_geometry_changed_returns_true_when_a_node_moves():
    action = make_action("modify",
                         new=make_element(lat=46.4, lon=-119.2),
                         old=make_element(lat=46.3, lon=-119.2))
    assert geometry_changed(action) is True


def test_geometry_changed_detects_when_a_way_node_list_changes():
    action = make_action("modify",
                         new=make_element("way", nodes=[{"ref": 1, "lat": 1, "lon": 1},
                                                        {"ref": 2, "lat": 2, "lon": 2}]),
                         old=make_element("way", nodes=[{"ref": 1, "lat": 1, "lon": 1}]))
    assert geometry_changed(action) is True


def test_way_geometry_change_ignores_coordinate_drift_if_references_remain_same():
    """Checks that `geometry_changed` ignores coordinate drift in ways when
    reference lists remain unchanged.

    When a child node moves, the node's version increases but the way's version
    does not, because the node receives its own modify action within the same
    adiff. The inline coordinates for the way also change (because the `old`
    side of the adiff contains genuine old geometry), but we compare reference
    lists instead of coordinates to avoid double-counting geometry work under
    both the way and the node's individual action.
    """
    action = make_action("modify",
                         new=make_element("way", nodes=[{"ref": 1, "lat": 5, "lon": 5}]),
                         old=make_element("way", nodes=[{"ref": 1, "lat": 1, "lon": 1}]))
    assert geometry_changed(action) is False


def test_modify_kind_returns_geometry_only_when_only_geometry_changes():
    action = make_action("modify",
                         new=make_element(lat=46.4, lon=-119.2, tags={"a": "1"}),
                         old=make_element(lat=46.3, lon=-119.2, tags={"a": "1"}))
    assert modify_kind(action) == "geometry_only"


def test_modify_kind_returns_tags_only_when_coordinates_match():
    action = make_action("modify",
                         new=make_element(lat=46.3, lon=-119.2, tags={"a": "2"}),
                         old=make_element(lat=46.3, lon=-119.2, tags={"a": "1"}))
    assert modify_kind(action) == "tags_only"


def test_modify_kind_returns_both():
    action = make_action("modify",
                         new=make_element(lat=46.4, lon=-119.2, tags={"a": "2"}),
                         old=make_element(lat=46.3, lon=-119.2, tags={"a": "1"}))
    assert modify_kind(action) == "both"


def test_modify_kind_returns_no_op_when_element_is_unchanged():
    action = make_action("modify",
                         new=make_element(lat=46.3, lon=-119.2, tags={"a": "1"}),
                         old=make_element(lat=46.3, lon=-119.2, tags={"a": "1"}))
    assert modify_kind(action) == "no_op"


def test_ledger_excludes_context_rows_from_counts():
    changesets = [cs(63, changes_count=1)]
    adiffs = {"63": [
        make_action("create", new=make_element(elem_id=1, changeset=63,
                                               tags={"barrier": "kerb", "kerb": "lowered"})),
        # The import authored this context row, so it doesn't count.
        make_action("modify", new=make_element(elem_id=2, changeset=1, user="Importer"),
                    old=make_element(elem_id=2, changeset=1, user="Importer")),
    ]}
    ledger = build_ledger(changesets, adiffs)
    assert ledger["reconciliation"]["counted"] == 1
    assert "Importer" not in ledger["contributors"]


def test_ledger_reconciles_number_of_actions_with_changes_count():
    changesets = [cs(63, changes_count=2)]
    adiffs = {"63": [
        make_action("create", new=make_element(elem_id=1, changeset=63)),
        make_action("create", new=make_element(elem_id=2, changeset=63)),
        make_action("modify", new=make_element(elem_id=9, changeset=1),
                    old=make_element(elem_id=9, changeset=1)),
    ]}
    ledger = build_ledger(changesets, adiffs)
    assert ledger["reconciliation"] == {"counted": 2, "expected": 2, "ok": True,
                                        "mismatches": []}


def test_ledger_reports_reconciliation_failure():
    changesets = [cs(63, changes_count=5)]
    adiffs = {"63": [make_action("create", new=make_element(changeset=63))]}
    ledger = build_ledger(changesets, adiffs)
    assert ledger["reconciliation"]["ok"] is False


def test_ledger_reconciliation_happens_per_changeset_not_globally():
    """Checks that an over-count in one changeset does not cancel an under-count
    of the same size in another when calculating the global total.

    This regression test ensures reconciliation fails even if the global totals
    match.
    """
    changesets = [cs(63, changes_count=1), cs(64, changes_count=2)]
    adiffs = {
        "63": [make_action("create", new=make_element(elem_id=1, changeset=63)),
               make_action("create", new=make_element(elem_id=2, changeset=63))],
        "64": [make_action("create", new=make_element(elem_id=3, changeset=64))],
    }
    ledger = build_ledger(changesets, adiffs)
    # Both counted and expected equal 3 globally, so a total reconciliation
    # appears correct.
    assert ledger["reconciliation"]["counted"] == 3
    assert ledger["reconciliation"]["expected"] == 3
    assert ledger["reconciliation"]["ok"] is False
    mismatches = ledger["reconciliation"]["mismatches"]
    assert {"changeset": 63, "counted": 2, "expected": 1} in mismatches
    assert {"changeset": 64, "counted": 1, "expected": 2} in mismatches


def test_ledger_excludes_baseline_import_by_default():
    changesets = [cs(1, user="Importer", created_by="TDEI Workspaces",
                     changes_count=1, extra_tags={"workspace": "1280"}),
                  cs(63, changes_count=1)]
    adiffs = {
        "1": [make_action("create", new=make_element(elem_id=5, changeset=1,
                                                     user="Importer"))],
        "63": [make_action("create", new=make_element(elem_id=6, changeset=63))],
    }
    ledger = build_ledger(changesets, adiffs)
    assert "Importer" not in ledger["contributors"]
    assert ledger["reconciliation"]["counted"] == 1
    assert len(ledger["provenance"]["baseline_import"]) == 1


def test_ledger_includes_baseline_when_requested():
    changesets = [cs(1, user="Importer", created_by="TDEI Workspaces",
                     changes_count=1, extra_tags={"workspace": "1280"})]
    adiffs = {"1": [make_action("create", new=make_element(changeset=1,
                                                          user="Importer"))]}
    ledger = build_ledger(changesets, adiffs, include_baseline=True)
    assert "Importer" in ledger["contributors"]


def test_ledger_records_attribute_deltas_and_value_flips():
    changesets = [cs(63, changes_count=1)]
    adiffs = {"63": [make_action(
        "modify",
        new=make_element(elem_id=1, changeset=63,
                         tags={"barrier": "kerb", "kerb": "flush", "tactile_paving": "no"}),
        old=make_element(elem_id=1, changeset=63,
                         tags={"barrier": "kerb", "kerb": "lowered"}))]}
    ledger = build_ledger(changesets, adiffs)
    assert ledger["attr_deltas"]["Flush Curb"]["tactile_paving"]["added"] == 1
    assert ledger["attr_deltas"]["Flush Curb"]["kerb"]["changed"] == 1
    assert ledger["value_flips"]["kerb"]["lowered → flush"] == 1


def test_ledger_ignores_ext_tags_in_attribute_deltas():
    """Checks that provenance tags with the `ext:` prefix (such as
    `ext:osm_version`) stay out of `attr_deltas` and `value_flips`.

    Even when we exclude these tags, we need the edit to remain classified as
    `tags_only` instead of becoming a `no_op`.
    """
    changesets = [cs(63, changes_count=1)]
    adiffs = {"63": [make_action(
        "modify",
        new=make_element(elem_id=1, changeset=63,
                         tags={"barrier": "kerb", "kerb": "lowered",
                               "ext:osm_version": "2"}),
        old=make_element(elem_id=1, changeset=63,
                         tags={"barrier": "kerb", "kerb": "lowered",
                               "ext:osm_version": "1"}))]}
    ledger = build_ledger(changesets, adiffs)
    assert ledger["attr_deltas"] == {}
    assert ledger["value_flips"] == {}
    assert ledger["modify_kinds"]["tags_only"] == 1


def test_ledger_uses_old_tags_to_classify_deleted_ways():
    """Checks that the ledger correctly identifies deleted ways by examining old
    tags instead of cleared new tags.

    When a delete action clears tags, the `new` element appears untagged. We
    need to ensure these deletions still count against the original tag
    classification.
    """
    changesets = [cs(63, changes_count=1)]
    adiffs = {"63": [make_action(
        "delete",
        new=make_element("way", elem_id=1, changeset=63, tags={}, visible=False),
        old=make_element("way", elem_id=1, changeset=63,
                         tags={"highway": "footway", "footway": "sidewalk"}))]}
    ledger = build_ledger(changesets, adiffs)
    assert ledger["by_entity"]["Sidewalk"]["delete"] == 1
    assert ledger["buckets"]["untagged_way"] == 0


def test_ledger_counts_active_days_per_contributor():
    changesets = [cs(63, changes_count=1, created_at="2026-06-01T10:00:00Z"),
                  cs(64, changes_count=1, created_at="2026-06-02T10:00:00Z")]
    adiffs = {"63": [make_action("create", new=make_element(changeset=63))],
              "64": [make_action("create", new=make_element(changeset=64))]}
    ledger = build_ledger(changesets, adiffs)
    assert ledger["contributors"]["Mapper"]["active_days"] == 2
    assert ledger["contributors"]["Mapper"]["changesets"] == 2


def test_ledger_treats_defining_tags_as_other_tags_not_osw_attributes():
    """Checks that elements containing only classification tags, like a Sidewalk's
    `highway` and `footway`, do not count as OSW attribute work. These tags
    define what an entity is, unlike OpenSidewalks attributes such as width,
    surface, incline, length, description, name, and foot.

    We need to record these tags under the other-tag group to prevent data
    loss. The legacy `attr_deltas` key must also include them without changes
    so that existing readers of that key continue to work.
    """
    changesets = [cs(63, changes_count=1)]
    adiffs = {"63": [make_action(
        "create",
        new=make_element("way", elem_id=1, changeset=63,
                         tags={"highway": "footway", "footway": "sidewalk"}))]}
    ledger = build_ledger(changesets, adiffs)

    assert ledger["osw_attr_deltas"].get("Sidewalk", {}) == {}
    assert ledger["other_tag_deltas"]["Sidewalk"]["highway"]["added"] == 1
    assert ledger["other_tag_deltas"]["Sidewalk"]["footway"]["added"] == 1
    # The legacy combined key retains its original meaning.
    assert ledger["attr_deltas"]["Sidewalk"]["highway"]["added"] == 1
    assert ledger["attr_deltas"]["Sidewalk"]["footway"]["added"] == 1


def test_ledger_records_real_osw_attributes_separately_from_defining_tags():
    """Checks that a single create action splits defining tags from actual OSW
    attributes.

    When we pass both a defining tag pair and an OSW attribute, the ledger
    separates them across different buckets. The `surface` tag (a declared
    Sidewalk attribute) goes into `osw_attr_deltas`, while the
    `highway`/`footway` defining tags go into `other_tag_deltas`.
    """
    changesets = [cs(63, changes_count=1)]
    adiffs = {"63": [make_action(
        "create",
        new=make_element("way", elem_id=1, changeset=63,
                         tags={"highway": "footway", "footway": "sidewalk",
                               "surface": "concrete"}))]}
    ledger = build_ledger(changesets, adiffs)

    assert ledger["osw_attr_deltas"]["Sidewalk"]["surface"]["added"] == 1
    assert "surface" not in ledger["other_tag_deltas"].get("Sidewalk", {})
    assert "highway" not in ledger["osw_attr_deltas"].get("Sidewalk", {})
    assert ledger["other_tag_deltas"]["Sidewalk"]["highway"]["added"] == 1


def test_ledger_records_composition_of_non_osw_feature_signatures():
    """Checks that the `non_osw_feature` bucket includes a composition breakdown
    of compact tag signatures and counts instead of only a total.

    Without this breakdown, we can't distinguish between scenarios, such as:

        "924 non-OSW features" apart from "924 curb records the schema doesn't happen to recognize"
    """
    changesets = [cs(63, changes_count=3)]
    adiffs = {"63": [
        make_action("create", new=make_element(elem_id=1, changeset=63,
                                               tags={"kerb": "no"})),
        make_action("create", new=make_element(elem_id=2, changeset=63,
                                               tags={"kerb": "no"})),
        make_action("create", new=make_element(elem_id=3, changeset=63,
                                               tags={"barrier": "fence"})),
    ]}
    ledger = build_ledger(changesets, adiffs)
    assert ledger["buckets"]["non_osw_feature"] == 3
    assert ledger["non_osw_signatures"]["kerb=no"] == 2
    assert ledger["non_osw_signatures"]["barrier=fence"] == 1
