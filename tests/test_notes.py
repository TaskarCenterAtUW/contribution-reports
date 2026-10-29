from contribution_reports.analysis import analyse
from contribution_reports.classify import split_note_photos
from contribution_reports.render import _build_section_context

CDN = "https://cdn.kartaview.org/pr:sharp/"
PHOTO_A = CDN + "aHR0cHM6Ly9leGFtcGxlLm9yZy9hLmpwZWc"
PHOTO_B = CDN + "aHR0cHM6Ly9leGFtcGxlLm9yZy9iLmpwZWc"


def changeset(cs_id, user):
    return {"id": cs_id, "user": user, "changes_count": 1, "tags": {}, "osc_xml": ""}


def test_split_note_photos_removes_trailing_urls():
    text, photos = split_note_photos(f"No sidewalk here. \n\n{PHOTO_A}\n{PHOTO_B}")
    assert text == "No sidewalk here."
    assert photos == [PHOTO_A, PHOTO_B]


def test_split_note_photos_returns_list_from_comma_separated_urls():
    _, photos = split_note_photos(f"Curb\n{PHOTO_A},{PHOTO_B}")
    assert photos == [PHOTO_A, PHOTO_B]


def test_split_note_photos_normalizes_legacy_urls():
    _, photos = split_note_photos("Ramp https://api.openstreetcam.org/files/photo/1.jpg")
    assert photos == [CDN + "aHR0cHM6Ly9hcGkub3BlbnN0cmVldGNhbS5vcmcvZmlsZXMvcGhvdG8vMS5qcGc"]


def test_split_note_photos_does_not_remove_non_photo_urls_from_text():
    text, photos = split_note_photos("See https://example.org/plan")
    assert text == "See https://example.org/plan"
    assert photos == []


def test_split_note_photos_ignores_urls_followed_by_text():
    text, photos = split_note_photos(f"{PHOTO_A} is the corner")
    assert text == f"{PHOTO_A} is the corner"
    assert photos == []


def test_split_note_photos_returns_empty_text_when_note_contains_only_photos():
    assert split_note_photos(PHOTO_A) == ("", [PHOTO_A])


def test_analyse_counts_notes_per_contributor():
    stats = analyse(
        [changeset(1, "Ana"), changeset(2, "Bo")],
        {},
        notes=[
            {"lat": 0, "lon": 0, "text": "a", "user": "Ana"},
            {"lat": 0, "lon": 0, "text": "b", "user": "Cy"},
            {"lat": 0, "lon": 0, "text": "c", "user": "Cy"},
        ],
    )
    assert stats["users"] == {"Cy": 2, "Ana": 2, "Bo": 1}
    assert stats["total"] == 2


def test_analyse_skips_notes_without_author():
    stats = analyse([changeset(1, "Ana")], {}, notes=[{"lat": 0, "lon": 0, "text": "a"}])
    assert stats["users"] == {"Ana": 1}


def test_analyse_credits_note_photos_to_author():
    stats = analyse([], {}, notes=[{"lat": 0, "lon": 0, "text": f"x\n{PHOTO_A}", "user": "Ana"}])
    assert stats["user_photo_urls"] == {"Ana": [PHOTO_A]}


def test_note_markers_include_author_and_photos():
    ctx = _build_section_context(
        "WS", [], {}, {},
        [{"lat": 1.0, "lon": 2.0, "text": f"No ramp\n{PHOTO_A}", "user": "Ana"}],
        None, [0],
    )
    [marker] = [m for m in ctx["all_map_data"] if m["kind"] == "note"]
    assert marker == {
        "lat": 1.0, "lon": 2.0, "kind": "note",
        "text": "No ramp", "user": "Ana", "photos": [PHOTO_A],
    }


def note_point(text):
    return {"lat": 1.0, "lon": 2.0, "kind": "note", "weight": -0.5, "text": text}


def test_issue_note_evidence_extracts_photos():
    issue = {
        "rank": 1, "sign": "problem", "combined_score": -0.5,
        "segment": {"name": "Main St"},
        "note_evidence": [{"text": f"No ramp\n{PHOTO_A}", "score": -0.5}],
        "evidence_points": [note_point(f"No ramp\n{PHOTO_A}"), {"kind": "quest", "tags": []}],
    }
    ctx = _build_section_context("WS", [], {}, {}, [], None, [0], issues=[issue])
    [problem] = ctx["problems"]
    assert problem["note_evidence"][0]["text"] == "No ramp"
    assert problem["note_evidence"][0]["photos"] == [PHOTO_A]
    assert problem["evidence_points"][0]["photos"] == [PHOTO_A]
    assert "photos" not in problem["evidence_points"][1]
    [issue_data] = ctx["all_issues_data"]
    assert issue_data["note_evidence"][0]["photos"] == [PHOTO_A]
    assert issue["note_evidence"][0]["text"] == f"No ramp\n{PHOTO_A}"


def test_hotspot_collects_photos_from_note_points():
    hotspot = {
        "rank": 1, "centroid": [1.0, 2.0], "label": "x",
        "evidence_points": [note_point(f"a\n{PHOTO_A}"), note_point(f"b\n{PHOTO_B}\n{PHOTO_A}")],
    }
    ctx = _build_section_context("WS", [], {}, {}, [], None, [0], hotspots=[hotspot])
    [h] = ctx["hotspots"]
    assert [p["text"] for p in h["evidence_points"]] == ["a", "b"]
    assert h["photos"] == [PHOTO_A, PHOTO_B]
    assert ctx["all_hotspots_data"][0]["photos"] == [PHOTO_A, PHOTO_B]


def test_hotspot_label_snippet_omits_photo_urls():
    from contribution_reports.hotspots import _derive_label

    label = _derive_label([{"kind": "note", "detail": {"text": f"Cracked\n{PHOTO_A}"}}])
    assert label == '"Cracked"'
