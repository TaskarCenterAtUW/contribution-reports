"""Tests that verify quest strictness and error handling at the CLI boundary.

We check that `choice_text` must be a string to avoid `TypeError` when the
popup joins multi-answer values. We verify that load-time rules reject
non-string `choice_text` even when single-answer values would otherwise bypass
this via direct dict lookup. We accept `choice_text` when it is absent, `None`,
or a string.

We verify that bounding boxes must be complete or entirely absent to prevent
`TypeError` during float conversion in `quest-centroid` and `created-marker`
paths. We accept bboxes that are complete, all-None, or wholly absent.

We check that element positions require both `elem_lat` and `elem_lon` to
prevent rounding crashes or partial data loss. We accept cases where both are
present or both are absent.

We verify that element versions must be integers because the consumer calls
`int()` on non-empty version strings. We accept empty strings or absent keys to
match upstream attribute-truthiness skips.
"""

import json

from _cli_errors_helpers import (
    WS_META,
    _EXT_NODE_MEMBER,
    _GEO_OK,
    _accept_cli,
    _build_archive,
    _cs,
    _manifest_zip,
    _quest_cli_fail,
    _quest_def,
    _quest_file,
    _reject_cli,
    _run,
    _run_offline,
)


_NODE = {"id": 1, "version": 1, "lat": 1.0, "lon": 1.0, "tags": {"highway": "path"}}


_BBOX = {"min_lat": 1.0, "min_lon": 2.0, "max_lat": 3.0, "max_lon": 4.0}


def _surface_member(surface):
    elem = {"id": 1, "version": 1, "lat": 1.0, "lon": 1.0}
    return json.dumps({"create": [dict(elem, tags={"ext:surface": surface})]})


def test_choice_text_not_string_raises_clean_error(dummy_env, monkeypatch, capsys):
    # The popup converts multi-answer values like 'yes;no' into a readable tag
    # by joining their choice_text, so we get a TypeError if choice_text is not
    # a string. We can still pass None, absent values, or strings.
    multi = _surface_member("yes;no")
    archive = _manifest_zip(
        dummy_env / "ch.zip",
        {**WS_META, "changesets": [_cs(**_GEO_OK)]},
        {"changesets/1.json": multi},
    )
    for i, bad in enumerate((5, 1.5, {"a": 1}, [1])):
        definition = _quest_def(
            choices=[
                {"value": "yes", "choice_text": bad},
                {"value": "no", "choice_text": "Nope"},
            ]
        )
        quest_file = _quest_file(dummy_env, f"ctext{i}.json", definition)
        _quest_cli_fail(
            monkeypatch,
            capsys,
            archive,
            quest_file,
            str(quest_file),
            "choice_text",
            "cannot be anything but a string",
        )
    ok_choices = [
        [{"value": "yes"}, {"value": "no", "choice_text": "Nope"}],
        [{"value": "yes", "choice_text": None}, {"value": "no"}],
    ]
    for i, choices in enumerate(ok_choices):
        quest_file = _quest_file(
            dummy_env, f"ctextok{i}.json", _quest_def(choices=choices)
        )
        _run(
            monkeypatch, ["--offline", str(archive), "--quest-file", str(quest_file)]
        )()
        captured = capsys.readouterr()
        assert "ERROR" not in captured.err and "Traceback" not in captured.err


def test_answer_choice_text_direct_lookup_divergence(dummy_env, monkeypatch, capsys):
    # We have a documented divergence where single-answer values use a direct
    # dict lookup that tolerates non-str choice_text from upstream (rc0). Even
    # so, the load-time rule rejects these values because other changesets
    # might send multi-answer values for the same quest.
    single = _surface_member("yes")
    archive = _manifest_zip(
        dummy_env / "ch-single.zip",
        {**WS_META, "changesets": [_cs(**_GEO_OK)]},
        {"changesets/1.json": single},
    )
    definition = _quest_def(
        choices=[{"value": "yes", "choice_text": 5}, {"value": "no"}]
    )
    quest_file = _quest_file(dummy_env, "ctext-direct.json", definition)
    _quest_cli_fail(
        monkeypatch,
        capsys,
        archive,
        quest_file,
        str(quest_file),
        "choice_text",
        "cannot be anything but a string",
    )


def test_partial_bbox_triggers_clean_error(dummy_env, monkeypatch, capsys):
    # Markers calculates values like `float(max_lat)` when a bbox contains only
    # partial data (specifically in created-marker and quest-centroid paths).
    # Because a single missing boundary triggers a `TypeError`, we require
    # bboxes to be either entirely present or completely omitted.
    #
    # The completeness rule also blocks path-dependent crashes, such as when
    # missing `min_lat` alone avoids failure due to the `None` guard in
    # markers.
    for missing in ("min_lat", "min_lon", "max_lat", "max_lon"):
        geo = {k: v for k, v in _BBOX.items() if k != missing}
        _run_offline(
            dummy_env,
            monkeypatch,
            capsys,
            f"bbox-{missing}.zip",
            {**WS_META, "changesets": [_cs(**geo)]},
            {"changesets/1.json": json.dumps({"create": [_NODE]})},
            ["incomplete bounding box", missing],
        )
    # Bboxes stay loadable whether they contain complete data, all None values,
    # or are missing entirely.
    variants = [
        dict(_BBOX),
        {k: None for k in _BBOX},
    ]
    for i, geo in enumerate(variants):
        archive = _manifest_zip(
            dummy_env / f"bboxok{i}.zip",
            {**WS_META, "changesets": [_cs(**geo)]},
            {"changesets/1.json": json.dumps({"create": [_NODE]})},
        )
        _accept_cli(dummy_env, monkeypatch, capsys, archive)
    archive = _manifest_zip(
        dummy_env / "bboxok-absent.zip",
        {**WS_META, "changesets": [_cs()]},
        {"changesets/1.json": json.dumps({"create": [_NODE]})},
    )
    _accept_cli(dummy_env, monkeypatch, capsys, archive)


def test_partial_element_position_clean_error(dummy_env, monkeypatch, capsys):
    # We use `elem_lat` and `elem_lon` for marker rounding. If we provide only
    # one of these fields, matched elements crash with "NoneType doesn't define
    # __round__" and other elements suffer silent partial drops. We must
    # provide both fields or neither.
    member = {"changesets/1.json": json.dumps({"create": [_NODE]})}
    for geo, needles in (
        ({"elem_lat": 1.0}, ["incomplete coordinates", "elem_lon"]),
        ({"elem_lon": 1.0}, ["incomplete coordinates", "elem_lat"]),
        ({"elem_lat": 1.0, "elem_lon": None}, ["incomplete coordinates", "elem_lon"]),
        ({"elem_lat": None, "elem_lon": 1.0}, ["incomplete coordinates", "elem_lat"]),
    ):
        _run_offline(
            dummy_env,
            monkeypatch,
            capsys,
            f"pos{list(geo)}.zip".replace(" ", "").replace("'", ""),
            {**WS_META, "changesets": [_cs(**geo)]},
            member,
            needles,
        )
    archive = _manifest_zip(
        dummy_env / "posok.zip",
        {**WS_META, "changesets": [_cs(elem_lat=1.0, elem_lon=2.0, **_BBOX)]},
        member,
    )
    _accept_cli(dummy_env, monkeypatch, capsys, archive)


def test_osc_element_version_needs_to_be_an_integer_clean_error(
    dummy_env, monkeypatch, capsys
):
    # The consumer calls `int()` on the version attribute of any element that
    # has an ID and a non-empty version string. If we craft these members
    # specifically, they trigger an "invalid literal for int()" error that
    # appears without context deep in extraction.
    #
    # Falsy versions--such as absent keys or empty strings--remain accepted.
    # This matches the way the upstream code skips attributes that lack
    # truthiness.
    def member(version=..., drop=False):
        elem = {"id": 1, "lat": 1.0, "lon": 1.0, "tags": {"highway": "path"}}
        if drop:
            return json.dumps({"create": [elem]})
        if version is not ...:
            elem["version"] = version
        return json.dumps({"create": [elem]})

    for i, bad in enumerate(("1.5", "abc", {"a": 1}, True, None)):
        _run_offline(
            dummy_env,
            monkeypatch,
            capsys,
            f"ver{i}.zip",
            {**WS_META, "changesets": [_cs()]},
            {"changesets/1.json": member(bad)},
            [
                "changesets/1.json",
                "element 1",
                "'version'",
                "requires an integer value",
            ],
            name_archive=False,
        )
    for i, ok in enumerate(
        (
            {"version": "3"},
            {"version": 3},
            {"version": 0},
            {"version": ""},
            {"drop": True},
        )
    ):
        archive = _manifest_zip(
            dummy_env / f"verok{i}.zip",
            {**WS_META, "changesets": [_cs()]},
            {"changesets/1.json": member(**ok)},
        )
        _accept_cli(dummy_env, monkeypatch, capsys, archive)


# We pass geo coordinate fields to round() without first coercing them to
# numbers.


def test_elem_pair_numeric_strings_error(dummy_env, monkeypatch, capsys):
    # We see the marker build fail when we pass strings because
    # `markers.py:115` applies `round()` directly to `elem_lat` and `elem_lon`
    # during the `quest_type` fallback. The code lacks the `float()` wrap that
    # exists for bbox bounds.
    #
    # Booleans remain valid since `round(True, 6)` executes without error--a
    # behavior that follows the round-8 F5 ruling.
    archive = _build_archive(
        dummy_env, "a1.zip", {"elem_lat": "1.5", "elem_lon": "2.5"}
    )
    _reject_cli(
        dummy_env,
        monkeypatch,
        capsys,
        archive,
        ["entry 0", "has non-numeric", "elem_lat"],
    )
    for i, (lat, lon) in enumerate(((1.5, 2.5), (True, True), (1, 2))):
        archive = _build_archive(
            dummy_env, f"a1ok{i}.zip", {"elem_lat": lat, "elem_lon": lon}
        )
        _accept_cli(dummy_env, monkeypatch, capsys, archive)


def test_elem_pair_strings_legacy_cache_clean_error(dummy_env, monkeypatch, capsys):
    # When we have an element that matches a quest and contains an `elem_id`,
    # the legacy cache path for single elements provides input to `round()`
    # instead (`markers.py:79`), which results in the same rejection.
    archive = _build_archive(
        dummy_env,
        "a2.zip",
        {"elem_lat": "1.5", "elem_lon": "2.5", "elem_id": "1"},
        member=_EXT_NODE_MEMBER,
    )
    _reject_cli(
        dummy_env,
        monkeypatch,
        capsys,
        archive,
        ["entry 0", "has non-numeric", "elem_lat"],
        quest=True,
    )


def test_all_elem_geoms_coord_strings_clean_error(dummy_env, monkeypatch, capsys):
    # We need to reference this test's behavior because `markers.py:79` applies
    # `round()` to raw coordinates within `all_elem_geoms`.
    archive = _build_archive(
        dummy_env,
        "a3.zip",
        {"all_elem_geoms": {"1": {"lat": "1.5", "lon": "2.5"}}},
        member=_EXT_NODE_MEMBER,
    )
    _reject_cli(
        dummy_env,
        monkeypatch,
        capsys,
        archive,
        ["all_elem_geoms", "contains a non-number", "lat"],
        quest=True,
    )


def test_all_elem_geoms_missing_lon_clean_error(dummy_env, monkeypatch, capsys):
    # We get a KeyError at markers.py:59 because the code attempts to read
    # elem_cache["lon"] without a check once lat has a value. The read never
    # happens if lat is absent or None.
    archive = _build_archive(
        dummy_env,
        "a4.zip",
        {"all_elem_geoms": {"1": {"lat": 1.5}}},
        member=_EXT_NODE_MEMBER,
    )
    _reject_cli(
        dummy_env,
        monkeypatch,
        capsys,
        archive,
        ["all_elem_geoms", "1", "lon"],
        quest=True,
    )
    archive = _build_archive(
        dummy_env,
        "a4ok.zip",
        {
            "all_elem_geoms": {
                "1": {"lat": None, "lon": 2.0},
                "2": {},
                "3": {"lat": None},
            }
        },
        member=_EXT_NODE_MEMBER,
    )
    _accept_cli(dummy_env, monkeypatch, capsys, archive, quest=True)
