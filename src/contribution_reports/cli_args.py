"""Argparse configuration for the command-line interface entry point."""

import argparse

from .llm import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, VALID_MODELS


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate TDEI Workspaces contribution report"
    )
    parser.add_argument(
        "workspace_ids", nargs="*", type=int, help="Workspace IDs to include"
    )
    parser.add_argument("--date", help="Set the report date as YYYY-MM-DD "
                                           "(default: yesterday)")
    parser.add_argument(
        "--tz",
        metavar="ZONE",
        default=None,
        help="IANA time zone for --date and report header dates, such as "
                 "America/Los_Angeles (default: UTC)",
    )
    parser.add_argument(
        "--all-dates",
        action="store_true",
        help="Fetch changesets from all dates instead of a single day by "
                 "paginating through the full workspace history",
    )
    parser.add_argument(
        "--cached",
        action="store_true",
        help="Use existing changesets_raw.json instead of re-fetching data",
    )
    parser.add_argument(
        "--refresh-meta",
        action="store_true",
        help="Fetch updated workspace titles and quest definitions from the "
                 "API while keeping existing changesets",
    )
    parser.add_argument(
        "--refresh-notes",
        action="store_true",
        help="Re-fetch note counts using cached changesets instead of "
                 "downloading them again",
    )
    parser.add_argument(
        "--refresh-geoms",
        action="store_true",
        help="Re-fetch way geometry for quest elements in cached changesets "
                 "to add per-element position data for accurate map markers "
                 "in batch changesets",
    )
    parser.add_argument(
        "--cache-file",
        default=None,
        help="Path to the cache JSON file (default: "
                 "./output/changesets_raw.json)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to the output HTML file (default: ./output/report.html)",
    )
    parser.add_argument(
        "--offline",
        metavar="PATH",
        default=None,
        help="Path to a changeset archive in zip or directory format for "
                 "ingestion without contacting the workspace API",
    )
    parser.add_argument(
        "--quest-file",
        metavar="PATH",
        default=None,
        help="Path to a quest definition JSON file when using --offline",
    )
    parser.add_argument(
        "--auto-detect-event-window",
        action="store_true",
        help="Isolate the densest contiguous activity session to narrow "
                 "changesets, which sheds isolated setup/test edits "
                 "(default: render all app changesets)",
    )
    parser.add_argument(
        "--app-filter",
        action="append",
        metavar="PREFIX",
        default=None,
        help="created_by prefix identifying survey-app changesets; repeatable (default: WS_APP_FILTER csv, else the built-in list)",
    )
    parser.add_argument(
        "--no-app-filter",
        action="store_true",
        help="Include all changesets by disabling the created_by filter",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Find workspaces using a --title-match prefix or provided "
                 "workspace IDs, auto-detect event windows, and write "
                 "individual caches and reports to discovered/ in the output "
                 "directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --discover: lists each workspace's event window and "
                 "fetches changeset history, but skips quest-definition, "
                 "OSC, and notes fetches and writes nothing",
    )
    parser.add_argument(
        "--title-match",
        action="append",
        metavar="PREFIX",
        default=None,
        help="Workspace title prefix to discover with --discover; this flag "
                 "is repeatable and required unless workspace IDs are given",
    )
    parser.add_argument(
        "--report-title",
        metavar="TITLE",
        default=None,
        help="Sets the report <h1> and <title> (default: 'Contribution "
                 "Report')",
    )
    parser.add_argument(
        "--workspace-title",
        metavar="TITLE",
        default=None,
        help="Set the title for every workspace section",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to .env file (default: WS_ENV_FILE env var, else nearest .env walking up from CWD; absence is tolerated when not fetching live data)",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Print HTTP request URLs and "
                                                 "headers"
    )
    parser.add_argument(
        "--debug-llm",
        metavar="DIR",
        nargs="?",
        const="llm-transcripts",
        default=None,
        help=(
            "Saves LLM call transcripts with system prompts, user inputs, "
                "responses, token counts, and timing to DIR (default: "
                "llm-transcripts/ in the default output dir (./output)) as "
                "numbered JSON files."
        ),
    )
    parser.add_argument(
        "--infer-issues",
        action="store_true",
        help=(
            "Infers infrastructure issues from quest answers and notes using "
                "the Anthropic API and Overpass, saving results to a cache "
                "file to avoid repeated API calls when using --cached. "
                "Requires WS_ANTHROPIC_API_KEY."
        ),
    )
    parser.add_argument(
        "--llm-provider",
        default=None,
        choices=("anthropic", "ollama", "openai"),
        help=(
            "LLM provider for --infer-issues (default: env WS_LLM_PROVIDER "
                "or 'anthropic'). Use 'ollama' for a local or self-hosted "
                "Ollama server instead of Anthropic. Use 'openai' for "
                "servers like vLLM, LM Studio, or llama.cpp's llama-server "
                "that expose an OpenAI-compatible /v1/chat/completions "
                "endpoint."
        ),
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        metavar="MODEL",
        help=(
            "Specifies the model for --infer-issues (default: env "
                f"WS_LLM_MODEL, or {DEFAULT_MODEL} for the anthropic "
                "provider). Anthropic supports these models: "
                f"{', '.join(sorted(VALID_MODELS))}. The ollama and openai "
                "providers accept any model served by the target server."
        ),
    )
    parser.add_argument(
        "--llm-url",
        "--ollama-url",
        dest="llm_url",
        default=None,
        metavar="URL",
        help=(
            "Base URL for ollama and openai servers (default: env "
                "WS_LLM_URL; for ollama, then WS_OLLAMA_URL or "
                f"{DEFAULT_OLLAMA_URL}). The openai provider requires this "
                "flag."
        ),
    )
    parser.add_argument(
        "--no-positive",
        action="store_true",
        help=(
            "Hides 'Surveyed Well' and positive-scoring segments in the "
                "report, which hides the panel and collapses the map ramp to "
                "yellow->red. The cache retains all inference data, so "
                "--cached can toggle this view."
        ),
    )
    parser.add_argument(
        "--hotspots",
        action="store_true",
        help=(
            "Recompute consensus hotspots using rubric and note scores from "
                "a previous --infer-issues run. This makes zero API calls "
                "and updates the cache to enable re-rendering with --cached."
        ),
    )
    return parser.parse_args(argv)
