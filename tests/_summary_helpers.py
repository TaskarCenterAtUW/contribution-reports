"""Provides shared builders for tests that verify contribution summaries."""

import json
from pathlib import Path

from contribution_reports.summary import EventStats



QUEST_DEF_SIDEWALK = {
    "elements": [
        {
            "element_type": "Sidewalks",
            "quests": [
                {
                    "quest_tag": "ext:surface_quality",
                    "quest_title": "Surface quality",
                    "quest_answer_choices": [],
                }
            ],
        }
    ],
}


EVENT_A = {
    "slug": "a",
    "title": "Event A",
    "use_window": True,
    "city": "A City, WA",
    "lat": 47.6,
    "lon": -122.3,
}


EVENT_B = {
    "slug": "b",
    "title": "Event B",
    "use_window": False,
    "city": "B City, WA",
    "lat": 48.0,
    "lon": -122.2,
}


def quest_cs(cs_id, user, ts, quest_def=QUEST_DEF_SIDEWALK):
    """Returns a single changeset that satisfies one quest by tagging one node.
    """
    tag = quest_def["elements"][0]["quests"][0]["quest_tag"]
    osc = (
        f'<osm><modify><node id="{cs_id}" version="1" changeset="{cs_id}" '
        f'lat="47.6" lon="-122.3"><tag k="{tag}" v="poor"/></node>'
        f"</modify></osm>"
    )
    return {
        "id": cs_id,
        "user": user,
        "created_at": ts,
        "changes_count": 1,
        "tags": {"created_by": "GIG 1.2.2(1)"},
        "osc_xml": osc,
    }


def create_cs(cs_id, user, ts):
    """Generates a single changeset that adds one tagged node for
    feature-creation.
    """
    osc = (
        f'<osm><create><node id="{cs_id}" version="1" changeset="{cs_id}" '
        f'lat="47.61" lon="-122.31">'
        f'<tag k="ext:surface_quality" v="good"/></node></create></osm>'
    )
    return {
        "id": cs_id,
        "user": user,
        "created_at": ts,
        "changes_count": 1,
        "tags": {"created_by": "GIG 1.2.2(1)"},
        "osc_xml": osc,
    }


def write_cache(
    cache_dir: Path, slug: str, changesets, notes=None, quest_def=QUEST_DEF_SIDEWALK
):
    ws = {
        "id": 1,
        "title": f"Workspace {slug}",
        "quest_definition": quest_def,
        "changesets": changesets,
        "notes": notes or [],
    }
    path = cache_dir / f"changesets_{slug}.json"
    path.write_text(
        json.dumps({"date": "2026-05-19", "workspaces": {"1": ws}}), encoding="utf-8"
    )
    return path


def _stats(title, dmin, quests, notes, contributors, mix=None, features=0):
    return EventStats(
        title=title,
        city=title,
        lat=47.0,
        lon=-122.0,
        quests=quests,
        notes=notes,
        contributors=set(contributors),
        element_mix=dict(mix or {}),
        features=features,
        date_min=dmin,
        date_max=dmin,
    )
