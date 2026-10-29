from conftest import make_action, make_element

from contribution_reports.osw.adiff import (
    effective_tags, geometry_of, is_own_action, own_actions,
)


def test_own_action_is_true_when_changeset_matches():
    action = make_action(new=make_element(changeset=10))
    assert is_own_action(action, 10) is True


def test_is_own_action_true_when_changeset_id_is_a_string():
    action = make_action(new=make_element(changeset=10))
    assert is_own_action(action, "10") is True


def test_context_row_does_not_belong_to_the_current_changeset():
    # Rule A: we test a row from changeset 1 that appears in the adiff for
    # changeset 63.
    action = make_action(new=make_element(changeset=1))
    assert is_own_action(action, 63) is False


def test_own_actions_returns_only_actions_matching_the_changeset():
    actions = [
        make_action(new=make_element(elem_id=1, changeset=63)),
        make_action(new=make_element(elem_id=2, changeset=1)),
        make_action(new=make_element(elem_id=3, changeset=63)),
    ]
    assert [a["new"]["id"] for a in own_actions(actions, 63)] == [1, 3]


def test_effective_tags_use_new_tags_during_create_and_modify_actions():
    action = make_action("modify",
                         new=make_element(tags={"kerb": "flush"}),
                         old=make_element(tags={"kerb": "lowered"}))
    assert effective_tags(action) == {"kerb": "flush"}


def test_effective_tags_returns_old_tags_during_delete():
    # Rule C requires classification to use old tags because delete actions
    # arrive with cleared tags in the `new` element.
    action = make_action("delete",
                         new=make_element(tags={}, visible=False),
                         old=make_element(tags={"highway": "footway"}))
    assert effective_tags(action) == {"highway": "footway"}


def test_effective_tags_use_new_tags_when_delete_action_lacks_old_tags():
    action = make_action("delete", new=make_element(tags={"highway": "footway"}))
    assert effective_tags(action) == {"highway": "footway"}


def test_geometry_of_way_returns_latitude_longitude_pairs():
    way = make_element("way", nodes=[{"ref": 1, "lat": 46.3, "lon": -119.2},
                                     {"ref": 2, "lat": 46.4, "lon": -119.3}])
    assert geometry_of(way) == [[46.3, -119.2], [46.4, -119.3]]


def test_geometry_of_node_returns_single_point():
    assert geometry_of(make_element(lat=46.3, lon=-119.2)) == [[46.3, -119.2]]


def test_geometry_of_returns_empty_list_for_unpositioned_elements():
    assert geometry_of(make_element()) == []
