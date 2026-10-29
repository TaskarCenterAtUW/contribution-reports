"""Validates the structure of inputs used during offline changeset-archive
ingestion.
"""

import re
from datetime import date, datetime


# Downstream marker code passes these manifest changeset entry fields to
# `float()` and `round()`. They contain the bbox and cached-element positions.
_BBOX_FIELDS = ("min_lat", "min_lon", "max_lat", "max_lon")

# Element tag names passed from `osc_json_to_xml` to `ET.SubElement` require
# valid XML formatting. Upstream accepts any name that meets this standard,
# which extends beyond just node, way, or relation.
_XML_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]+$")

# XML 1.0 forbids C0 control characters except for tab, LF, and CR. Including
# these characters in attribute values creates XML that fails to parse later.
_XML_UNSAFE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _parseable_timestamp(value: str) -> bool:
    """Validates whether a string matches the formats required by downstream date
    logic.

    We can pass a complete ISO datetime (as we do with `--tz`), or we can
    provide a string where the first 10 characters form a valid ISO date. The
    latter matches the default no-tz path, which slices the string at `[:10]`
    before it attempts parsing.
    """
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        pass
    try:
        date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def _check_xml_safe(member: str, field: str, value) -> None:
    if _XML_UNSAFE_RE.search(str(value)):
        raise ValueError(
            f"{member}: {field} has a control character not allowed in XML"
        )


def _reject_lone_surrogates(where: str, field: str, value) -> None:
    """Rejects strings that include lone surrogate code points between U+D800 and
    U+DFFF.

    These characters pass through the escaped cache JSON and escape the
    XML-serializer's internal filters, but they cause `out_file.write_text` to
    raise a `UnicodeEncodeError`. This failure occurs after an incomplete HTML
    report has already been written to disk. We don't guard fields that bypass
    the rendered output (such as `created_by` or unmatched `quest_tag`).
    """
    if isinstance(value, str) and any("\ud800" <= c <= "\udfff" for c in value):
        raise ValueError(f"{where} {field!r} cannot have lone surrogates")


def _validate_osc_member(osc: dict, member: str) -> None:
    """Validates member OSC shapes to prevent crashes in `osc_json_to_xml` or
    subsequent XML parsing and float consumption.

    Because `osc_json_to_xml` reports non-object elements directly, we skip
    them here.
    """
    if not osc:
        return
    for action in ("create", "modify", "delete"):
        elements = osc.get(action)
        if not elements:
            continue
        if not isinstance(elements, list):
            raise ValueError(f"{member}: the value of '{action}' needs to be "
                                 "a list")
        for elem in elements:
            if isinstance(elem, dict):
                _validate_osc_element(member, elem)


def _validate_osc_element(member: str, elem: dict) -> None:
    eid = elem.get("id", "?")
    for field in ("id", "version"):
        _check_xml_safe(member, field, elem.get(field))

    # The consumer calls `int()` on the version attribute if its string
    # representation has content. This happens in `osc.py` via
    # `if eid and eversion: int(eversion)` following JSON to XML conversion.
    # Because a malicious value can trigger an "invalid literal for int()"
    # error during extraction without context, we need this check.
    #
    # Falsy versions--those absent as keys or present as empty strings--remain
    # valid. Every other value must pass `int(str(v))`.
    if "version" in elem:
        vstr = str(elem["version"])
        if vstr:
            try:
                int(vstr)
            except ValueError:
                raise ValueError(
                    f"{member}: element {eid} 'version' requires an integer "
                        "value"
                ) from None

    etype = elem.get("type")
    if "type" in elem and (not isinstance(etype, str) or not _XML_NAME_RE.match(etype)):
        raise ValueError(
            f"{member}: the 'type' attribute for element {eid} is not a "
                "proper XML element name"
        )
    if etype is not None:
        _check_xml_safe(member, "type", etype)

    # Upstream only provides lat/lon attributes for the effective element type.
    # This type matches an explicit type flag or follows the same inference
    # osc_json_to_xml uses (lat/lon implies nodes, nodes imply ways, and
    # members imply relations).
    #
    # Because of this, we only run numeric coercion for nodes to mirror how
    # consumers use float(str(...)). We never dereference lat/lon attributes on
    # ways or relations.
    if "type" in elem:
        effective = elem["type"]
    elif "lat" in elem or "lon" in elem:
        effective = "node"
    elif "nodes" in elem:
        effective = "way"
    elif "members" in elem:
        effective = "relation"
    else:
        effective = "node"
    if effective == "node":
        for field in ("lat", "lon"):
            if field in elem:
                v = elem[field]
                try:
                    float(str(v))
                except ValueError:
                    raise ValueError(
                        f"{member}: element {eid} {field!r} requires a "
                            "numerical value"
                    ) from None
                _check_xml_safe(member, field, v)

    nodes = elem.get("nodes")
    if nodes:
        if not isinstance(nodes, list):
            raise ValueError(f"{member}: the 'nodes' field requires a list "
                                 "format")
        for n in nodes:
            _check_xml_safe(member, "nodes entry", n)

    members = elem.get("members")
    if members:
        if not isinstance(members, list):
            raise ValueError(f"{member}: the 'members' field is required to "
                                 "be a list")
        for m in members:
            if not isinstance(m, dict):
                raise ValueError(
                    f"{member}: each entry within element {eid} 'members' "
                        "must be an object"
                )
            for key in ("type", "ref", "role"):
                _check_xml_safe(member, f"members {key}", m.get(key))

    tags = elem.get("tags")
    if tags is not None:
        if not isinstance(tags, dict):
            raise ValueError(f"{member}: element {eid} 'tags' needs to be a "
                                 "JSON object")
        for k, v in tags.items():
            _check_xml_safe(member, "tag key", k)
            _check_xml_safe(member, "tag value", v)


def _validate_changeset_entry(entry: dict, i: int, archive_path) -> None:
    """Validates manifest changeset entries to prevent downstream crashes.

    When an `id` consists only of digits, we cast it to an `int` so that member
    lookups and `sorted()` use homogeneous types. We raise a `ValueError`
    referencing entry `i` if any validation fails.
    """
    where = f"{archive_path}: manifest.json changesets entry {i}"
    cs_id = entry["id"]
    if isinstance(cs_id, bool):
        valid = False
    elif isinstance(cs_id, int):
        valid = True
    elif isinstance(cs_id, str):
        valid = cs_id.isdigit()
        if valid:
            cs_id = int(cs_id)
    else:
        valid = False
    if not valid:
        raise ValueError(f"{where} has invalid id: {entry['id']!r}")
    entry["id"] = cs_id

    ts = entry.get("created_at")
    if ts and not (isinstance(ts, str) and _parseable_timestamp(ts)):
        raise ValueError(f"{where} contains an incorrectly formatted "
                             f"created_at value: {ts!r}")

    if "user" in entry:
        if not isinstance(entry["user"], str):
            raise ValueError(f"{where} has a non-string user: "
                                 f"{entry['user']!r}")
        _reject_lone_surrogates(where, "user", entry["user"])

    if "tags" in entry and not isinstance(entry["tags"], dict):
        raise ValueError(f"{where} The 'tags' field requires a JSON object "
                             "format")
    tags = entry.get("tags")
    if tags is not None:
        if "created_by" in tags:
            if not isinstance(tags["created_by"], str):
                raise ValueError(f"{where} the field 'tags.created_by' "
                                     "requires a string value")

        # `classify_quest` returns the first truthy quest_type-containing tag
        # value containing `quest_type` without modification. We need to
        # enforce strings here because non-string types break `Counter` keys
        # and cause `k.replace` to fail during template rendering.
        #
        # Upstream logic filters out falsy values using `and v`, so those
        # values and non-quest_type keys that don't contain `quest_type` remain
        # accepted regardless of their JSON type.
        for k, v in tags.items():
            if "quest_type" in k:
                if v and not isinstance(v, str):
                    raise ValueError(f"{where} expected a string for 'tags."
                                         f"{k}'")
                # Jinja renders `quest_type` strings as raw text in the Quest
                # Types breakdown. The call to `_reject_lone_surrogates`
                # provides the same guard used for other rendered fields.
                _reject_lone_surrogates(where, f"tags.{k}", v)

    for field in _BBOX_FIELDS:
        v = entry.get(field)
        # `markers.py` wraps bbox bounds in `float()`, so this check mirrors
        # that coercion. Any value that survives `float(str(v))` counts as
        # numeric there, and bools also count as numeric (`float(True)==1.0`).
        # Strings remain accepted per the round-8 F5 ruling.
        if v is not None and not isinstance(v, bool):
            try:
                float(str(v))
            except ValueError:
                raise ValueError(f"{where} has non-numeric {field}: {v!r}")

    # Centroids in markers.py call float() on each bbox bound after the bbox is
    # set. A missing max_* or min_lon causes a crash with float(None), though a
    # missing min_* might be skipped by the None guard in markers, which makes
    # the crash path-dependent. The round() function dereferences elem_lat and
    # elem_lon pairs together.
    #
    # These behaviors require either all four bbox bounds or none at all, and
    # both element position fields or neither.
    bbox_absent = [f for f in _BBOX_FIELDS if entry.get(f) is None]
    if bbox_absent and len(bbox_absent) < 4:
        present = [f for f in _BBOX_FIELDS if entry.get(f) is not None]
        raise ValueError(
            f"{where} incomplete bounding box: fields {', '.join(present)} "
                f"exist but {', '.join(bbox_absent)} are missing"
        )
    has_lat = entry.get("elem_lat") is not None
    has_lon = entry.get("elem_lon") is not None
    if has_lat != has_lon:
        solo = "elem_lat" if has_lat else "elem_lon"
        partner = "elem_lon" if has_lat else "elem_lat"
        raise ValueError(
            f"{where} incomplete coordinates: {solo} exists but {partner} is "
                "missing"
        )

    # `markers.py` calls `round()` directly on `elem_lat` and `elem_lon` pairs
    # during the `quest_type` fallback and on the legacy single-element cache
    # path. The marker build crashes when it encounters numeric strings because
    # these fields lack the `float()` wrapping used for bbox bounds. Since
    # `bool` inherits from `int`, `round(True, 6)` succeeds, so booleans remain
    # accepted under the round-8 F5 bool ruling.
    for field in ("elem_lat", "elem_lon"):
        v = entry.get(field)
        if v is not None and not isinstance(v, (int, float)):
            raise ValueError(f"{where} has non-numeric {field}: {v!r}")

    # When `markers.py` walks `all_elem_geoms` using `.get()`, any truthy
    # object that lacks a mapping interface triggers an `AttributeError`. For
    # quest element entries, the code reads the `lon` key unconditionally once
    # `lat` exists--which causes a `KeyError` if `lon` is missing--and calls
    # `round()` on both values without checks. The process remains inert if the
    # value dict lacks a `lat` or contains a null one.
    #
    # We accept falsy containers because the consumer uses `cs.get(...) or {}`
    # to coalesce them into empty dicts. This matches the round-8 F6 ruling
    # treating falsy values as empty.
    geoms = entry.get("all_elem_geoms")
    if geoms:
        if not isinstance(geoms, dict):
            raise ValueError(f"{where} the 'all_elem_geoms' field requires a "
                                 "JSON object")
        for gid, g in geoms.items():
            if not isinstance(g, dict):
                raise ValueError(
                    f"{where} the 'all_elem_geoms' item {gid!r} is required "
                        "to be a JSON object"
                )
            if g.get("lat") is not None:
                for coord in ("lat", "lon"):
                    cv = g.get(coord)
                    if cv is None:
                        raise ValueError(
                            f"{where} 'all_elem_geoms' item {gid!r} contains "
                                "'lat' but lacks 'lon'"
                        )
                    if not isinstance(cv, (int, float)):
                        raise ValueError(
                            f"{where} 'all_elem_geoms' item {gid!r} contains "
                                f"a non-number at {coord!r}: {cv!r}"
                        )
