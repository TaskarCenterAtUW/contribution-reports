"""Ingests offline changeset archives by converting a zip file or directory into a
cache dict.
"""

import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .offline_quest_validation import _validate_quest_definition
from .offline_validate import (
    _reject_lone_surrogates,
    _validate_changeset_entry,
    _validate_osc_member,
)
from .osc import _extract_quest_element_info
from .quests import build_quest_index


# This decompression guard rejects zip members exceeding this size based on the
# header before any data enters memory.
_MAX_MEMBER_BYTES = 128 * 1024 * 1024


def _reject_encrypted(archive_path, info: zipfile.ZipInfo) -> None:
    if info.flag_bits & 0x1:
        raise ValueError(
            f"{archive_path}: cannot accept encrypted zip member: {info.filename}"
        )


# OSM and quest payloads typically nest fewer than 10 levels deep. This limit
# ensures accepted values remain within the recursion budget of `json.dumps`
# across different interpreters, because `json.loads` accepts structures deeper
# than `json.dumps` can re-serialize.
_MAX_JSON_DEPTH = 100


def _json_nesting_over_deep(obj) -> bool:
    # An explicit stack enables an iterative depth walk because inputs may
    # approach the load ceiling (~6,300 levels), which would exhaust a
    # recursive guard. The loop terminates when it finds a container exceeding
    # the cap.
    stack = [(obj, 1)]
    while stack:
        value, depth = stack.pop()
        if depth > _MAX_JSON_DEPTH:
            return True
        if isinstance(value, dict):
            stack.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            stack.extend((v, depth + 1) for v in value)
    return False


def _loads(text: str | bytes, where: str):
    """Wraps `json.loads` to convert any `RecursionError` into a `ValueError` to
    prevent deep-nesting attacks from producing tracebacks.

    We also reject data that passes parsing but exceeds `_MAX_JSON_DEPTH` so
    that downstream cache re-dumps never overflow when we accept the data.
    """
    try:
        data = json.loads(text)
    except RecursionError:
        raise ValueError(
            f"{where}: JSON exceeds maximum nesting depth for parsing"
        ) from None
    if _json_nesting_over_deep(data):
        raise ValueError(f"{where}: The JSON nesting level exceeds the storage limit")
    return data


def osc_json_to_xml(osc: dict, member: str | None = None) -> str:
    """Transforms an OSC JSON dictionary containing optional `create`, `modify`,
    and `delete` lists into OsmChange XML.
    """
    if not osc:
        return ""
    root = ET.Element("osmChange")
    root.set("version", "0.6")
    has_content = False
    for action in ("create", "modify", "delete"):
        elements = osc.get(action)
        if not elements:
            continue
        has_content = True
        action_el = ET.SubElement(root, action)
        for elem in elements:
            if not isinstance(elem, dict):
                where = f"{member}: " if member else ""
                raise ValueError(
                    f"{where}{action} action includes an element that is not an object"
                )
            if "type" in elem:
                etype = elem["type"]
            elif "lat" in elem or "lon" in elem:
                etype = "node"
            elif "nodes" in elem:
                etype = "way"
            elif "members" in elem:
                etype = "relation"
            else:
                etype = "node"
            elem_tags = elem.get("tags")
            if elem_tags is not None and not isinstance(elem_tags, dict):
                where = f"{member}: " if member else ""
                raise ValueError(
                    f"{where}element {elem.get('id', '?')} 'tags' must be a JSON object"
                )
            el = ET.SubElement(action_el, etype)
            if "id" in elem:
                el.set("id", str(elem["id"]))
            if "version" in elem:
                el.set("version", str(elem["version"]))
            if etype == "node":
                if "lat" in elem:
                    el.set("lat", str(elem["lat"]))
                if "lon" in elem:
                    el.set("lon", str(elem["lon"]))
            for k, v in (elem.get("tags") or {}).items():
                tag_el = ET.SubElement(el, "tag")
                tag_el.set("k", str(k))
                tag_el.set("v", str(v))
            if etype == "way":
                for node_id in elem.get("nodes") or []:
                    nd = ET.SubElement(el, "nd")
                    nd.set("ref", str(node_id))
            if etype == "relation":
                for member in elem.get("members") or []:
                    m = ET.SubElement(el, "member")
                    m.set("type", str(member.get("type", "")))
                    m.set("ref", str(member.get("ref", "")))
                    m.set("role", str(member.get("role", "")))
    if not has_content:
        return ""
    return ET.tostring(root, encoding="unicode")


def _read_archive(archive_path: Path) -> tuple[dict, dict]:
    """Extracts a manifest and a mapping of `{id_str: osc_dict}` from an extracted
    archive directory or a zip file.

    We'll encounter a `ValueError` if the path doesn't point to a readable zip
    archive or an extracted archive directory, and a missing path triggers a
    `FileNotFoundError`.
    """
    if archive_path.suffix == ".zip" or zipfile.is_zipfile(archive_path):
        try:
            zf = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile:
            raise ValueError(
                f"{archive_path} is neither a proper zip file nor an unpacked folder"
            ) from None
        with zf:
            try:
                manifest_info = zf.getinfo("manifest.json")
            except KeyError:
                raise ValueError(
                    f"{archive_path}: missing manifest.json in archive"
                ) from None
            _reject_encrypted(archive_path, manifest_info)
            try:
                manifest_raw = zf.read(manifest_info)
            except (zipfile.BadZipFile, RuntimeError):
                # BadZipFile and RuntimeError exceptions occur when zipfile
                # cannot unpack a member or the CRC and header hold false data.
                # These do not inherit from OSError, so we raise a ValueError
                # to keep the error within the CLI's handling scope.
                raise ValueError(
                    f"{archive_path}: manifest.json is a damaged zip member"
                ) from None
            manifest = _loads(manifest_raw, f"{archive_path}: manifest.json")
            osc_jsons = {}
            for info in zf.infolist():
                name = info.filename
                if name.startswith("changesets/") and name.endswith(".json"):
                    if info.file_size > _MAX_MEMBER_BYTES:
                        raise ValueError(
                            f"{name} surpasses the allowed "
                            f"{_MAX_MEMBER_BYTES // (1024 * 1024)} MiB "
                            "threshold"
                        )
                    _reject_encrypted(archive_path, info)
                    cs_id = name.split("/")[1].removesuffix(".json")
                    try:
                        member_raw = zf.read(name)
                    except (zipfile.BadZipFile, RuntimeError):
                        raise ValueError(
                            f"{archive_path}: zip member {name} is damaged"
                        ) from None
                    member = _loads(member_raw, name)
                    if member:
                        if not isinstance(member, dict):
                            raise ValueError(
                                f"{name}: OSC JSON requires an object format"
                            )
                        _validate_osc_member(member, name)
                    osc_jsons[cs_id] = member
    elif archive_path.is_dir():
        manifest = _loads(
            (archive_path / "manifest.json").read_text(),
            f"{archive_path}: manifest.json",
        )
        osc_jsons = {}
        cs_dir = archive_path / "changesets"
        if cs_dir.exists():
            for f in cs_dir.glob("*.json"):
                member = _loads(f.read_text(), f"changesets/{f.name}")
                if member:
                    if not isinstance(member, dict):
                        raise ValueError(
                            f"changesets/{f.name}: OSC JSON requires an object format"
                        )
                    _validate_osc_member(member, f"changesets/{f.name}")
                osc_jsons[f.stem] = member
    else:
        raise ValueError(
            f"{archive_path} is neither a proper zip file nor an unpacked folder"
        )
    if not isinstance(manifest, dict):
        raise ValueError(
            f"{archive_path}: manifest.json needs to be structured as a JSON object"
        )
    return manifest, osc_jsons


def load_offline_archive(
    archive_path: str | Path,
    quest_path: str | Path | None = None,
) -> dict:
    """Loads a changeset archive from a directory or zip file to produce a cache
    dict.

    We build the returned dict to match the shape of a live-fetch cache:
        {date, workspaces: {id_str: {id, title, type, quest_definition, changesets[], notes:[]}}}
    """
    manifest, osc_jsons = _read_archive(Path(archive_path))

    raw_changesets = manifest.get("changesets", [])
    if not isinstance(raw_changesets, list):
        raise ValueError(
            f"{archive_path}: the 'changesets' field in "
            "manifest.json is required to be a list"
        )

    if "workspace" in manifest and not isinstance(manifest["workspace"], dict):
        raise ValueError(
            f"{archive_path}: the 'workspace' key in "
            "manifest.json requires an object value"
        )

    ws_meta = manifest.get("workspace", {})
    ws_id = ws_meta.get("id", 0)
    ws_title = ws_meta.get("title", "Unknown Workspace")
    _reject_lone_surrogates(
        f"{archive_path}: manifest.json workspace", "title", ws_title
    )
    ws_type = ws_meta.get("type", "osw")

    quest_def = None
    if quest_path:
        raw = _loads(
            Path(quest_path).read_text(),
            f"quest file {quest_path}",
        )
        quest_def = {"elements": raw} if isinstance(raw, list) else raw
        _validate_quest_definition(quest_def, quest_path)

    quest_index = build_quest_index(quest_def)

    changesets = []
    for i, cs in enumerate(raw_changesets):
        if not isinstance(cs, dict):
            raise ValueError(
                f"{archive_path}: manifest.json changesets entry {i} must be an object"
            )
        if "id" not in cs:
            raise ValueError(
                f"{archive_path}: manifest.json changesets entry {i}"
                " is missing required 'id'"
            )
        entry = dict(cs)
        _validate_changeset_entry(entry, i, archive_path)
        osc_json = osc_jsons.get(str(entry["id"]), {})
        entry["osc_xml"] = osc_json_to_xml(
            osc_json, member=f"changesets/{cs['id']}.json"
        )
        info = _extract_quest_element_info(entry["osc_xml"], quest_index)
        if info:
            etype, eid, eversion = info
            entry["elem_type"] = etype
            entry["elem_id"] = eid
            entry["elem_version"] = eversion
        entry["prev_tags"] = None
        changesets.append(entry)

    dates = [cs["created_at"][:10] for cs in changesets if cs.get("created_at")]
    earliest_date = min(dates) if dates else ""

    return {
        "date": earliest_date,
        "workspaces": {
            str(ws_id): {
                "id": ws_id,
                "title": ws_title,
                "type": ws_type,
                "quest_definition": quest_def,
                "changesets": changesets,
                "notes": [],
            }
        },
    }
