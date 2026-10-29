"""Half B - the final OSW data state for each element that was touched."""

from collections import Counter, defaultdict

from .adiff import effective_tags, own_actions
from .changes import CLASS_IMPORT, classify_changeset
from .schema import classify_tags


def final_elements(changesets: list, adiffs: dict,
                   include_baseline: bool = False) -> dict:
    """Folds each counted action into the most recent state of every element.

    We return a dict where keys are `(elem_type, elem_id)` and values are
    `{"tags", "version", "deleted"}`. We keep deleted elements to preserve the
    distinction between live and touched elements.
    """
    included = [cs for cs in changesets
                if include_baseline or classify_changeset(cs) != CLASS_IMPORT]

    final: dict = {}
    for cs in sorted(included, key=lambda c: c["id"]):
        cs_id = cs["id"]
        for action in own_actions(adiffs.get(str(cs_id), []), cs_id):
            element = action["new"]
            key = (element.get("type", "node"), element.get("id"))
            version = element.get("version", 0)
            previous = final.get(key)
            if previous is not None and previous["version"] > version:
                continue
            final[key] = {
                "tags": effective_tags(action),
                "version": version,
                "deleted": action["type"] == "delete",
            }
    return final


def live_elements(final: dict) -> dict:
    """Returns a subset of *final* containing only elements where the `deleted`
    key is false.
    """
    return {k: v for k, v in final.items() if not v["deleted"]}


def _coverage_status(pct: float) -> str:
    """Maps a coverage percentage to a status bucket that matches the completeness
    bar colors. This ensures the individual attribute bars and the per-entity
    `status_counts` summary remain synchronized.
    """
    if pct >= 90:
        return "good"
    if pct >= 40:
        return "fair"
    return "poor"


def build_state(final: dict) -> dict:
    """Group live elements by OSW entity and measure attribute completeness.

    The denominator is touched-and-live elements, not the whole dataset; the
    renderer labels it so a 100% figure is never read as city-wide coverage.
    """
    live = live_elements(final)
    grouped: dict = defaultdict(list)
    for record in live.values():
        entity = classify_tags(record["tags"])
        if entity is not None:
            grouped[entity].append(record["tags"])

    entities: dict = {}
    for entity, tagsets in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        total = len(tagsets)
        coverage: dict = {}
        distributions: dict = {}
        for attr in entity.attrs:
            values = [t[attr] for t in tagsets if t.get(attr) not in (None, "")]
            pct = round(100 * len(values) / total, 1) if total else 0.0
            coverage[attr] = {
                "have": len(values),
                "total": total,
                "pct": pct,
                "status": _coverage_status(pct),
            }
            if values:
                distributions[attr] = dict(Counter(values).most_common())
        status_counts = Counter(cov["status"] for cov in coverage.values())
        entities[entity.name] = {
            "name": entity.name, "count": total,
            "coverage": coverage, "distributions": distributions,
            "status_counts": dict(status_counts),
        }

    return {"entities": entities, "touched": len(final), "live": len(live)}
