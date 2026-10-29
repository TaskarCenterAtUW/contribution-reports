"""Deterministic rules for analyzing OSW data state.

We maintain distinct families of rules, deliberately kept apart. Conformance
flags identify where data violates the schema. Network findings assume the data
accurately represents the world, but note that the described environment
warrants attention from a lead.
"""

from collections import Counter
from dataclasses import dataclass, field

from .schema import ATTRIBUTES, classify_tags
from .state import live_elements

FAMILY_CONFORMANCE = "conformance"
FAMILY_NETWORK = "network"

MAX_SAMPLES = 20


@dataclass
class Finding:
    id: str
    family: str
    severity: str  # we choose from `error`, `warning`, or `info`
    title: str
    message: str
    count: int
    total: int
    samples: list = field(default_factory=list)


def _classified(final: dict):
    """Yields a tuple containing the key, entity, and tags for each element that
    is live and has an OSW classification.
    """
    for key, record in live_elements(final).items():
        entity = classify_tags(record["tags"])
        if entity is not None:
            yield key, entity, record["tags"]


def _finding(rule_id, family, severity, title, message, hits, total, max_samples):
    return Finding(id=rule_id, family=family, severity=severity, title=title,
                   message=message, count=len(hits), total=total,
                   samples=hits[:max_samples])


def _rule_width_placeholder(rows, max_samples):
    spec = ATTRIBUTES["width"]
    populated, hits = [], []
    for key, _entity, tags in rows:
        value = tags.get("width")
        if value in (None, ""):
            continue
        populated.append(key)
        if value.strip() in spec.placeholders:
            hits.append(key)
    if not hits:
        return None
    # We claim coverage is 0% only when all populated widths are placeholders.
    # In other cases we need to state coverage proportionally.
    #
    # We changed this because the old code reported 0% unconditionally and
    # divided by all classified rows. That included node-only entities like
    # Curb Ramp that never carry a width, so the resulting coverage percentage
    # had no meaning.
    if len(hits) == len(populated):
        message = (
            f"{len(hits)} of {len(populated)} populated width values are the "
            f"placeholder 0.0 — every recorded width is a placeholder, so "
            f"effective width coverage is 0%."
        )
    else:
        remaining = len(populated) - len(hits)
        message = (
            f"{len(hits)} of {len(populated)} populated width values are the "
            f"placeholder 0.0; the remaining {remaining} are genuinely "
            f"measured."
        )
    return _finding(
        "width-placeholder", FAMILY_CONFORMANCE, "warning",
        "Width values are placeholders",
        message,
        hits, len(populated), max_samples)


def _rules_enum_off_schema(rows, max_samples):
    """Reports errors when enum attributes contain values that violate their
    schema definitions.

    For each attribute in `ATTRIBUTES` that has a kind of `"enum"` and contains
    defined values, we check every row. If the attribute's value is present and
    not empty but falls outside the expected set, we record it as an offender.

    Where these violations occur, we generate a finding with the ID
    `enum-off-schema:{attr}` and the `FAMILY_CONFORMANCE` family. The finding
    includes the total count of populated values, the count of violators, and a
    list of the five most common offending values.
    """
    results = []
    for attr, spec in sorted(ATTRIBUTES.items()):
        if spec.kind != "enum" or not spec.values:
            continue
        hits, offenders, total = [], Counter(), 0
        for key, _entity, tags in rows:
            value = tags.get(attr)
            if value in (None, ""):
                continue
            total += 1
            if value not in spec.values:
                hits.append(key)
                offenders[value] += 1
        if not hits:
            continue
        listed = ", ".join(f"{v} ×{n}" for v, n in offenders.most_common(5))
        results.append(_finding(
            f"enum-off-schema:{attr}", FAMILY_CONFORMANCE, "error",
            f"{attr} values outside the OSW schema",
            f"{len(hits)} of {total} populated {attr} values are outside the "
            f"enum the OpenSidewalks schema defines: {listed}.",
            hits, total, max_samples))
    return results


def _rule_steps_no_count(rows, max_samples):
    steps = [(k, t) for k, e, t in rows if e.name == "Steps"]
    hits = [k for k, t in steps if not t.get("step_count")]
    if not hits:
        return None
    return _finding(
        "steps-no-count", FAMILY_CONFORMANCE, "warning",
        "Steps without a step count",
        f"{len(hits)} of {len(steps)} step features have no step_count.",
        hits, len(steps), max_samples)


def _rule_crossing_unmarked(rows, max_samples):
    crossings = [(k, t) for k, e, t in rows if e.name == "Crossing"]
    hits = [k for k, t in crossings if t.get("crossing:markings") == "no"]
    if not hits:
        return None
    return _finding(
        "crossing-unmarked", FAMILY_NETWORK, "info",
        "Crossings recorded as unmarked",
        f"{len(hits)} of {len(crossings)} crossings are explicitly "
        f"crossing:markings=no.",
        hits, len(crossings), max_samples)


def _rule_curb_type_mix(rows, max_samples):
    curbs = [(k, e.name) for k, e, _t in rows if e.name.endswith("Curb")
             or e.name == "Curb Ramp"]
    if not curbs:
        return None
    mix = Counter(name for _k, name in curbs)
    listed = " · ".join(f"{name} {n}" for name, n in mix.most_common())
    return _finding(
        "curb-type-mix", FAMILY_NETWORK, "info",
        "Curb type distribution",
        f"Curb types across {len(curbs)} touched curb features recognized by "
        f"the OpenSidewalks schema (barrier=kerb + a kerb value): {listed}. "
        f"Elements tagged only kerb=* without barrier=kerb are not schema "
        f"curbs and are not counted here — see the non-OSW-tagged elements "
        f"noted above.",
        [k for k, _ in curbs], len(curbs), max_samples)


def evaluate(final: dict, max_samples: int = MAX_SAMPLES) -> list:
    """Applies every rule to the live, classified elements in *final*.

    We pass these elements along with `max_samples` to each rule, collecting
    results that are not `None`. We then sort the findings by severity
    according to the order of error, warning, and info, with higher counts
    breaking ties within each severity level.
    """
    rows = list(_classified(final))
    findings: list = []
    for rule in (_rule_width_placeholder, _rule_steps_no_count,
                 _rule_crossing_unmarked, _rule_curb_type_mix):
        result = rule(rows, max_samples)
        if result is not None:
            findings.append(result)
    findings.extend(_rules_enum_off_schema(rows, max_samples))

    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order.get(f.severity, 3), -f.count))
    return findings
