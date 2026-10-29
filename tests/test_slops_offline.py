"""These tests pin behaviors in *offline.py* to prevent regressions during
slop-cleanup.

We use these tests to pin observable validation layer behaviors that cleanup
could plausibly alter. We focus on the hoisting of the manifest `'changesets'`
list, the redundant checks for `in entry` and `get(...) is not None` inside
`_validate_changeset_entry`, and the dual truthiness evaluations for OSC
members. These pins document current code behavior instead of intended
behavior.
"""

import json
import zipfile

import pytest

from contribution_reports import offline

WS_META = {"workspace": {"id": 1, "title": "T", "type": "osw"}}


def _manifest_zip(path, manifest, members=None):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, content in (members or {}).items():
            zf.writestr(name, content)
    return path


def _changesets(entries):
    return {**WS_META, "changesets": entries}


def _first_entry(result):
    return result["workspaces"]["1"]["changesets"][0]


def test_null_and_empty_zip_members_are_accepted_without_validation(tmp_path):
    # OSC members that are falsy ('null' and {}) bypass the object-shape raise
    # as well as _validate_osc_member. The test stores these as-is, which
    # results in an empty osc_xml.
    archive = _manifest_zip(
        tmp_path / "falsy.zip",
        _changesets([{"id": 1}, {"id": 2}]),
        {"changesets/1.json": "null", "changesets/2.json": "{}"},
    )
    result = offline.load_offline_archive(archive)
    entries = result["workspaces"]["1"]["changesets"]
    assert [e["id"] for e in entries] == [1, 2]
    assert all(e["osc_xml"] == "" for e in entries)
    assert _first_entry(result)["osc_xml"] == ""


def test_truthy_non_dict_zip_member_raises_value_error(tmp_path):
    archive = _manifest_zip(
        tmp_path / "list-member.zip",
        _changesets([{"id": 1}]),
        {"changesets/1.json": "[1]"},
    )
    with pytest.raises(ValueError, match="OSC JSON requires an object format"):
        offline.load_offline_archive(archive)


def test_extracted_directory_accepts_null_member(tmp_path):
    archive_dir = tmp_path / "extracted"
    (archive_dir / "changesets").mkdir(parents=True)
    (archive_dir / "manifest.json").write_text(
        json.dumps(_changesets([{"id": 1}])), encoding="utf-8"
    )
    (archive_dir / "changesets" / "1.json").write_text("null", encoding="utf-8")
    result = offline.load_offline_archive(archive_dir)
    assert _first_entry(result)["osc_xml"] == ""


def test_truthy_non_dict_member_in_directory_raises_value_error(tmp_path):
    archive_dir = tmp_path / "extracted-bad"
    (archive_dir / "changesets").mkdir(parents=True)
    (archive_dir / "manifest.json").write_text(
        json.dumps(_changesets([{"id": 1}])), encoding="utf-8"
    )
    (archive_dir / "changesets" / "1.json").write_text('"x"', encoding="utf-8")
    with pytest.raises(
        ValueError, match=r"changesets/1\.json: OSC JSON requires an object format"
    ):
        offline.load_offline_archive(archive_dir)


def test_loader_rejects_non_string_user_with_value_error(tmp_path):
    archive = _manifest_zip(tmp_path / "user5.zip", _changesets([{"id": 1, "user": 5}]))
    with pytest.raises(ValueError, match="has a non-string user"):
        offline.load_offline_archive(archive)


def test_user_with_lone_surrogate_in_string_raises_value_error(tmp_path):
    archive = _manifest_zip(
        tmp_path / "user-surr.zip",
        _changesets([{"id": 1, "user": "U\ud801"}]),
    )
    with pytest.raises(ValueError, match="lone surrogates"):
        offline.load_offline_archive(archive)


def test_null_tags_raise_value_error_when_not_a_json_object(tmp_path):
    # We want to verify that an explicit null value for the tags key triggers
    # the shape gate instead of the skipped path.
    archive = _manifest_zip(
        tmp_path / "tags-null.zip", _changesets([{"id": 1, "tags": None}])
    )
    with pytest.raises(ValueError, match="The 'tags' field requires a JSON object"):
        offline.load_offline_archive(archive)


def test_non_string_created_by_raises_value_error_inside_dict_tags(tmp_path):
    archive = _manifest_zip(
        tmp_path / "cb-null.zip", _changesets([{"id": 1, "tags": {"created_by": None}}])
    )
    with pytest.raises(ValueError, match="'tags.created_by' requires a string value"):
        offline.load_offline_archive(archive)


def test_quest_type_gate_remains_active_when_tags_hoist_occurs(tmp_path):
    archive = _manifest_zip(
        tmp_path / "qtype.zip",
        _changesets([{"id": 1, "tags": {"quest_type": {"a": 1}}}]),
    )
    with pytest.raises(ValueError, match="expected a string for 'tags.quest_type'"):
        offline.load_offline_archive(archive)


def test_manifest_missing_changesets_key_loads_empty_list(tmp_path):
    # We use a hoisted single read here. When the 'changesets' key is missing,
    # the loader defaults to [] and returns zero entries instead of raising an
    # exception.
    archive = _manifest_zip(tmp_path / "no-cs.zip", dict(WS_META))
    result = offline.load_offline_archive(archive)
    assert result["workspaces"]["1"]["changesets"] == []
