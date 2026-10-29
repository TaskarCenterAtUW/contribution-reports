import re

from conftest import make_action, make_element
from contribution_reports.osw.render import build_context, render_report


def workspace_data():
    return {
        "id": 1280, "title": "WSP_Richland_City", "type": "osw",
        "bbox": [-119.36, 46.19, -119.21, 46.36],
        "changesets": [
            {"id": 1, "user": "Importer", "uid": 1,
             "created_at": "2026-03-01T00:00:00Z", "changes_count": 1,
             "tags": {"created_by": "TDEI Workspaces", "workspace": "1280"}},
            {"id": 63, "user": "Mapper", "uid": 341,
             "created_at": "2026-06-01T10:00:00Z", "changes_count": 2,
             "tags": {"created_by": "Rapid 2.5.5", "comment": "fixes",
                      "resolved:disconnected_way:highway": "3",
                      "warnings:ambiguous_crossing:crossing_conflict": "7",
                      "imagery_used": "Esri World Imagery"}},
        ],
        "adiffs": {
            "1": [make_action("create", new=make_element(elem_id=5, changeset=1,
                                                         user="Importer"))],
            "63": [
                make_action("create",
                            new=make_element(elem_id=6, changeset=63,
                                             lat=46.3, lon=-119.2,
                                             tags={"barrier": "kerb",
                                                   "kerb": "lowered",
                                                   "tactile_paving": "no"})),
                make_action("modify",
                            new=make_element("way", elem_id=7, version=2,
                                             changeset=63,
                                             nodes=[{"ref": 1, "lat": 46.3,
                                                     "lon": -119.2}],
                                             tags={"highway": "footway",
                                                   "footway": "sidewalk",
                                                   "surface": "bricks"}),
                            old=make_element("way", elem_id=7, version=1,
                                             changeset=1,
                                             nodes=[{"ref": 1, "lat": 46.3,
                                                     "lon": -119.2}],
                                             tags={"highway": "footway",
                                                   "footway": "sidewalk",
                                                   "surface": "concrete"})),
            ],
        },
        "adiff_failures": {},
    }


def test_context_excludes_baseline_contributors():
    ctx = build_context(workspace_data())
    assert "Importer" not in ctx["ledger"]["contributors"]
    assert "Mapper" in ctx["ledger"]["contributors"]


def test_context_reconciliation_of_counted_actions_succeeds():
    ctx = build_context(workspace_data())
    assert ctx["ledger"]["reconciliation"]["ok"] is True


def test_context_includes_off_schema_surface_finding():
    ctx = build_context(workspace_data())
    assert any(f.id == "enum-off-schema:surface" for f in ctx["findings"])


def test_context_collects_validation_trail():
    ctx = build_context(workspace_data())
    assert ctx["validation"]["resolved"]["disconnected_way:highway"] == 3
    assert ctx["validation"]["outstanding"]["ambiguous_crossing:crossing_conflict"] == 7


def test_context_records_imagery_sources():
    ctx = build_context(workspace_data())
    assert "Esri World Imagery" in ctx["sources"]["imagery_used"]


def test_render_writes_self_contained_html(tmp_path):
    out = tmp_path / "report.html"
    render_report({"workspaces": {"1280": workspace_data()}}, out)
    html = out.read_text()
    assert "<!doctype html>" in html.lower()
    assert "WSP_Richland_City" in html
    assert "Mapper" in html
    # We need to state the denominator instead of leaving it implicit.
    assert "touched" in html.lower()


def test_render_report_shows_reconciliation_failure_details(tmp_path):
    data = workspace_data()
    data["changesets"][1]["changes_count"] = 99
    out = tmp_path / "report.html"
    render_report({"workspaces": {"1280": data}}, out)
    html = out.read_text()
    assert "reconcil" in html.lower()
    # We need to verify that the specific mismatch details per changeset appear
    # in the output instead of only the general reconciliation failure message.
    #
    # For changeset 63, the output should show 2 actions--both being the adiff
    # actions listed above--against the reported count of 99.
    assert "changeset 63: counted 2, expected 99" in html


def test_timeline_bar_heights_scale_against_the_peak_day(tmp_path):
    data = workspace_data()
    # We add a second active day with more activity than the first. This forces
    # `peak` to emerge from a `max()` across multiple days instead of
    # defaulting to the single day in our base fixture.
    #
    # Because every bar measures 100% by construction in that fixture, we need
    # this second day to prevent a broken `day_totals` or `peak` computation
    # from passing anyway.
    data["changesets"].append({
        "id": 64, "user": "Mapper2", "uid": 500,
        "created_at": "2026-06-05T10:00:00Z", "changes_count": 3,
        "tags": {"created_by": "Rapid 2.5.5"},
    })
    data["adiffs"]["64"] = [
        make_action("create", new=make_element(elem_id=10, changeset=64)),
        make_action("create", new=make_element(elem_id=11, changeset=64)),
        make_action("create", new=make_element(elem_id=12, changeset=64)),
    ]
    out = tmp_path / "report.html"
    render_report({"workspaces": {"1280": data}}, out)
    html = out.read_text()

    heights = dict(re.findall(
        r'title="(\d{4}-\d{2}-\d{2})[^"]*">\s*'
        r'<div class="timeline-stack" style="height:(\d+)%"',
        html,
    ))
    # We have 2 actions on 2026-06-01 and 3 actions on 2026-06-05, which
    # represents the peak. Because we scale daily totals against that peak, the
    # heights need to differ so the busier date reaches 100%.
    assert heights == {"2026-06-01": "67", "2026-06-05": "100"}
    assert heights["2026-06-01"] != heights["2026-06-05"]


def test_render_includes_activity_timeline(tmp_path):
    out = tmp_path / "report.html"
    render_report({"workspaces": {"1280": workspace_data()}}, out)
    html = out.read_text()
    assert "timeline-stack" in html
    assert "2026-06-01" in html


def test_render_includes_methodology_modal(tmp_path):
    out = tmp_path / "report.html"
    render_report({"workspaces": {"1280": workspace_data()}}, out)
    html = out.read_text()
    assert "osw-method-btn" in html
    assert "Methodology" in html
    # The modal explains the two different counting units.
    assert "distinct elements" in html


def test_render_labels_dataset_scope_when_extract_supplied(tmp_path):
    extract = {("node", 1): {"tags": {"barrier": "kerb", "kerb": "lowered"},
                             "version": 1, "deleted": False}}
    out = tmp_path / "report.html"
    render_report({"workspaces": {"1280": workspace_data()}}, out,
                  extracts={"1280": extract})
    html = out.read_text()
    # We need to avoid claiming whole-dataset coverage because the
    # `--full-extract` flag limits results to the bounding box.
    assert "entire workspace dataset" not in html
    assert "edited extent" in html
    assert "1 raw elements" in html
    assert "touched-and-live" not in html
    # The denominator note needs to disclose that Findings below share this
    # scope instead of limiting the disclosure to the completeness panel.
    assert "Findings below are evaluated over this same edited-extent population" in html


def test_render_separates_osw_attributes_from_defining_tags(tmp_path):
    """Checks that the 'Attribute changes' panel displays real OSW attributes
    (like `surface`) prominently while separating defining or classification
    tag deltas (such as `highway` and `footway` for a new Sidewalk) into a
    labeled secondary group. These groups must both appear without merging into
    a single undifferentiated count.

    To ensure `highway` and `footway` appear as deltas from real ledger data
    instead of incidental template prose, we use a create action instead of the
    existing modify fixture, which only touches `surface`.
    """
    data = workspace_data()
    data["adiffs"]["63"].append(
        make_action("create", new=make_element(
            "way", elem_id=20, changeset=63,
            tags={"highway": "footway", "footway": "sidewalk",
                  "surface": "concrete"})))
    out = tmp_path / "report.html"
    render_report({"workspaces": {"1280": data}}, out)
    html = out.read_text()
    assert "Other tag changes" in html
    assert "not OSW attributes" in html
    # We use `attr-name` spans to display raw tag keys. These assertions verify
    # that we actually split `osw_attr_deltas` from `other_tag_deltas` instead
    # of merely testing the panel's explanatory text.
    assert '<span class="attr-name">surface</span>' in html
    assert '<span class="attr-name">highway</span>' in html
    assert '<span class="attr-name">footway</span>' in html


def test_render_contains_finding_samples(tmp_path):
    """Checks that rendered reports include `Finding.samples` (up to 20 element
    keys), which leads use to open items in the editor.

    We need to ensure these computed keys appear in the final output instead of
    being dropped.
    """
    out = tmp_path / "report.html"
    render_report({"workspaces": {"1280": workspace_data()}}, out)
    html = out.read_text()
    # We'll find one hit for the enum-off-schema:surface finding at way/7
    # (surface=bricks).
    assert "way/7" in html


def test_render_non_osw_bucket_labels_by_composition_not_as_foreign(tmp_path):
    """Checks that the `non_osw_feature` bucket displays its actual composition
    and uses a label stating that tags match no OpenSidewalks entity
    definition.

    We want to avoid the outdated 'non-OSW features' phrasing because it reads
    as 'irrelevant.'
    """
    data = workspace_data()
    data["adiffs"]["63"].append(
        make_action("create", new=make_element(elem_id=8, changeset=63,
                                               tags={"kerb": "no"})))
    out = tmp_path / "report.html"
    render_report({"workspaces": {"1280": data}}, out)
    html = out.read_text()
    assert "non-OSW features" not in html
    assert "match no OpenSidewalks entity definition" in html
    assert "kerb=no" in html


def test_render_extract_does_not_leak_across_workspaces(tmp_path):
    """Checks that element counts and scope labels do not leak between workspaces
    when only one workspace contains extract elements.

    If one workspace has an extract, we expect it to show its own element count
    in the dataset-scope label. The workspace lacking an extract must instead
    display its own count using the touched-and-live label, without inheriting
    data or scope from the other workspace.
    """
    ws_a = workspace_data()  # We use ID 1280, which we key as "1280" below
    ws_b = workspace_data()
    ws_b["id"] = 999
    ws_b["title"] = "WSP_Other_City"

    # We need two elements in Workspace A's extract so we can distinguish them
    # from the live elements in Workspace B--node 6 and way 7--which also total
    # 2 according to the adiffs in `workspace_data()`.
    extract_a = {
        ("node", 100): {"tags": {"barrier": "kerb", "kerb": "lowered"},
                        "version": 1, "deleted": False},
        ("node", 101): {"tags": {"barrier": "kerb", "kerb": "lowered"},
                        "version": 1, "deleted": False},
    }

    out = tmp_path / "report.html"
    render_report({"workspaces": {"1280": ws_a, "999": ws_b}}, out,
                  extracts={"1280": extract_a})
    html = out.read_text()

    # Workspaces occupy individual <section>...</section> elements. The report
    # header joins titleA and titleB with a middle dot, so we split on
    # <section> tags instead of title text to separate each workspace's panel
    # content.
    _, section_a, section_b = html.split("<section>")
    assert "WSP_Richland_City" in section_a
    assert "WSP_Other_City" in section_b

    # We size the edited-extent scope for A using the 2 elements in extract_a
    # (nodes 100/101). The touched-element count for A also equals 2 (nodes
    # 5+6), but that uses a different code path.
    #
    # The output must not claim coverage of the whole dataset because
    # --full-extract follows bbox scope.
    assert "entire workspace dataset" not in section_a
    assert "edited extent" in section_a
    assert "2 raw elements" in section_a
    assert "touched-and-live" not in section_a

    # B lacks an extract entry, so the page falls back to touched-and-live. B
    # must not inherit extract elements from A or render the edited-extent
    # label containing "N raw elements". While A's extract elements would also
    # show 2 elements, they use the wording we asserted absent above instead of
    # the touched-and-live phrasing.
    #
    # We can't use "edited extent" alone as a discriminator. The page-level
    # Methodology modal also contains that phrase in the singular form "raw
    # element" (which appears in this split chunk because the modal appends
    # after the last section). The per-section denominator note renders the
    # plural "raw elements", so that is the specific string we assert absent.
    assert "raw elements" not in section_b
    assert "touched-and-live" in section_b
    # We exclude the baseline import from changeset 1 by default. This leaves
    # the figures from changeset 63--creating node 6 and modifying way 7--which
    # results in 2 touched elements that both remain live and 0 left deleted.
    assert "2 touched-and-live elements" in section_b
    assert "(2 touched, 0 left deleted)" in section_b
