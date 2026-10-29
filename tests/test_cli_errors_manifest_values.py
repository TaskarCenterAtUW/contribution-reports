"""Tests error handling at the CLI boundary specifically for manifest values.

When we use the `--cached` flag, we want to verify that the tool renders
reports without requiring `WS_*` URL environment variables. We also check that
`EOFError` during authentication prompts--both for general tokens and
passwords--results in a clean exit and an error message that contains no
traceback. The first authentication failure should specifically reference
`WS_REPORT`.

We also validate that changesets and member tags handle malformed fields
without tracebacks. These checks include:

- Ensuring `tags.created_by` is a string.
- Verifying that member actions like `create` are lists.
- Checking that member relation shapes for `nodes` and `members` are lists.
- Confirming that member `lat` values are numeric.
"""

import json
import sys

import pytest

from contribution_reports import auth, cli, offline

from _cli_errors_helpers import WS_META, _cs, _manifest_zip, _run, _run_offline


def test_cached_renders_with_empty_environment(tmp_path, monkeypatch, capsys):
    # We don't need any WS_* URL environment variables when we pass `--cached`
    # because the flag prevents all HTTP calls.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_env", lambda p=None: {})
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps(
            {
                "date": "2026-06-01",
                "workspaces": {
                    "1": {
                        "id": 1,
                        "title": "T",
                        "type": "osw",
                        "quest_definition": None,
                        "changesets": [],
                        "notes": [],
                    }
                },
            }
        )
    )
    out = tmp_path / "report.html"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "contribution-report",
            "--cached",
            "--cache-file",
            str(cache),
            "--output",
            str(out),
        ],
    )
    cli.main()
    assert out.exists()
    captured = capsys.readouterr()
    assert "ERROR" not in captured.err
    assert "Traceback" not in captured.err


def test_auth_prompt_eof_causes_clean_error(monkeypatch, capsys):
    def raise_eof(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    with pytest.raises(SystemExit) as excinfo:
        auth.get_token({"WS_TDEI_BACKEND_URL": "http://localhost"})
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert "WS_REPORT" in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err


def test_auth_password_eof_produces_clean_error(monkeypatch, capsys):
    def raise_eof(prompt):
        raise EOFError

    monkeypatch.setattr("contribution_reports.auth.getpass.getpass", raise_eof)
    env = {"WS_TDEI_BACKEND_URL": "http://localhost", "WS_REPORT_USER": "tester"}
    with pytest.raises(SystemExit) as excinfo:
        auth.get_token(env)
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR:")
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err


# We validate that member tag values and changesets contain no malformed
# fields.


def _osc_zip(dummy_env, name, osc_obj):
    members = {"changesets/1.json": json.dumps(osc_obj)}
    return _manifest_zip(dummy_env / name, {**WS_META, "changesets": [_cs()]}, members)


def test_created_by_tag_non_string_raises_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "cb-int.zip",
        {**WS_META, "changesets": [_cs(tags={"created_by": 5})]},
        None,
        ["entry 0", "created_by", "requires a string"],
    )
    for bad in (None, ["GIG"]):
        with pytest.raises(ValueError, match="tags.created_by"):
            offline.load_offline_archive(
                _manifest_zip(
                    dummy_env / f"cb-{bad!s}.zip",
                    {**WS_META, "changesets": [_cs(tags={"created_by": bad})]},
                )
            )
    # We can omit `created_by` without causing a failure.
    offline.load_offline_archive(
        _manifest_zip(
            dummy_env / "cb-absent.zip",
            {**WS_META, "changesets": [_cs(tags={"foo": "bar"})]},
        )
    )


def test_offline_member_action_not_list_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "create-int.zip",
        {**WS_META, "changesets": [_cs()]},
        {"changesets/1.json": '{"create": 5}'},
        ["changesets/1.json", "create", "needs to be a list"],
        name_archive=False,
    )


def test_offline_member_relation_shapes_clean_error(dummy_env, monkeypatch, capsys):
    oscs = [
        {"create": [{"id": 1, "nodes": 5}]},
        {"create": [{"id": 1, "members": [5]}]},
        {"create": [{"id": 1, "members": {"a": 1}}]},
    ]
    needles = ["nodes", "must be a list", "members"]
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "nodes-int.zip",
        {**WS_META, "changesets": [_cs()]},
        {"changesets/1.json": json.dumps(oscs[0])},
        ["changesets/1.json", "nodes", "requires a list"],
        name_archive=False,
    )
    with pytest.raises(ValueError, match="members"):
        offline.load_offline_archive(_osc_zip(dummy_env, "mem-list.zip", oscs[1]))
    with pytest.raises(ValueError, match="members"):
        offline.load_offline_archive(_osc_zip(dummy_env, "mem-dict.zip", oscs[2]))
    # Node entries load without error because we don't dereference them
    # individually.
    offline.load_offline_archive(
        _osc_zip(
            dummy_env,
            "nodes-ok.zip",
            {"create": [{"id": 1, "nodes": [None, 1, "x", True]}]},
        )
    )


def test_offline_member_lat_not_numeric_clean_error(dummy_env, monkeypatch, capsys):
    elem = {
        "id": 1,
        "version": 1,
        "lat": "garbage",
        "lon": 1.0,
        "tags": {"highway": "path"},
    }
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "lat-garbage.zip",
        {**WS_META, "changesets": [_cs()]},
        {"changesets/1.json": json.dumps({"create": [elem]})},
        ["changesets/1.json", "lat", "numeric"],
        name_archive=False,
    )
    for bad in (None, {}, [], True):
        with pytest.raises(ValueError, match="'lat'"):
            offline.load_offline_archive(
                _osc_zip(
                    dummy_env,
                    f"lat-{type(bad).__name__}.zip",
                    {"create": [dict(elem, lat=bad)]},
                )
            )
    # Frozen upstream employs float(str(v)) for coercion, so digit-strings
    # remain valid.
    offline.load_offline_archive(
        _osc_zip(dummy_env, "lat-str.zip", {"create": [dict(elem, lat="47.4")]})
    )
    offline.load_offline_archive(
        _osc_zip(dummy_env, "lat-zero.zip", {"create": [dict(elem, lat=0)]})
    )


def test_offline_member_type_invalid_name_clean_error(dummy_env, monkeypatch, capsys):
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "type-space.zip",
        {**WS_META, "changesets": [_cs()]},
        {"changesets/1.json": '{"create":[{"id":1,"type":"x y"}]}'},
        ["changesets/1.json", "type"],
        name_archive=False,
    )
    for bad in (5, None, ""):
        with pytest.raises(ValueError, match="type"):
            offline.load_offline_archive(
                _osc_zip(
                    dummy_env, f"type-{bad!r}.zip", {"create": [{"id": 1, "type": bad}]}
                )
            )


def test_offline_member_type_foo_is_accepted(dummy_env, monkeypatch, capsys):
    # Upstream accepts any element tag that follows well-formed XML naming
    # conventions.
    archive = _osc_zip(
        dummy_env,
        "type-foo.zip",
        {"create": [{"id": 1, "type": "foo", "tags": {"a": "b"}}]},
    )
    _run(monkeypatch, ["--offline", str(archive)])()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert (dummy_env / "output" / "report.html").exists()


def test_offline_member_control_char_clean_error(dummy_env, monkeypatch, capsys):
    value_elem = {
        "id": 1,
        "version": 1,
        "lat": 1.0,
        "lon": 1.0,
        "tags": {"k": "a\x00b"},
    }
    _run_offline(
        dummy_env,
        monkeypatch,
        capsys,
        "ctl-value.zip",
        {**WS_META, "changesets": [_cs()]},
        {"changesets/1.json": json.dumps({"create": [value_elem]})},
        ["changesets/1.json", "control character"],
        name_archive=False,
    )
    key_elem = {"id": 1, "version": 1, "lat": 1.0, "lon": 1.0, "tags": {"a\x07b": "v"}}
    with pytest.raises(ValueError, match="control character"):
        offline.load_offline_archive(
            _osc_zip(dummy_env, "ctl-key.zip", {"create": [key_elem]})
        )
    # We can use tabs, newlines, and carriage returns because these characters
    # remain valid in XML.
    offline.load_offline_archive(
        _osc_zip(
            dummy_env,
            "ctl-ok.zip",
            {"create": [dict(value_elem, tags={"k": "a\tb\nc\rd"})]},
        )
    )
