from conftest import make_action, make_element

from contribution_reports.osw.state import build_state, final_elements, live_elements


def cs(cs_id=63, created_by="Rapid 2.5.5", changes_count=1):
    return {"id": cs_id, "user": "Mapper", "uid": 341,
            "created_at": "2026-06-01T10:00:00Z",
            "changes_count": changes_count,
            "tags": {"created_by": created_by}}


def test_final_elements_retains_highest_version():
    changesets = [cs(63), cs(64)]
    adiffs = {
        "63": [make_action("modify",
                           new=make_element(elem_id=1, version=2, changeset=63,
                                            tags={"surface": "concrete"}),
                           old=make_element(elem_id=1, version=1, changeset=1))],
        "64": [make_action("modify",
                           new=make_element(elem_id=1, version=3, changeset=64,
                                            tags={"surface": "asphalt"}),
                           old=make_element(elem_id=1, version=2, changeset=63))],
    }
    final = final_elements(changesets, adiffs)
    assert final[("node", 1)]["tags"] == {"surface": "asphalt"}
    assert final[("node", 1)]["version"] == 3


def test_final_elements_marks_deleted_elements():
    changesets = [cs(63)]
    adiffs = {"63": [make_action(
        "delete",
        new=make_element(elem_id=1, version=2, changeset=63, tags={}, visible=False),
        old=make_element(elem_id=1, version=1, changeset=1,
                         tags={"highway": "footway"}))]}
    final = final_elements(changesets, adiffs)
    assert final[("node", 1)]["deleted"] is True
    assert live_elements(final) == {}


def test_final_elements_ignores_context_rows():
    changesets = [cs(63)]
    adiffs = {"63": [make_action("modify",
                                 new=make_element(elem_id=9, changeset=1),
                                 old=make_element(elem_id=9, changeset=1))]}
    assert final_elements(changesets, adiffs) == {}


def test_final_elements_excludes_baseline_by_default():
    changesets = [cs(1, created_by="TDEI Workspaces"), cs(63)]
    adiffs = {
        "1": [make_action("create", new=make_element(elem_id=5, changeset=1))],
        "63": [make_action("create", new=make_element(elem_id=6, changeset=63))],
    }
    final = final_elements(changesets, adiffs)
    assert ("node", 5) not in final
    assert ("node", 6) in final


def test_build_state_calculates_coverage_percentages():
    final = {
        ("node", 1): {"tags": {"barrier": "kerb", "kerb": "lowered",
                               "tactile_paving": "no"},
                      "version": 2, "deleted": False},
        ("node", 2): {"tags": {"barrier": "kerb", "kerb": "lowered"},
                      "version": 2, "deleted": False},
    }
    state = build_state(final)
    coverage = state["entities"]["Curb Ramp"]["coverage"]["tactile_paving"]
    assert coverage == {"have": 1, "total": 2, "pct": 50.0, "status": "fair"}


def test_build_state_calculates_status_counts_from_entity_coverage():
    final = {
        ("way", 1): {"tags": {"highway": "footway", "footway": "sidewalk",
                              "surface": "concrete", "width": "1.5"},
                     "version": 2, "deleted": False},
        ("way", 2): {"tags": {"highway": "footway", "footway": "sidewalk",
                              "surface": "concrete"},
                     "version": 2, "deleted": False},
    }
    state = build_state(final)
    # We check the status counts for sidewalk attributes: width, surface,
    # incline, length, description, name, and foot. Surface scores 2/2 (good),
    # width scores 1/2 (fair), and the five other attributes score 0/2 (poor).
    #
    # Because it uses the same per-attribute statuses as coverage, we need
    # `status_counts` to match coverage exactly.
    assert state["entities"]["Sidewalk"]["status_counts"] == {
        "good": 1, "fair": 1, "poor": 5,
    }


def test_build_state_excludes_deleted_elements():
    final = {
        ("node", 1): {"tags": {"barrier": "kerb", "kerb": "lowered"},
                      "version": 2, "deleted": False},
        ("node", 2): {"tags": {"barrier": "kerb", "kerb": "lowered"},
                      "version": 2, "deleted": True},
    }
    state = build_state(final)
    assert state["entities"]["Curb Ramp"]["count"] == 1
    assert state["touched"] == 2
    assert state["live"] == 1


def test_build_state_records_entity_property_value_distributions():
    final = {
        ("way", i): {"tags": {"highway": "footway", "footway": "sidewalk",
                              "surface": surface},
                     "version": 2, "deleted": False}
        for i, surface in enumerate(["concrete", "concrete", "asphalt"])
    }
    distributions = build_state(final)["entities"]["Sidewalk"]["distributions"]
    assert distributions["surface"] == {"concrete": 2, "asphalt": 1}


def test_build_state_treats_empty_strings_as_missing():
    final = {("node", 1): {"tags": {"barrier": "kerb", "kerb": "lowered",
                                    "tactile_paving": ""},
                           "version": 2, "deleted": False}}
    state = build_state(final)
    assert state["entities"]["Curb Ramp"]["coverage"]["tactile_paving"]["have"] == 0
