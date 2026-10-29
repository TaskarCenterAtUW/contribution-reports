"""Tests for render and fetch behavior that lock implementation details from the
slop-cleanup pass.
"""

from contribution_reports import fetch, render



# We test whether `render.filter_app_changesets` drops entries that lack a
# usable `created_by` value, which verifies the interaction between edges and
# `app_filter` threading.
def test_filter_app_changesets_drops_entries_lacking_usable_created_by():
    keep = {"id": 3, "tags": {"created_by": "GIG 1"}}
    dropped = [
        {"id": 1},  # no tags key
        {"id": 2, "tags": {}},  # tags without created_by
    ]
    assert render.filter_app_changesets(dropped + [keep]) == [keep]


def test_filter_app_changesets_returns_new_list_when_disabled():
    items = [{"id": 1, "tags": {"created_by": "Rapid 2"}}]
    out = render.filter_app_changesets(items, ())
    assert out == items
    assert out is not items


def _minimal_ws(ws_id=7, title="WS"):
    return {"id": ws_id, "title": title, "changesets": [], "notes": []}


def test_render_report_passes_app_filter_to_filter_and_window(tmp_path, monkeypatch):
    seen_filter, seen_window = [], []
    monkeypatch.setattr(
        render,
        "filter_app_changesets",
        lambda cs, app_filter=None: seen_filter.append(app_filter) or list(cs),
    )
    monkeypatch.setattr(
        render,
        "find_event_window",
        lambda cs, app_filter=None: seen_window.append(app_filter) or None,
    )
    data = {"date": "2026-06-01", "workspaces": {"7": _minimal_ws()}}

    render.render_report(data, tmp_path / "r1.html", app_filter=("Xyz",))
    assert seen_filter == [("Xyz",)]
    assert seen_window == [("Xyz",)]  # apply_window defaults True

    render.render_report(
        data, tmp_path / "r2.html", apply_window=False, app_filter=("Xyz",)
    )
    assert len(seen_filter) == 2
    assert len(seen_window) == 1  # No window call when `apply_window=False`


def test_header_joins_multiple_workspace_names_and_escapes_each(tmp_path):
    data = {
        "date": "2026-06-01",
        "workspaces": {
            "1": _minimal_ws(1, "A & B"),
            "2": _minimal_ws(2, "C"),
        },
    }
    out = tmp_path / "r.html"
    render.render_report(data, out)
    html = out.read_text(encoding="utf-8")
    assert "A &amp; B" in html
    # We join the separator as Markup, so it remains a raw entity run--it never
    # double-escapes to &amp;nbsp;.
    assert " &nbsp;·&nbsp; " in html
    assert "&amp;nbsp;" not in html


def test_falsy_workspace_dates_do_not_poison_header_range(tmp_path):
    # We have one dated workspace and one workspace that lacks an archive and
    # contains an empty summary date. The empty entry must not crash the range
    # calculation via fromisoformat("") or trigger the Unknown-date fallback.
    data = {
        "date": "",
        "workspaces": {
            "1": {
                "id": 1,
                "title": "Dated",
                "event_date": "2026-06-01",
                "changesets": [],
                "notes": [],
            },
            "2": _minimal_ws(2, "Undated"),
        },
    }
    out = tmp_path / "r.html"
    render.render_report(data, out)
    html = out.read_text(encoding="utf-8")
    assert "June 1, 2026" in html
    assert "Unknown date" not in html


# fetch.py delta branches
def test_version_one_fetch_prev_tags_gives_empty_dict_with_invalid_id(monkeypatch):
    # We hit the version<=1 branch before the numeric-id guard checks the ID.
    # In this case, the function returns {} to indicate all tags are new
    # instead of returning None as a fetch-failure sentinel.
    def _boom(*args, **kwargs):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert fetch.fetch_prev_tags("http://osm.test", 1, "way", "not-a-number", 1) == {}


def test_enrich_with_prev_tags_skips_non_numeric_ids(monkeypatch, capsys):
    entry = {"osc_xml": "<osmChange/>"}
    midpoint_calls = []
    monkeypatch.setattr(
        fetch,
        "_extract_quest_element_info",
        lambda osc_xml, quest_index: ("way", "bad id", 2),
    )
    monkeypatch.setattr(fetch, "fetch_prev_tags", lambda *a, **k: {})
    monkeypatch.setattr(
        fetch,
        "_extract_all_quest_elements",
        lambda osc_xml, quest_index: [
            ("way", "bad id", None, {}),
            ("way", "42", None, {}),
        ],
    )

    def fake_midpoint(osm_url, ws_id, elem_id, token=None):
        midpoint_calls.append(elem_id)
        return (10.0, 20.0), [[10.0, 20.0]]

    monkeypatch.setattr(fetch, "fetch_way_midpoint", fake_midpoint)

    fetch.enrich_with_prev_tags(entry, "http://osm.test", 1, {})

    assert midpoint_calls == ["42"]
    assert set(entry["all_elem_geoms"]) == {"42"}
    assert entry["elem_type"] == "way"
    assert entry["elem_id"] == "bad id"
    assert entry["elem_version"] == 2
    assert entry["prev_tags"] == {}
    # Flat fields from the legacy system point to the first element only after
    # we fetch its geometry. Because we skipped a bad ID, these fields remain
    # unset.
    assert (
        "elem_lat" not in entry and "elem_lon" not in entry and "elem_geom" not in entry
    )
    out = capsys.readouterr().out
    assert "WARNING" in out and "bad id" in out
