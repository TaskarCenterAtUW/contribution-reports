# CONTRIBUTION REPORTS — Package Knowledge Base

## OVERVIEW
Python 3.12+ `contribution_reports` package fetching OSM changeset data to render self-contained HTML contribution reports with LLM-powered infrastructure issue inference. Installable package exposing three console scripts: `contribution-report` (quest report, with a `--discover` mode for title-prefix workspace discovery), `osw-report` (OSW change report), and `report-summary` (program one-pager from cached events).

## STRUCTURE
```
contribution-reports/
├── src/contribution_reports/  # ~50 modules + templates/ + assets/
│   └── osw/                   # OSW change report: adiff-sourced, quest-free, deterministic
├── examples/                  # Example fetch inputs: changeset.zip, renton-quest.json, quests/, events.json
├── docs/                      # quest-settings.schema.json (quest long-settings API payload)
├── tests/
└── output/                    # ALL generated artifacts (gitignored) — changesets_*.json, report_*.html, discovered/
```
Output is resolved relative to the process working directory (`paths.default_output_dir()`); `--discover` writes per-workspace caches/reports under `output/discovered/`. Full module map in `README.md`. Key layers:

| Layer | Modules | Role |
|-------|---------|------|
| CLI / orchestration | `cli.py`, `cli_args.py`, `cli_util.py`, `cache_runs.py`, `render.py`, `discover.py`, `summary.py`, `summary_core.py` | Argparse, shared input/cache helpers, cache-mode runs, mode dispatch, title-prefix discovery, one-pager, Jinja2 rendering |
| Issue inference | `issues.py`, `issues_prompts.py`, `issues_parse.py`, `issues_points.py`, `issues_geo.py`, `issues_score.py`, `issues_evidence.py`, `hotspots.py` | 8-step LLM pipeline orchestrator + its prompt/schema, LLM-output parsing, point extraction, geometry grouping, scoring, evidence-shaping siblings + consensus clustering |
| LLM transport | `llm.py`, `llm_providers.py` | `LLMClient` (Anthropic); `OllamaClient` + `OpenAIClient` for local/self-hosted servers, shared `complete()`/`complete_json()` interface |
| Data fetching | `fetch.py`, `offline.py`, `offline_validate.py`, `offline_quest_validation.py`, `workspace_api.py`, `auth.py`, `net.py` | Live OSM API, offline archives + ingest shape/quest validation, tokens |
| Analysis | `analysis.py`, `classify.py`, `markers.py`, `popup.py`, `osc.py`, `events.py` | Classification, markers, popups, event windows |
| Rendering support | `render_builders.py`, `render_mapdata.py`, `render_format.py` | Section-context builders, map-layer JSON payloads, date/attribute formatting |
| Geometry | `overpass.py`, `overpass_graph.py`, `segments.py` | Overpass road fetch, intersection-graph primitives, block-face labeling |
| Config | `constants.py`, `env.py`, `paths.py`, `quests.py`, `runtime.py` | Dimensions, weights, env, output paths, quest indexes |

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Add CLI flag | `cli_args.py:parse_args()` + `cli.py:main()` else-if chain | Flag priority order matters |
| Change discovery / window skip | `discover.py:run_discover()` | Title match, window detection, per-workspace outputs |
| Change report layout | `templates/page.html.j2`, `section.html.j2` | Shared macros in `macros.html.j2` |
| Modify issue inference steps | `issues.py` orchestrator + `issues_*` siblings | Prompts in `issues_prompts.py`, scoring in `issues_score.py`; constants live in `constants.py` |
| Add new dimension | `constants.py:DIMENSIONS` + `DIMENSION_WEIGHTS` | Also update `render.py` panel UI |
| Change map markers | `markers.py` (backend) + `assets/map.js` (frontend) | Quest=circles, created=diamonds |
| Offline format support | `offline.py:load_offline_archive()` | Zip or dir with `manifest.json`; input shape checks in `offline_validate.py` |
| Cache schema evolution | `cli_util.py:_load_cache()` | Must handle old files gracefully |
| OSW report entity/attribute catalog | `contribution_reports/osw/schema.py` | Declarative — adding an entity is a table edit |
| OSW report rules | `contribution_reports/osw/rules.py` | Two families: conformance vs network |
| Adiff fetching / contract rules | `contribution_reports/osw/adiff.py` | Rules A and C live here |

## CONVENTIONS
- **Cache-first**: All fetched data saved to JSON before rendering. `--cached` = zero API cost.
- **App filter always on**: Changesets filtered by `created_by` starting with the survey-app prefixes `AVIV ScoutRoute`, `GIG`, `GoInfoGame`; configurable via `--app-filter`, `WS_APP_FILTER`, disabled by `--no-app-filter`.
- **Photo dedup via seen set**: Oldest-first processing; `seen_photo_urls: set[str]` prevents re-attribution.
- **Fuzzy quest matching**: Bare (`surface`) and `ext:`-prefixed aliases registered for both directions.
- **Env via bash subprocess**: `env.py:load_env()` sources the resolved `.env` with `set -a && source`. Never parse `.env` directly. Resolution: `--env-file`, then `WS_ENV_FILE`, then nearest `.env` walking up from CWD; none is tolerated; shell `WS_*` override the file.
- **Dimension scoring is orthogonal**: Trav (1.0), conn (1.0), safety (0.5). Combined = dimension-weighted mean.

## ANTI-PATTERNS (THIS PACKAGE)
- **No per-changeset LLM calls** — rubric computed once per workspace, applied deterministically after
- **Never drop single-evidence clusters** — min size is 1; thinness reflected in confidence score
- **Do not commit generated HTML or cache JSON** — build artifacts live in `output/` (gitignored), regenerated from caches with `--cached`
- **No new cache keys without backward compat** — `cli_util.py:_load_cache()` must handle missing fields
- **No combined NDA report** — `--discover` writes one standalone cache+report per workspace only; don't reintroduce a multi-workspace combined file
- **Never count adiff context rows as edits** — an action belongs to a changeset only when `new.changeset` matches; counting context rows inflates volume ~34% and misattributes authorship
- **Never classify a delete from `new.tags`** — deletes carry cleared tags; use `old.tags`
- **Never absorb a truncated HTTP body** — no `except IncompleteRead: return e.partial`; retry then raise
- **Do not apply the survey-app filter in the OSW report** — it empties editor-driven workspaces

## NOTES
- Issues pipeline stores `_rubric` and `_scored_notes` on workspace data for offline LLM output inspection
- Hotspots auto-compute alongside issues during `--infer-issues`; standalone via `--hotspots` at zero API cost
- Offline mode degrades: no notes, bbox centroid fallback, all tags shown as "added"
- Confidence = `0.4 qty + 0.4 agreement + 0.2 corroboration`; quantity uses distinct voices, saturates at 3
