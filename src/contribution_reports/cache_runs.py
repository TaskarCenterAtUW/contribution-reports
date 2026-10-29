"""CLI cache-mode operations that recompute data using a cache file and commit
updates back to it.
"""

import json
import sys
from pathlib import Path

from . import paths
from .cli_util import _load_cache
from .llm import DEFAULT_MODEL, DEFAULT_OLLAMA_URL


def run_infer_from_cache(args, env: dict, cache_file: Path, app_filter: tuple) -> dict:
    from .issues import infer_issues
    from .llm import LLMClient, OllamaClient, OpenAIClient
    from .overpass import DEFAULT_OVERPASS_URL
    from .render import filter_app_changesets

    provider = args.llm_provider or env.get("WS_LLM_PROVIDER", "") or "anthropic"
    overpass_url = env.get("WS_OVERPASS_URL", "") or DEFAULT_OVERPASS_URL
    overpass_token = env.get("WS_OVERPASS_TOKEN", "") or None

    transcript_dir = None
    if args.debug_llm:
        transcript_dir = (
            Path(args.debug_llm)
            if Path(args.debug_llm).is_absolute()
            else paths.default_output_dir() / args.debug_llm
        )
        print(f"LLM transcripts → {transcript_dir}")

    if provider in ("ollama", "openai"):
        model = args.llm_model or env.get("WS_LLM_MODEL", "")
        if not model:
            print(
                "ERROR: --llm-model (or WS_LLM_MODEL) is required when "
                    f"using --llm-provider={provider}.",
                file=sys.stderr,
            )
            sys.exit(1)
        llm_url = args.llm_url or env.get("WS_LLM_URL", "")
        if provider == "ollama":
            llm_url = llm_url or env.get("WS_OLLAMA_URL", "") or DEFAULT_OLLAMA_URL
            llm = OllamaClient(model, base_url=llm_url, transcript_dir=transcript_dir)
        else:
            if not llm_url:
                print(
                    "ERROR: --llm-url (or WS_LLM_URL) must be set when using "
                        "--llm-provider=openai.",
                    file=sys.stderr,
                )
                sys.exit(1)
            llm = OpenAIClient(model, base_url=llm_url, transcript_dir=transcript_dir)
        print(
            f"Inferring issues using provider={provider}, model={model}, "
                f"server={llm_url}, and overpass={overpass_url}"
        )
    else:
        api_key = env.get("WS_ANTHROPIC_API_KEY", "")
        if not api_key:
            print(
                "ERROR: WS_ANTHROPIC_API_KEY is not set in .env, so "
                    "--infer-issues cannot run without an Anthropic API key.",
                file=sys.stderr,
            )
            sys.exit(1)
        model = args.llm_model or env.get("WS_LLM_MODEL", "") or DEFAULT_MODEL
        llm = LLMClient(api_key, model, transcript_dir=transcript_dir)
        print(
            f"Inferring issues with provider=anthropic, model={model}, "
                f"overpass={overpass_url}"
        )

    print(f"Loading cached data from {cache_file}")
    data = _load_cache(cache_file, args.date)
    for ws_id_str, ws_data in data["workspaces"].items():
        print(f"\nWorkspace {ws_id_str}: {ws_data.get('title', '?')}")
        # Only survey-app changesets get scored. The baseline workspace import
        # and Rapid edits do not count as quest submissions, so filtering them
        # prevents unrelated tag data from swamping the evidence.
        all_cs = ws_data["changesets"]
        ws_data["changesets"] = filter_app_changesets(all_cs, app_filter)
        try:
            infer_issues(ws_data, llm, overpass_url, overpass_token)
        finally:
            ws_data["changesets"] = all_cs
    cache_file.write_text(json.dumps(data, indent=2, default=str))
    print(f"\nIssues cached to {cache_file}")
    return data


def run_hotspots_from_cache(args, cache_file: Path, app_filter: tuple) -> dict:
    from .hotspots import compute_hotspots, note_points_from_scored
    from .issues import _extract_quest_points
    from .render import filter_app_changesets

    print(f"Recomputing hotspots from cached data in {cache_file}")
    data = _load_cache(cache_file, args.date)
    for ws_id_str, ws_data in data["workspaces"].items():
        rubric_map = ws_data.get("_rubric")
        scored_notes = ws_data.get("_scored_notes")
        if rubric_map is None and scored_notes is None:
            print(
                f"  Workspace {ws_id_str}: no cached rubric or notes, so run "
                    "--infer-issues first"
            )
            continue
        changesets = filter_app_changesets(ws_data.get("changesets", []), app_filter)
        q_pts = _extract_quest_points(changesets, rubric_map or {})
        n_pts = note_points_from_scored(scored_notes or [])
        hotspots = compute_hotspots(q_pts, n_pts)
        ws_data["hotspots"] = hotspots
        print(f"  Workspace {ws_id_str}: {len(hotspots)} hotspots")
    cache_file.write_text(json.dumps(data, indent=2, default=str))
    print(f"Hotspots cached to {cache_file}")
    return data
