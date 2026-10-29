"""An edit ledger that tracks what changed and identifies the authors of those
changes.
"""

from collections import Counter, defaultdict

from .adiff import effective_tags, geometry_of, own_actions
from .schema import (
    BUCKET_ENTITY, BUCKET_NON_OSW, BUCKET_UNTAGGED_WAY, BUCKET_VERTEX,
    bucket_for, core_tags,
)

CLASS_IMPORT = "baseline_import"
CLASS_APP = "survey_app"
CLASS_EDITOR = "editor"

IMPORT_CREATED_BY = "TDEI Workspaces"
APP_CREATED_BY_PREFIXES = ("AVIV ScoutRoute", "GIG", "GoInfoGame")


def classify_changeset(cs: dict) -> str:
    """Partitions a changeset by provenance.

    We report provenance instead of filtering it because an always-on app
    filter in the quest report would exclude all changesets within an
    editor-driven workspace.
    """
    created_by = cs.get("tags", {}).get("created_by", "")
    if created_by == IMPORT_CREATED_BY:
        return CLASS_IMPORT
    if created_by.startswith(APP_CREATED_BY_PREFIXES):
        return CLASS_APP
    return CLASS_EDITOR


def diff_tags(old: dict, new: dict) -> tuple:
    """Returns a tuple containing added, changed, and removed items; the changed
    collection maps keys to a pair of old and new values.
    """
    added = {k: v for k, v in new.items() if k not in old}
    changed = {k: (old[k], v) for k, v in new.items() if k in old and old[k] != v}
    removed = {k: v for k, v in old.items() if k not in new}
    return added, changed, removed


def geometry_changed(action: dict) -> bool:
    """Returns True if the element owns geometry that changed.

    For ways, we compare node `ref` lists instead of inline coordinates. In
    OSM, moving a node increments that node's version and not its parent way's,
    so a child's movement already appears as a modify action for that node
    elsewhere in the adiff. We found that the `old` side of the adiff preserves
    previous inline coordinates (we verified this using workspace 1280: among
    way-modifies with unchanged ref lists, 890 have identical coordinates while
    220 differ), so comparing coordinates would be reliable despite what
    earlier comments claimed. We still prefer ref lists to avoid
    double-counting: those 220 cases involved nodes edited within the same
    changeset, so tracking coordinate drift on the way would count the same
    geometry change twice--first for the node and again for the way. Since
    nodes lack ref lists, we compare lat/lon directly because they own no other
    geometry and have no child actions to double-count.
    """
    old = action.get("old")
    if not old:
        return False
    new = action["new"]
    if new.get("type") == "way":
        old_refs = [n["ref"] for n in (old.get("nodes") or [])]
        new_refs = [n["ref"] for n in (new.get("nodes") or [])]
        return old_refs != new_refs
    return (old.get("lat"), old.get("lon")) != (new.get("lat"), new.get("lon"))


def modify_kind(action: dict) -> str:
    """Classifies a modify action as `geometry_only`, `tags_only`, `both`, or
    `no_op`.

    We use this distinction to separate high-level change counts from more
    descriptive work, such as stating that two thirds of the effort involved
    aligning geometry to imagery instead of merely reporting "42,443 changes".
    """
    old_tags = (action.get("old") or {}).get("tags") or {}
    new_tags = action["new"].get("tags") or {}
    added, changed, removed = diff_tags(old_tags, new_tags)
    tags_touched = bool(added or changed or removed)
    geom_touched = geometry_changed(action)
    if tags_touched and geom_touched:
        return "both"
    if tags_touched:
        return "tags_only"
    if geom_touched:
        return "geometry_only"
    return "no_op"


def _new_contributor() -> dict:
    return {"changesets": 0, "actions": 0, "active_days": 0, "days": set(),
            "first_edit": None, "last_edit": None,
            "kinds": Counter(), "actions_by_type": Counter()}


def _tag_signature(tags: dict) -> str:
    """Generates an order-independent, compact label for a set of tags.

    Examples include ``kerb=no`` or ``barrier=fence,surface=paved``.

    We use this label to reveal what makes up the non-OSW-feature bucket
    instead of reporting just a total. Without it, a reader cannot distinguish
    between "924 non-OSW features" and "924 mislabelled curbs".
    """
    core = core_tags(tags)
    return ",".join(f"{k}={v}" for k, v in sorted(core.items())) or "(no tags)"


def _record_attr_delta(entity, key: str, kind: str, attr_deltas: dict,
                       osw_attr_deltas: dict, other_tag_deltas: dict) -> None:
    """Increments a tag delta count in both a combined table and a specific
    partition. The partition separates OSW attributes defined in `entity.attrs`
    from other identifying or classifying tags, such as `highway` or `footway`
    for a Sidewalk, which exist outside the OSW attribute set.
    """
    attr_deltas[entity.name][key][kind] += 1
    target = osw_attr_deltas if key in entity.attrs else other_tag_deltas
    target[entity.name][key][kind] += 1


def build_ledger(changesets: list, adiffs: dict, include_baseline: bool = False) -> dict:
    """Aggregates all counted actions into the Half A panels.

    We only count actions where the changeset is the author (Rule A). The
    process reconciles the outcome against `changes_count` on a **per
    changeset** basis (Rule B) so that one changeset under-counting cannot
    offset another that over-counts within a global total.
    """
    provenance = defaultdict(list)
    for cs in changesets:
        provenance[classify_changeset(cs)].append(cs)

    included = list(provenance[CLASS_EDITOR]) + list(provenance[CLASS_APP])
    if include_baseline:
        included += list(provenance[CLASS_IMPORT])

    contributors: dict = defaultdict(_new_contributor)
    timeline: dict = defaultdict(Counter)
    by_entity: dict = defaultdict(Counter)
    modify_kinds: Counter = Counter()
    attr_deltas: dict = defaultdict(lambda: defaultdict(Counter))
    osw_attr_deltas: dict = defaultdict(lambda: defaultdict(Counter))
    other_tag_deltas: dict = defaultdict(lambda: defaultdict(Counter))
    value_flips: dict = defaultdict(Counter)
    buckets: Counter = Counter({BUCKET_ENTITY: 0, BUCKET_VERTEX: 0,
                                BUCKET_NON_OSW: 0, BUCKET_UNTAGGED_WAY: 0})
    non_osw_signatures: Counter = Counter()
    geometry: list = []
    counted = expected = 0
    mismatches: list = []

    for cs in sorted(included, key=lambda c: c["id"]):
        cs_id = cs["id"]
        cs_expected = cs.get("changes_count", 0)
        cs_counted = 0
        expected += cs_expected
        day = (cs.get("created_at") or "")[:10]
        user = cs.get("user", "unknown")

        stats = contributors[user]
        stats["changesets"] += 1
        stamp = cs.get("created_at")
        if day:
            stats["days"].add(day)
        if stamp:
            for field, keep in (("first_edit", min), ("last_edit", max)):
                current = stats[field]
                stats[field] = stamp if current is None else keep(current, stamp)

        for action in own_actions(adiffs.get(str(cs_id), []), cs_id):
            counted += 1
            cs_counted += 1
            action_type = action["type"]
            element = action["new"]

            stats["actions"] += 1
            stats["actions_by_type"][action_type] += 1
            if day:
                timeline[day][action_type] += 1

            tags = effective_tags(action)
            bucket, entity = bucket_for(element.get("type", "node"), tags)
            buckets[bucket] += 1
            if bucket == BUCKET_NON_OSW:
                # We track this group when tags exist but no OSW entity
                # matches. For instance, we might have a bare kerb=no without a
                # barrier=kerb. This lets the report detail these elements
                # instead of showing only a total.
                non_osw_signatures[_tag_signature(tags)] += 1

            if entity is not None:
                by_entity[entity.name][action_type] += 1

            if action_type == "modify":
                # We use raw tags in `modify_kind()` so that an element
                # changing only an `ext:osm_version` tag reports as
                # `tags_only`. This prevents the classification from silently
                # downgrading to `no_op` or `geometry_only`.
                #
                # We need to keep `ext:` tags intact before calling this
                # function.
                kind = modify_kind(action)
                modify_kinds[kind] += 1
                stats["kinds"][kind] += 1
                # We use `core_tags` to strip provenance tags prefixed with
                # `ext:` (such as `ext:osm_version` and `ext:sw_id`) because
                # `attr_deltas` and `value_flips` report OpenSidewalks
                # attribute work. Without this filter, bookkeeping tags from
                # import and export operations swamp the attribute table.
                old_tags = core_tags((action.get("old") or {}).get("tags") or {})
                new_tags = core_tags(element.get("tags") or {})
                added, changed, removed = diff_tags(old_tags, new_tags)
                if entity is not None:
                    # We store all combined core-tag deltas in `attr_deltas`
                    # for readers tracking that key. To distinguish these
                    # events, we partition them between `osw_attr_deltas` and
                    # `other_tag_deltas` based on whether keys exist in
                    # `entity.attrs`.
                    #
                    # Keys that identify or classify an entity--such as
                    # `highway` for a Sidewalk or `barrier`/`kerb` for a
                    # curb--do not count as true OSW attributes. We exclude
                    # these from attribute work because including them roughly
                    # doubled the panel's apparent size. For instance, a Raised
                    # Curb might show 1,783 churn entries for pure
                    # `barrier`/`kerb` tags but 0 real attribute deltas.
                    for key in added:
                        _record_attr_delta(entity, key, "added", attr_deltas,
                                           osw_attr_deltas, other_tag_deltas)
                    for key in changed:
                        _record_attr_delta(entity, key, "changed", attr_deltas,
                                           osw_attr_deltas, other_tag_deltas)
                    for key in removed:
                        _record_attr_delta(entity, key, "removed", attr_deltas,
                                           osw_attr_deltas, other_tag_deltas)
                for key, (old_value, new_value) in changed.items():
                    value_flips[key][f"{old_value} → {new_value}"] += 1
            elif action_type == "create" and entity is not None:
                for key in core_tags(element.get("tags") or {}):
                    _record_attr_delta(entity, key, "added", attr_deltas,
                                       osw_attr_deltas, other_tag_deltas)

            # When we delete a feature, the `new` field contains cleared
            # geometry. We fall back to `old` so the map continues to show the
            # removed features.
            source = (action.get("old") or element) if action_type == "delete" else element
            coords = geometry_of(source)
            if coords:
                geometry.append({
                    "type": element.get("type"), "id": element.get("id"),
                    "action": action_type,
                    "kind": modify_kind(action) if action_type == "modify" else action_type,
                    "entity": entity.name if entity else None,
                    "coords": coords,
                })

        # Rule B applies to each changeset. We'll need to track mismatches
        # individually so that over-counting and under-counting don't cancel
        # each other out in the final totals.
        if cs_counted != cs_expected:
            mismatches.append({"changeset": cs_id, "counted": cs_counted,
                               "expected": cs_expected})

    for stats in contributors.values():
        stats["active_days"] = len(stats["days"])
        del stats["days"]

    return {
        "contributors": dict(sorted(contributors.items(),
                                    key=lambda kv: -kv[1]["actions"])),
        "timeline": {d: dict(c) for d, c in sorted(timeline.items())},
        "by_entity": {e: dict(c) for e, c in sorted(
            by_entity.items(), key=lambda kv: -sum(kv[1].values()))},
        "modify_kinds": dict(modify_kinds),
        "attr_deltas": {e: {a: dict(c) for a, c in attrs.items()}
                        for e, attrs in attr_deltas.items()},
        "osw_attr_deltas": {e: {a: dict(c) for a, c in attrs.items()}
                            for e, attrs in osw_attr_deltas.items()},
        "other_tag_deltas": {e: {a: dict(c) for a, c in attrs.items()}
                             for e, attrs in other_tag_deltas.items()},
        "value_flips": {k: dict(c.most_common()) for k, c in value_flips.items()},
        "buckets": dict(buckets),
        "non_osw_signatures": dict(non_osw_signatures.most_common(6)),
        "provenance": {k: list(v) for k, v in provenance.items()},
        "reconciliation": {"counted": counted, "expected": expected,
                           "ok": not mismatches, "mismatches": mismatches},
        "geometry": geometry,
    }
