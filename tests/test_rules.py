from contribution_reports.osw.rules import FAMILY_CONFORMANCE, FAMILY_NETWORK, evaluate


def live(key, tags):
    return {key: {"tags": tags, "version": 2, "deleted": False}}


def findings_by_id(final):
    return {f.id: f for f in evaluate(final)}


def test_width_placeholder_fires_when_all_widths_are_zero():
    final = {}
    for i in range(3):
        final.update(live(("way", i), {"highway": "footway", "footway": "sidewalk",
                                       "surface": "concrete", "width": "0.0"}))
    finding = findings_by_id(final)["width-placeholder"]
    assert finding.count == 3
    assert finding.total == 3
    assert finding.family == FAMILY_CONFORMANCE
    # We assert that every populated width here is a placeholder, so we can
    # make the strong claim that coverage is 0%.
    assert "coverage is 0%" in finding.message


def test_no_width_placeholder_finding_when_width_is_real():
    final = live(("way", 1), {"highway": "footway", "footway": "sidewalk",
                              "width": "1.5"})
    assert "width-placeholder" not in findings_by_id(final)


def test_partial_width_placeholders_do_not_claim_zero_percent_coverage():
    """Checks that a mixed fixture with 4 real widths and 1 placeholder does not
    claim 0% coverage.

    We're preventing a regression from an original rule bug where any present
    placeholder caused a hardcoded 0% claim, even when the other 4 measurements
    were genuine.
    """
    final = {}
    for i in range(4):
        final.update(live(("way", i), {"highway": "footway", "footway": "sidewalk",
                                       "surface": "concrete", "width": "1.5"}))
    final.update(live(("way", 9), {"highway": "footway", "footway": "sidewalk",
                                   "surface": "concrete", "width": "0.0"}))
    finding = findings_by_id(final)["width-placeholder"]
    assert finding.count == 1
    assert finding.total == 5
    assert "0%" not in finding.message
    assert "remaining 4" in finding.message


def test_width_placeholder_counts_zero_values_but_not_absent_width_keys():
    final = {}
    final.update(live(("way", 1), {"highway": "footway", "footway": "sidewalk",
                                   "surface": "concrete", "width": "0.0"}))
    final.update(live(("way", 2), {"highway": "footway", "footway": "sidewalk",
                                   "surface": "concrete"}))  # no `width` key
    finding = findings_by_id(final)["width-placeholder"]
    # We need the same distinction used in `state.build_state`, which treats a
    # value of "0.0" as populated and counts only "" or `None` as missing.
    # Without this, we cannot distinguish between a real placeholder like "0.0"
    # and a width key that was never recorded.
    #
    # If we regressed `not in (None, "")` to a basic falsy check, "0.0" would
    # no longer count as populated. The rule would then silently report 0 of 0
    # instead of flagging each placeholder.
    assert finding.count == 1
    assert finding.total == 1


def test_bricks_surface_triggers_enum_off_schema_error():
    final = live(("way", 1), {"highway": "footway", "footway": "sidewalk",
                              "surface": "bricks"})
    finding = findings_by_id(final)["enum-off-schema:surface"]
    assert finding.count == 1
    assert finding.severity == "error"
    assert "bricks" in finding.message


def test_enum_off_schema_findings_do_not_appear_for_valid_surfaces():
    final = live(("way", 1), {"highway": "footway", "footway": "sidewalk",
                              "surface": "concrete"})
    assert "enum-off-schema:surface" not in findings_by_id(final)


def test_enum_off_schema_also_checks_tactile_paving():
    final = live(("node", 1), {"barrier": "kerb", "kerb": "lowered",
                               "tactile_paving": "maybe"})
    assert "enum-off-schema:tactile_paving" in findings_by_id(final)


def test_steps_without_count_fires():
    final = live(("way", 1), {"highway": "steps", "surface": "concrete"})
    finding = findings_by_id(final)["steps-no-count"]
    assert finding.count == 1
    assert finding.total == 1


def test_steps_no_count_finding_absent_when_count_exists():
    final = live(("way", 1), {"highway": "steps", "step_count": "8"})
    assert "steps-no-count" not in findings_by_id(final)


def test_unmarked_crossings_occupy_the_network_family():
    final = {}
    for i in range(2):
        final.update(live(("way", i), {"highway": "footway", "footway": "crossing",
                                       "crossing:markings": "no"}))
    final.update(live(("way", 9), {"highway": "footway", "footway": "crossing",
                                   "crossing:markings": "zebra"}))
    finding = findings_by_id(final)["crossing-unmarked"]
    assert finding.family == FAMILY_NETWORK
    assert finding.severity == "info"
    assert finding.count == 2
    assert finding.total == 3


def test_curb_type_mix_reports_distribution():
    final = {}
    final.update(live(("node", 1), {"barrier": "kerb", "kerb": "lowered"}))
    final.update(live(("node", 2), {"barrier": "kerb", "kerb": "raised"}))
    finding = findings_by_id(final)["curb-type-mix"]
    assert finding.total == 2
    assert "Curb Ramp" in finding.message


def test_curb_type_mix_message_states_it_does_not_match_kerb_only_elements():
    """Checks that the `curb-type-mix` count applies only to curbs recognized by
    the schema (`barrier=kerb`).

    If a node has `kerb=no` but lacks `barrier=kerb`, it fails to match any
    curb Entity, which makes it invisible to this rule. We need the message to
    state this fact instead of suggesting that N represents every curb-ish
    element the rule touched.
    """
    final = live(("node", 1), {"barrier": "kerb", "kerb": "lowered"})
    finding = findings_by_id(final)["curb-type-mix"]
    assert "barrier=kerb" in finding.message
    assert "kerb=" in finding.message
    assert "not" in finding.message.lower()


def test_deleted_elements_are_not_evaluated():
    final = {("way", 1): {"tags": {"highway": "footway", "footway": "sidewalk",
                                   "surface": "bricks"},
                          "version": 2, "deleted": True}}
    assert findings_by_id(final) == {}


def test_findings_have_a_maximum_number_of_samples():
    final = {}
    for i in range(50):
        final.update(live(("way", i), {"highway": "steps"}))
    finding = findings_by_id(final)["steps-no-count"]
    assert finding.count == 50
    assert len(finding.samples) == 20


def test_evaluate_sorts_by_severity_then_descending_count():
    final = {}
    # We have two sidewalks with surface values outside the schema. This
    # produces an error with a count of 2.
    for i in range(2):
        final.update(live(("way", i), {"highway": "footway", "footway": "sidewalk",
                                       "surface": "bricks"}))
    # We need one step that lacks a `step_count` to trigger a warning with a
    # count of 1.
    final.update(live(("way", 10), {"highway": "steps"}))
    # We test that descending counts break ties within a single severity tier.
    # Here we verify that curb-type-mix (count 3) outranks crossing-unmarked
    # (count 2) among info findings.
    final.update(live(("node", 20), {"barrier": "kerb", "kerb": "lowered"}))
    final.update(live(("node", 21), {"barrier": "kerb", "kerb": "raised"}))
    final.update(live(("node", 22), {"barrier": "kerb", "kerb": "flush"}))
    for i in range(2):
        final.update(live(("way", 30 + i), {"highway": "footway", "footway": "crossing",
                                            "crossing:markings": "no"}))

    ids = [f.id for f in evaluate(final)]
    assert ids == ["enum-off-schema:surface", "steps-no-count",
                    "curb-type-mix", "crossing-unmarked"]
