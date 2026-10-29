# Workspaces Contribution Reports

These tools fetch changeset data from a local export archive or the live OSM API
to render self-contained HTML contribution reports for data-collection events. A
single installable package provides three console scripts: `contribution-report`
for quest contribution reports, `osw-report` for OSW workspace change reports,
and `report-summary` for program one-page summaries.

## Install

We need Python 3.12 or newer. To install the console scripts:

```sh
pip install .
```

Alternatively, we can use [uv](https://docs.astral.sh/uv/) to install the
package into an isolated tool environment:

```sh
uv tool install .
```

Before running, copy the *.env.example* file to *.env* and set the variables as
needed.

## Usage

Pass `--help` to any command to see all available options. The tools write all
output into the `output/` directory within our current working directory.

```sh
# Fetch live data for specific workspace IDs and render
contribution-report 1977 1978 1979

# Fetch for a specific past date
contribution-report 1977 1978 1979 --date 2026-06-10

# Fetch changesets created on a local calendar day instead of a UTC day.
# --tz also sets the time zone of the report header date.
contribution-report 2166 --date 2026-10-18 --tz America/Los_Angeles

# Fetch all changesets across all dates (paginated; useful when a workspace spans multiple days)
contribution-report 127 --all-dates \
    --cache-file ./output/changesets_hth_renton.json --output ./output/report_hth_renton.html

# Re-render from cache (no HTTP requests)
contribution-report --cached

# Re-render from a named cache file
contribution-report --cached --cache-file ./output/changesets_leavenworth.json --output ./output/report_leavenworth.html

# Refresh only workspace titles/quest definitions, keep cached changesets
contribution-report --refresh-meta

# Refresh only notes, keep cached changesets
contribution-report --refresh-notes

# Re-fetch way geometry for all quest elements (fixes markers in batch changesets)
contribution-report --refresh-geoms --cache-file ./output/discovered/changesets_nda_vancouver_walk_roll.json

# Load a local export archive (no workspace API needed); also writes a cache file for --cached re-runs
contribution-report --offline examples/changeset.zip --quest-file examples/renton-quest.json \
    --cache-file ./output/changesets_renton.json --output ./output/report_renton.html

# Override the report title (appears in <h1> and <title>)
contribution-report --cached --report-title "Renton Accessibility Survey Report"

# Override every workspace section title (useful for single-workspace reports with a nicer short name)
contribution-report --offline examples/changeset.zip --workspace-title "Renton HTH Event"

# Restrict to the densest contiguous activity session (default: render all app changesets)
contribution-report --cached --auto-detect-event-window

# Infer infrastructure issues (requires WS_ANTHROPIC_API_KEY in .env)
# Calls the Anthropic API and Overpass API; stores results in the cache file.
# --infer-issues and --hotspots work with offline-produced caches just like live ones.
# Discovered workspaces are standalone caches, so run this per workspace, e.g.:
contribution-report --infer-issues --cache-file ./output/discovered/changesets_nda_vancouver_walk_roll.json

# Use a specific model (for comparing outputs)
contribution-report --infer-issues --llm-model claude-opus-4-8

# Use a local model via Ollama instead of the Anthropic API (no API key needed)
contribution-report --infer-issues \
    --llm-provider ollama --llm-model qwen3-coder-next --llm-url http://localhost:11434

# Use a local OpenAI-compatible server (llama.cpp llama-server, vLLM, LM Studio)
contribution-report --infer-issues \
    --llm-provider openai --llm-model <served-model-id> --llm-url http://localhost:11435

# Re-render with issues already cached (zero API calls)
contribution-report --cached

# Render issues but suppress the "Surveyed Well" positive panel (problems only)
contribution-report --cached --no-positive

# Recompute consensus hotspots from a cache that already has --infer-issues data (zero API calls)
contribution-report --hotspots --cache-file ./output/discovered/changesets_nda_vancouver_walk_roll.json

# Then re-render to see hotspot beacons and panel
contribution-report --cached --cache-file ./output/discovered/changesets_nda_vancouver_walk_roll.json --output ./output/discovered/report_nda_vancouver_walk_roll.html

# Discover reports (find workspaces by title prefix, auto-detect each event window)
# Writes one standalone ./output/discovered/changesets_<slug>.json + report_<slug>.html
# per workspace (e.g. report_nda_vancouver_walk_roll.html) — there is no combined report.
contribution-report --discover --title-match NDA
contribution-report --discover --title-match NDA --dry-run   # show workspaces + windows only
contribution-report --discover --cached    # re-render every cached discovered workspace, no fetching
```

## OSW Workspace Change Report

We use this second report type for workspaces that lack both **survey-app
changesets and a quest definition** (such as remote-mapping projects at city
scale edited via JOSM or Rapid). The quest report renders no data in these cases
because the always-on app filter discards every changeset.

```sh
# Fetch and render
osw-report 1280

# Re-render from cache, zero API calls
osw-report --cached \
    --cache-file ./output/osw_richland.json.gz

# Discard and re-fetch every cached adiff
osw-report 1280 --force

# Fold the TDEI baseline import into the edit ledger
osw-report 1280 --include-baseline

# Measure completeness over the edited extent (the bbox spanning the
# reported changesets) instead of touched elements only — NOT the whole
# workspace dataset
osw-report 1280 --full-extract
```

- **Caching contract:** Adiffs for closed changesets never change. The script
  reuses all adiffs present in the cache file during a standard
  `osw-report 1280` run and only fetches changesets missing from the cache or
  found in `adiff_failures`. This gap-filling behavior happens by default
  without a flag and cannot be disabled. Only `--force` overrides this; it
  clears all cached adiffs for the specified workspace(s) and re-fetches the
  entire set. This is costly for workspaces with large baseline imports (see
  gzip note below) and is rarely needed.

- **Data source:** The augmented-diff API
  (`GET {WS_NEW_API_URL}/workspaces/{ws}/changesets/{cs}/adiff`) provides
  element data instead of OSC XML. A single call per changeset returns way
  geometry and both `old` and `new` tags, so the script does not use
  `/changeset/{id}/download` or `/way/{id}/full`.

- **Contract rules:** Three rules ensure accurate accounting:

1. The script counts an action as an edit only if
   `action.new.changeset == requested_changeset_id`. The adiff also includes
   *context rows* for referenced elements not authored by the changeset.
   Including these would credit work to the last person who touched the element
   and inflate edit volume by ~34%.
2. The sum of counted actions per changeset must equal `changes_count`. If they
   differ, the report displays a visible warning instead of rendering an
   incorrect number.
3. The script uses `old.tags` to classify `delete` actions. Because `new`
   contains cleared tags for deletions, this prevents every deleted way from
   appearing untagged.

**Report halves.** The first half details modifications and authors (timeline,
contributors, changes by OSW entity, corrections to values, deltas in
attributes, modifications limited to either tags or geometry, and the editor
validation trail). The second half is the *resulting data state* (rule findings,
value distributions, and attribute completeness per OSW entity).

Figures label their scope because completeness measures **touched-and-live**
elements rather than the entire dataset. These halves use different units: Half
A counts actions while Half B counts distinct elements.

When we pass `--full-extract`, the tool fetches all elements within the **edited
extent** via `/api/0.6/map?bbox=`. This extent is the bounding box from the
minimum to maximum latitude and longitude of all reported changesets.
Completeness metrics then use this broader raw-element population instead of
only elements that were touched. **This does not cover the entire workspace
dataset**: features outside that bounding box (such as those in city areas no
reported changeset touched) are silently absent from figures, just as they are
when using the touched-elements denominator. The resulting figure counts raw
**elements** rather than features, so it includes untagged geometry vertices.

Results save to a sibling file at `output/osw_<slug>_extract.json.gz` with a
workspace ID key (`{"workspaces": {"<ws_id>": {"elements": [...]}}}`). This
shape mirrors the main cache so that runs involving multiple workspaces never
mix elements between different figures. The tool uses touched-and-live figures
for a workspace alone if that workspace lacks an entry here&mdash;perhaps
because it joined after the most recent `--full-extract` run, contains no
positioned changesets, or its bbox fetch failed because the API cannot return it
in one call. In this case, the tool prints a warning instead of aborting. This
mode is off by default because city-scale bboxes pull tens of megabytes and the
report remains useful without the extract. The report's denominator note always
specifies which scope produced the figures and clarifies that the findings panel
uses the same population when evaluated across the edited extent.

**Rules** split into families:

- **conformance:** data that contradicts the OSW schema (such as missing step
  counts, off-enum values, or placeholder widths).
- **network:** valid data with real-world significance (such as curb type mix or
  unmarked crossings).

Both types are deterministic and involve no calls to Overpass or an LLM.

Cache files are **gzipped** (`output/osw_<slug>.json.gz`) — raw adiffs run
~25 MB for a workspace with a large baseline import.

**Verified against the reference workspace** (1280, `WSP_Richland_City`):
102 changesets fetched, 102 adiffs, 0 fetch failures. Counted actions
reconcile exactly against the sum of `changes_count`: 42,443 excluding the
baseline import, 168,350 including it. Modifications split 13,210
geometry-only / 6,181 tags-only / 1,059 both / 57 no-op, touching 37,196
elements of which 34,967 are still live. Rule findings: `enum-off-schema:surface`
93 of 7,534 (`bricks` ×81, `ground` ×11, `wood` ×1), `width-placeholder` 1,595
of 1,595, `steps-no-count` 10 of 38, `crossing-unmarked` 1,083 of 1,506, and
`curb-type-mix` across 8,702 curb features.

**Production runs.** The resolved `.env` may point `WS_NEW_API_URL` at a local dev host.
Workspace 1280 lives on the production API instead, so a live run against it
needs `WS_NEW_API_URL` set in the shell — shell `WS_*` variables override the
env file:

```sh
WS_NEW_API_URL=https://api.workspaces.sidewalks.washington.edu/api/v1/ osw-report 1280
```

## Contribution Summary

We use `report-summary` to generate a one-page program summary using cached
event reports. Because it relies entirely on `changesets_<slug>.json` caches
found in `--cache-dir` (which defaults to `./output`) or on an event catalog
JSON provided via `--events-file`, it makes no API calls. The tool defaults to
`Contribution Summary` for the page title and writes the result to
`summary_contributions.html` within the cache directory.

```sh
# Auto-discover events from the caches in ./output
report-summary --cache-dir ./output

# Exact published figures
report-summary --events-file examples/events.json --output ./output/summary_contributions.html
```

Auto-discovered events lack reporting history, so each renders with `use_window`
set to true. This alters figures for events originally published from a full
cache. To match those published figures, we need to pass a catalog of event
objects (`slug`, `title`, `use_window`, `city`, `lat`, `lon`) via
`examples/events.json` to record whether each event used the full cache or an
event window.

## Environment variables

We resolve the environment file by checking `--env-file PATH` first, then the
`WS_ENV_FILE` variable, and finally any `.env` file found while walking up from
the current working directory. If no file exists, the tools default to shell
environment variables alone (which is fine unless we're fetching live data,
where those calls will fail during URL checks). The active file is never parsed
in Python. Instead, a bash subprocess sources it using `set -a && source`.
Because shell `WS_*` variables override file values, we can pass a variable like
`WS_OSM_URL=...` directly on the command line to ensure it wins. The relevant
variables are:

- **`WS_OSM_URL`:** Required. Base URL for the OSM API (e.g.
  `http://osm.workspaces.local:PORT`); handles all element and changeset
  fetches.
- **`WS_NEW_API_URL`:** Required. Base URL for the new FastAPI backend; fetches
  quest definitions and workspace metadata.
- **`WS_REPORT_TOKEN`:** Optional. Pre-obtained Bearer token that skips
  interactive authentication if present.
- **`WS_TDEI_BACKEND_URL`:** Optional. The TDEI backend URL used to request auth
  tokens when `WS_REPORT_TOKEN` is missing.
- **`WS_REPORT_USER`:** Optional. TDEI username. It works with
  `WS_TDEI_BACKEND_URL` for non-interactive token retrieval or triggers an
  interactive prompt if absent.
- **`WS_REPORT_PASS`:** Optional. TDEI password used alongside `WS_REPORT_USER`.
  Triggers an interactive prompt if absent.
- **`WS_ANTHROPIC_API_KEY`:** Optional. The key for the Anthropic API. When
  using the default `anthropic` provider, `--infer-issues` requires this key.
  Local providers like `ollama` or `openai` do not need it. If missing without a
  local provider, the report renders without an issues panel and skips
  inference.
- **`WS_LLM_PROVIDER`:** Optional. The LLM provider for `--infer-issues`
  (`anthropic` by default, or `ollama` / `openai`). The `--llm-provider` flag
  overrides this value.
- **`WS_LLM_MODEL`:** Optional. The default model for `--infer-issues`. For
  `anthropic`, it defaults to `claude-sonnet-5` (also accepts `claude-opus-4-8`
  or `claude-haiku-4-5`). For `openai` and `ollama`, no default exists; any
  model served by the target is valid, and one must be specified here or via
  `--llm-model`. The `--llm-model` flag overrides this value.
- **`WS_LLM_URL`:** Optional. The model server base URL for `openai` and
  `ollama` providers. It is required for `openai` (the `/v1` suffix is
  optional). The `--llm-url` flag overrides this value.
- **`WS_OLLAMA_URL`:** Optional. Default server URL (`http://localhost:11434`)
  for the `ollama` provider when `WS_LLM_URL` is empty. The `--ollama-url` flag
  aliases `--llm-url`.
- **`WS_OVERPASS_URL`:** Optional. The Overpass API base URL; defaults to
  `https://overpass-api.de/api/interpreter`. Use this to point to a local
  mirror.
- **`WS_OVERPASS_TOKEN`:** Optional. The Bearer token sent in the
  `Authorization` header for Overpass mirrors that require auth.
- **`WS_APP_FILTER`:** Optional. Comma-separated `created_by` prefixes that
  override the default survey-app list (`AVIV ScoutRoute, GIG, GoInfoGame`).
  Overridden by `--app-filter` and disabled by `--no-app-filter`.
- **`WS_ENV_FILE`:** Optional. The path to the `.env` file when `--env-file` is
  not provided. If this variable is set but the file is missing, an error
  occurs. If no file is found at all, it is tolerated.

**Security:** We need to route all database access through APIs instead of
connecting scripts directly. All data comes through `WS_OSM_URL` and
`WS_NEW_API_URL`, with OSM requests carrying `X-Workspace: <id>` and
`Authorization: Bearer <token>` headers.

**Outbound calls made by `--infer-issues`:** The inference pipeline sends quest
definitions and note text to the **Anthropic Messages API**
(`api.anthropic.com`) when using the default `anthropic` provider. In debug
output, we mask the `x-api-key` header. If we use `--llm-provider ollama` or
`openai`, these calls go instead to the `/api/chat` or `/v1/chat/completions`
endpoint of a self-hosted or local server. This approach requires no API key and
keeps all traffic within the server's reachable network. Regardless of the
provider, road geometry queries go to the **Overpass API** (`overpass-api.de` by
default). We send no workspace data anywhere else.

## Output directory

We write all rendered HTML reports and JSON caches to the `./output` directory
in the current working directory. This folder is created automatically if it
does not exist, and since it contains build artifacts, it is gitignored (see
*AGENTS.md*). Example fetch inputs, including `changeset.zip`,
`renton-quest.json`, `quests/`, and `events.json`, occupy `examples/`.

## Cache files

We save all live API data as JSON in `./output/` before rendering so we can
regenerate reports without new fetches.

- **`changesets_raw.json`:** The default cache used by `contribution-report`.
- **`discovered/changesets_<slug>.json`:** Standalone caches created by
  `--discover`. Each discovered workspace gets its own file in
  `./output/discovered/` (for example, `changesets_nda_vancouver_walk_roll.json`
  or `changesets_nda_pierce_county_walk_roll.json`). The `discover.slugify()`
  function derives `<slug>` from the workspace title. Every workspace remains
  fully standalone; no combined multi-workspace cache exists.
- **`changesets_leavenworth.json`:** A named cache specifically for the
  Leavenworth event.

Cache schema:
`{ "date": "YYYY-MM-DD", "tz"?, "workspaces": { "<ws_id>": { "id", "title", "type", "event_date"?, "quest_definition", "changesets": [...], "notes": [...], "issues"?: [...] } } }`.
The renderer pulls the IANA zone from `tz` (which we pass with `--tz`) for
header dates. A changeset entry contains the raw OSM API object plus:

- `osc_xml`: The OsmChange XML download.
- `elem_lat`, `elem_lon`, and `elem_geom`: The full node geometry and way
  midpoint for the first quest element (optional).
- `all_elem_geoms`: A map of `{elem_id: {lat, lon, geom}}` that records the
  geometry and midpoint of each quest way within the changeset. This is optional
  and added during a fetch or via `--refresh-geoms`; map markers use it when a
  changeset involves multiple sidewalk ways.

Each note entry records `{lat, lon, text, user}`, where `user` is the author and
`text` is the opening comment. Caches created before notes included the `user`
field still render, but we exclude those notes from Contributor counts unless
`--refresh-notes` re-fetches them.

Using `--infer-issues` adds the `issues` array. The entries contain:
`{ rank, combined_score (signed −1..+1, dimension-weighted), quest_score, note_score, trav_score, conn_score, safety_score (per-dimension means, or null when not assessed), confidence, conf_quantity, conf_agreement, conf_corroboration, sign: "problem"|"good"|"neutral", derived (bool), derived_from (str|null), segment: { name, side, cross_streets, geometry, label }, centroid: [lat,lon], summary, quest_count, note_count, quest_evidence: [{tag, value, label, weight, dimensions, count}], note_evidence: [{text, score, label, dimensions}], evidence_points: [{lat, lon, kind, weight, label, dimensions, tags?|text?}] }`.
After running `--infer-issues`, we'll see the issues panel re-render from this
array when we use `--cached`, which requires no new API calls. A sibling
`issue_meta` object contains
`{ dimension_coverage: { <dim>: {tags, points, covered} } }`, so the report
marks dimensions never assessed by the survey instead of displaying a hollow
zero.

The `hotspots` array comes from `--infer-issues` (where it's added
automatically) or from the `--hotspots` flag. The latter makes no API or
Overpass calls because it reads cached `_rubric` and `_scored_notes` data. The
entries contain:
`{ rank, centroid: [lat,lon], count, quest_count, note_count, voices, intensity (signed mean of each point's worst-dimension weight, −1..0), confidence, conf_quantity, conf_agreement, conf_corroboration, label, evidence_points: [{lat, lon, kind, weight, label, text|tags}] }`.
Only negative-signal clusters with ≥3 reports within 40 m from ≥2 independent
voices qualify. These appear in a ranked "Consensus Problem Hotspots" panel and
as red pulsing beacons on the map.

During rendering, `render_builders.py` adds a `seg_ref` dict to each issue via
`segments.format_segment_ref()`. This dict isn't stored in the cache and uses
the segment's `name`, `side`, and `cross_streets` fields to populate `road`,
`side`, `side_letter`, `cross_range`, and `text` (for aria and `title`). If we
have an old cache lacking component data, the original `segment.label` string
serves as the fallback.

We also write two debug fields at the workspace level for offline inspection of
model outputs:

- `_rubric`: the complete `{quest_tag → {answers, thresholds, default_weight}}`
  dictionary from the LLM.
- `_scored_notes`: the LLM output for each note before spatial clustering is
  applied, which includes `is_relevant`, `score`, `road_ref`, `summary`, and
  `_orig` (containing the original text and lat/lon).

The renderer does not use these fields.

## Key concepts

### OSC XML — full element state, not a diff

The OsmChange format (`/api/0.6/changeset/{id}/download`) provides the
**complete current state** of each element in a changeset instead of just the
modified tags. For example, a `<modify>` entry for a node contains all its
current tags, including those from previous changesets.

This affects how we attribute photos. If we add `ext:kartaview_url` to a way in
changeset 42 and then modify that way in changeset 53 (for instance, to address
another quest question), the OSC for changeset 53 will also include
`ext:kartaview_url`. We'll attribute the photo to both changesets unless we
deduplicate.

**Fix in place:** both `analyse()` and `build_map_markers()` sort changesets by
ID in ascending order (oldest first) and track a `seen_photo_urls: set[str]`. We
attribute a photo URL only to the first changeset where it appears.

### Offline ingestion (`--offline`)

When we pass a **zip file** or **directory** to `--offline PATH`, it must
contain:

- `manifest.json`: This holds workspace metadata (`workspace.{id,title,type}`)
  and a `changesets[]` array matching the OSM API's changeset list shape.
- `changesets/<id>.json`: Each changeset gets one file with an OSC JSON dict
  containing `{create?:[],modify?:[],delete?:[]}`. Elements include `id`,
  `version`, and `tags`, plus type-specific fields&mdash;`lat`/`lon` for nodes,
  `nodes:[ids]` for ways, and `members:[{type,ref,role}]` for relations. The
  pipeline reads an explicit `type` field or infers the type from these fields.

The function `offline.py::osc_json_to_xml()` transforms each OSC JSON dict into
an OsmChange XML string so the pipeline treats it like a live-fetched OSC. If
files are missing or contain only `{}`, they produce `""`, which `osc.py` no-ops
cleanly.

**Offline degradations vs live fetch:**

- **No notes:** The `notes: []` array remains empty because the OSM notes API is
  not called.
- **No way geometry:** Way polylines won't appear on the map, and midpoints fall
  back to the bbox centroid.
- **No prev-tag diff:** Since `prev_tags` becomes `null`, the tag table marks
  all tags as "added" (purple).

These limitations don't affect `--infer-issues` or `--hotspots`, which still
call the **Anthropic** and **Overpass** APIs unless results already exist in the
cache. Once we cache issues by running `--infer-issues` on an offline-produced
cache, all following `--cached` re-renders work fully offline.

### Always-on app filter

Before any other work begins, `render_report()` removes changesets from each
workspace unless their `created_by` tag matches a survey-app prefix. This
prevents non-app edits from being counted, whether we fetch data live or
offline. By default, the filter uses a built-in list containing
`AVIV ScoutRoute`, `GIG`, and `GoInfoGame`. We can define a custom list for a
single run by repeating `--app-filter PREFIX`, make that list the default for
all runs via the comma-separated `WS_APP_FILTER` environment variable, or
include every changeset by passing `--no-app-filter`.

### Event window filtering

We use `--auto-detect-event-window` to restrict the report to the **densest
contiguous activity session**. The `find_event_window()` function divides a day
into sessions when the time between app changesets surpasses an adaptive
threshold (`max(20 min, 4 × median inter-edit gap)`), selecting the session with
the highest changeset count to define the window's start and end timestamps.
This approach accommodates events of any length without a fixed 2-hour limit but
discards lonely test or setup edits occurring far outside the main activity. By
default, app changesets appear in the report since most archives hold only event
data. We need this flag to apply the filter.

Because `--discover` employs the same `find_event_window` logic, discovered
reports automatically match the actual event duration without a separate flag.

### Date range header

We compute the date range in the report header from the changesets that actually
appear in the render:

- Single day: `"September 4, 2024"`
- Multiple days within one month: `"September 4 – 10, 2024"`
- Multiple months within one year: `"September 4 – October 10, 2024"`
- Multiple years: `"December 31, 2023 – January 1, 2024"`

### Fuzzy quest tag matching

We register every `quest_tag` using both its bare form (`surface`) and its
`ext:`-prefixed version (`ext:surface`) inside `build_quest_index()` and
`build_choices_index()`. This ensures that `ext:`-prefixed tags in changeset OSC
data match against bare tags in offline quest definitions (such as those in
*renton-quest.json*), and vice versa.

### Title overrides

- `--report-title TITLE`: sets the `<title>` and `<h1>` instead of the default
  `"Contribution Report"`.
- `--workspace-title TITLE`: replaces all workspace section titles; this is
  useful for providing a shorter name when reporting on a single offline
  workspace.

### Quest definitions

Data comes from `definition.elements[].quests[]` via
`GET /api/v1/workspaces/{id}/quests/long/settings`. We build two indexes from
this:

- **`quest_index`**:
  `{ext:tag_key: {"title": "Human Question Title", "element_type": "Sidewalks"}}`.
  We use this to classify changesets, generate the Labels view, and apply green
  color-coding to quest answer tags in popups.
- **`choices_index`**: `{ext:tag_key: {raw_value: "Display Label"}}`. We use
  this to translate raw OSM tag values into human-readable labels for the
  question breakdown table and Labels popup view. It handles MultipleChoice
  values separated by semicolons.

When we use `--offline`, we need to pass a definition from `examples/quests/`
via `--quest-file`. The `--discover` flow instead fetches the live definition
for each workspace.

### Changeset classification

We use `classify_quest()` to assign an element type (such as "Bus Stops" or
"Sidewalks") to a changeset:

1. We use the `quest_type` changeset tag directly when Android clients include
   it.
2. When iOS clients omit that tag, we fall back to `classify_by_tags()` to
   match `ext:` tags on the modified element against keys in the `quest_index`.
3. If those methods fail to classify the changeset, we fall back to the OSM tag
   heuristics in `classify_osm_feature()`.

### Map markers

Changesets generate markers:

- **Quest markers:** These circles come from `build_map_markers()`, with one
  created for each non-empty changeset containing `quest_type` or `ext:` tags.
  We place them at the element's true arc-length midpoint by interpolating nodes
  for ways using `/api/0.6/way/{id}/full.json`, or we fall back to the bbox
  centroid if geometry is missing. When a user clicks a way marker, the full
  geometry draws as a polyline in the quest-type color until the popup closes.
  These markers apply photo deduplication.
- **Created feature markers:** These diamonds come from
  `build_created_markers()`, with one per element in `<create>` actions. We
  position them at the actual lat/lon of the node, though elements lacking tags
  are skipped.

If a changeset contains both, quest markers take priority. The
`build_map_markers()` function skips any changeset lacking `ext:` tags to
prevent double-marking elements that already appear in
`build_created_markers()`.

### Popup tag tables

A "Raw" / "Labels" button toggles between two popup views for every map marker:

- **Raw view:** The `build_popup_tags()` function provides all element tags
  without filtering. The view marks quest-indexed tags in green when `old: null`
  and others as neutral if `old == new`.
- **Labels view:** The `build_readable_tags()` function includes only tags
  present in the `quest_index` that also possess a mapped choice value or
  human-readable title. Question titles replace raw tag keys, while choice
  display text replaces raw values.

The JS function `renderTagTable()` renders both views. Odd-numbered `<tr>`
elements use a `#e9ecef` stripe, while each `<td>` receives a semantic color for
add/modify/delete operations at 0.65 rgba opacity to ensure the stripe remains
visible. The key column employs text color `#495057` to maintain WCAG AA ≥ 4.5:1
contrast against all applied backgrounds.

### Photo handling

The `ext:kartaview_url` tag stores multiple KartaView photo URLs as a
comma-separated list. To move legacy `api.openstreetcam.org` links to the modern
CDN format (`https://cdn.kartaview.org/pr:sharp/<base64>`), we use
`convert_kartaview_url()`.

Survey apps also include photos in notes by adding KartaView URLs to the end of
the text on individual lines. The `split_note_photos()` function in
`classify.py` removes these from the display text and normalizes each with
`convert_kartaview_url()`.

Photos appear in these locations:

- A 📷 button inside map popups (for each note and changeset), as well as any
  area displaying note text for hotspot or issue evidence (including the hotspot
  table, hotspot popups, the single-point modal, and the Evidence modal).
  Because we split evidence during rendering, the cache retains the original
  fetched note text.
- A photos column within summary cards for teams, quests, and users. Photos from
  notes credit the author.

The Contributors card counts a single note or changeset as one contribution for
its author.

The photo gallery opens in a modal with `z-index: 410`, which places it above
the backdrop (299), the expanded map (300), and the Evidence modal (400) that
may have triggered it.

### Infrastructure issue scoring (`--infer-issues`)

Each issues panel in the HTML report includes an **ⓘ Methodology** button for
readers. The following details the same algorithm for developers.

`issues.py` manages a sequence of geometry and LLM steps for each workspace by
delegating to `issues_*` sibling modules. All results go into the cache, so
`--cached` re-renders incur no API costs.

- **Dimensions:** We assign each quest tag and note to at least one of three
  independent dimensions, calculating separate scores for every segment:

| Dimension | Captures | Roll-up weight |
|---|---|---|
| `traversability` | Surface, obstacles, clear width, steps, incline&mdash;can the path be physically used? | 1.0 |
| `connectivity` | Curb ramps, crossings, tactile paving, network continuity&mdash;is the path reachable/connected? | 1.0 |
| `safety_comfort` | Lighting, handrails, shade, shelter, traffic buffering&mdash;is it safe and comfortable? | 0.5 |

- **Step 1--Quest rubric (one LLM call per workspace):** The LLM analyzes the
  workspace quest definition to assign each quest to one or more dimensions. For
  each answer value, it returns a short label and a signed weight
  `w ∈ [−1, +1]`. Negative weights signal problems (e.g.
  `ext:intersection_curb_ramps_all_corners=no → −0.90, "Missing curb ramps", ["connectivity"]`).
  We apply this rubric deterministically to all changesets to avoid
  per-changeset LLM costs.

- **Step 2--Quest point extraction & scoring:** We create a scored point at the
  element's position for each quest changeset. We bucket weights per dimension
  from the matched tags, then calculate the point's flat `weight` as the mean of
  those tag weights.

- **Step 3--Note scoring (one batched LLM call per workspace):** We send
  free-text notes in groups of 50 to extract a one-line `summary`, an optional
  `road_ref`, `dimensions`, a `score ∈ [−1, +1]`, and an `is_relevant` flag to
  filter out noise like "Driveway".

- **Step 4&mdash;Overpass road fetch:** The pipeline queries Overpass once using
  the entire evidence bbox to collect named highway ways in the area.

- **Step 5&mdash;Side-aware block-face grouping:** We use
  `overpass.locate_point()` to map each evidence point to a
  `(road, block-face span, side)` key, which groups points that share a block
  side and location. If no road matches, we cluster points within 50 m using
  `_cluster_points`. The minimum group size is **1**, which allows a single
  observation to surface as a low-confidence lead. The confidence score reflects
  this thinness.

- **Step 6&mdash;Dimension-aware group scoring:** Each group receives a score
  per dimension based on the mean of those dimension weights. The
  `combined_score ∈ [−1, +1]` is the **dimension-weighted mean** of present
  dimensions (Safety & Comfort at half). This is different from a flat mean of
  all answers. The score does not change based on low evidence count. That
  uncertainty is in the confidence value instead.

- **Step 7&mdash;One-hop connectivity propagation:** Connectivity barriers at
  intersections also affect the block faces leading to them. When a group has a
  negative `conn_score`, a decayed penalty (`× 0.5`, `CONNECTIVITY_DECAY`)
  propagates one hop to adjacent block faces that lack direct evidence. This
  creates **derived** issues (`derived: true`) with confidence capped at 0.25.
  We only propagate evidence located within 60 m (`_MAX_NODE_EVIDENCE_DIST`) of
  the shared intersection node, and the strongest barrier claims each target
  face.

- **Step 8&mdash;Sign, ranking, and summaries:** The `SEVERITY_SIGN_THRESHOLD`
  marks groups with `combined_score < −0.1` as problems and those with
  `combined_score > +0.1` as good. Others are neutral. The pipeline sends a
  single LLM request for each top-N set (10 problems and 10 good by default) to
  generate a plain-language summary under 25 words. Derived issues use canned
  text and require no LLM call.

- **Confidence:**

```
confidence = 0.4 × quantity + 0.4 × agreement + 0.2 × corroboration
```

| Sub-factor | Formula | Notes |
|---|---|---|
| `conf_quantity` | `min(1, √voices / √3)` | We count **distinct voices** (contributors) instead of raw observations to prevent inflated scores from repeated surveyor taps. This value saturates at 3, since thorough block surveys rarely field more. Each note is one voice; a quest point's voice comes from its `uid` (which maps to username and then changeset id). |
| `conf_agreement` | `mean over dims of max(0, 1 − σ_dim)` | We average within-dimension consistency across all dimensions with **≥2 independent voices**. This per-dimension calculation ensures that good conditions on one dimension do not mask a real problem on another as "disagreement". A single voice provides no signal and results in 0. |
| `conf_corroboration` | 1.0 / 0.6 / 0.2 | The value depends on whether quest and note sources align, if only one source exists, or if sources conflict. |

**Ranking**

We rank segments by `|combined_score| × confidence`. This approach places a
moderate problem with strong evidence above a severe one with weak evidence.

**Map display**

Polyline color follows a diverging ramp from red to yellow to green to encode
the active-dimension score. When we use the Combined/Trav/Conn/Safety toggle,
the color updates by dimension. We use polyline opacity to encode confidence
(`0.35 + 0.55 × confidence`). Derived issues appear as **dashed** lines.

### Consensus hotspots (`hotspots.py`)

This simpler problem-surfacing method operates without the Overpass or Anthropic
APIs once `--infer-issues` has already cached the scored-notes and rubric. It
does not identify specific infrastructure elements at fault; it finds locations
where multiple people reported similar problems.

**Algorithm**

1. Filter all scored quest and note points to keep only those with a
   **worst-dimension weight ≤ −0.25** (`NEG_THRESHOLD`). Using the worst
   dimension instead of a flat mean prevents severe barriers (like a −0.90
   missing curb ramp) from being masked by other benign answers.
2. Group points using the greedy 40 m (`HOTSPOT_RADIUS_M`) single-linkage
   algorithm in `issues_geo.py` (`_cluster_points`).
3. Require **≥3 evidence points from ≥2 independent voices** for a cluster to
   qualify as a hotspot. Each note and each quest changeset contributor counts
   as one voice.
4. Calculate intensity (mean of worst-dimension weights), confidence (using the
   issues formula), and a label (combining a note snippet with top quest-answer
   labels) without further API calls.
5. Sort by `confidence` descending and use `count` as a tie-breaker.

**Contrast with the interpretive issues pipeline**

| | Issues pipeline | Consensus hotspots |
|---|---|---|
| API calls | Overpass plus LLMs for scoring rubrics, notes, and summaries | None (leverages cached notes and rubrics) |
| Output | Block-face road segments with dimensions, summaries, and scores | Beacons at points showing raw evidence |
| Claim | "Traversability for this road and side is −0.82" | "Several users reported issues at this spot" |
| Map display | Polylines with color coding | Red beacons that pulse |

**CLI flag:** `--hotspots` can run standalone at zero API cost if the cache
contains `_rubric` and `_scored_notes`. The `--infer-issues` flag also generates
`hotspots` automatically alongside `issues`.

### Discover reports (`--discover`)

`contribution-report --discover` finds workspaces by title prefix (`--title-match NDA`, repeatable; explicit workspace IDs also work) instead of requiring IDs up front, and renders one standalone cache + report per workspace under `./output/discovered/`: `changesets_<slug>.json` / `report_<slug>.html`. There is no combined multi-workspace report — each workspace is fully independent, on both a live fetch and `--cached` re-renders:

- Each workspace's full changeset history is scanned and the event window is detected with the shared `find_event_window` — see [Event window filtering](#event-window-filtering). Changesets in isolated setup/testing sessions are excluded; all app changesets within the window are included.
- A workspace whose window cannot be detected because it has too little data (e.g. a single test changeset) is skipped until it has a real event to report on.
- The slug is derived from the workspace title by `discover.slugify()`: lowercased with non-alphanumeric runs collapsed to single underscores (`"NDA Vancouver Walk/Roll"` → `nda_vancouver_walk_roll`), falling back to `ws<id>` when nothing is left.
- `--dry-run` lists the discovered workspaces and their detected windows. Each workspace's changeset history is still fetched, because window detection requires it, but the quest-definition, OSC, and notes fetches are skipped and nothing is written.
- `--discover --cached` re-renders every `./output/discovered/changesets_*.json` file already on disk; it doesn't rediscover or refetch workspaces. Running `--infer-issues` against a workspace's own cache and then re-running `--discover --cached` propagates the cached `issues`/`hotspots`/`_rubric` back into that workspace's report — inference is run (and priced) per workspace.

### Local model support (`--llm-provider ollama|openai`)

We can point `--infer-issues` at a self-hosted model server rather than the
Anthropic API by passing `--llm-provider ollama` (or `WS_LLM_PROVIDER=ollama`)
along with `--llm-model <name>` and `--llm-url` (if we're using a non-default
port). The `contribution_reports.llm.OllamaClient` communicates with the
`/api/chat` endpoint and shares the same `complete()` and `complete_json()`
interface as the Anthropic `LLMClient`, so `issues.py` remains agnostic to the
active provider.

For platforms that implement the OpenAI chat API instead of the Ollama
format&mdash;such as vLLM, LM Studio, or the `llama-server` from
llama.cpp&mdash;we'll need to use `--llm-provider openai` with a required
`--llm-url` and an `--llm-model` that matches an ID from the server's
`/v1/models`. `OpenAIClient` extends `OllamaClient`, changing only the response
parsing, the endpoint, and the request body's `response_format: json_object` and
`max_tokens`. Reasoning models include thinking tokens in their `max_tokens`
count; a call returns no content and fails with `finish_reason=length` if the
model exhausts its token budget before answering.

Local models follow the implicit JSON conventions for note-scoring and rubric
calls less consistently than Claude. When we tested `qwen3-coder-next`, a single
prompt generated at least half a dozen distinct top-level structures across
different runs&mdash;including a flat
`{quest_tag: {answer_value: {weight, label}}}` map, a bare list,
`{"rubric": [...]}`, `{"quest_weights": {...}}`, a sibling `quest_dimensions`
map for dimensions, etc. Also, a single batched note-scoring request merged
several notes into one object instead of returning an array. To avoid
special-casing individual models, the issue-pipeline modules employ broad
normalization:

- `issues_parse._unwrap_list_result()` handles a bare array or a wrapper object
  with a single key of any name, even if the prompt requested something else.
- `issues_parse._entries_from_flat_map()` and `issues_parse._build_rubric()`
  support multiple rubric shapes&mdash;such as a tag->answer-list map, a flat
  tag->answers map, or a list-of-entries&mdash;and they tolerate individual
  malformed answers or tags without discarding the entire response.
If `issues_score._score_notes()` finds a collapsed batch&mdash;a single note
object instead of an expected array of N&mdash;it falls back to scoring those
notes individually so none disappear. This provider-agnostic robustness also
helps the Anthropic provider, though we wrote it to handle real failures that
occurred when running the NDA reports with a local model.
