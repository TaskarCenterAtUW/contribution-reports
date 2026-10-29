"""LLM clients used by ``--infer-issues``: stdlib urllib only, no SDK dependency.

Two interchangeable clients, both exposing the same public interface so
callers in ``issues.py`` can use either without caring which is active:

  complete(system, user)              → plain text
  complete_json(system, user, hint)   → parsed dict / list

``LLMClient`` talks to the Anthropic Messages API (cloud, requires an API
key). ``OllamaClient`` talks to a local/self-hosted Ollama server's
``/api/chat`` endpoint (no API key). ``OpenAIClient`` talks to any server
that implements the OpenAI ``/v1/chat/completions`` endpoint, such as
llama.cpp's ``llama-server``, vLLM or LM Studio. The caller is responsible
for catching RuntimeError on API failures.

Security: the ``x-api-key`` header value is masked in debug output by
``runtime._dbg`` (which normalises the key to ``X-api-key`` via urllib's
``add_header``).
"""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import runtime
from .llm_providers import (
    DEFAULT_OLLAMA_URL,
    OllamaClient,
    OpenAIClient,
    _JSON_SYSTEM_SUFFIX,
)

ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"
VALID_MODELS = frozenset({"claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5"})


class LLMClient:
    """Wraps the Anthropic Messages API using only the standard library `urllib`.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        transcript_dir: Path | None = None,
    ):
        if model not in VALID_MODELS:
            print(
                f"WARNING: Unknown LLM model '{model}'; using '"
                    f"{DEFAULT_MODEL}' instead",
                file=sys.stderr,
            )
            model = DEFAULT_MODEL
        self._api_key = api_key
        self.model = model
        self._transcript_dir = transcript_dir
        self._seq = 0
        if transcript_dir is not None:
            transcript_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(
        self, system: str, user: str, max_tokens: int = 1024, label: str = "text"
    ) -> str:
        """Performs a single-turn completion and returns the text from the first
        content block.
        """
        body = self._body(system, user, max_tokens)
        resp = self._call(body, label=label)
        return self._first_text(resp)

    def complete_json(
        self,
        system: str,
        user: str,
        max_tokens: int = 4096,
        label: str = "json",
    ) -> dict | list:
        """Returns a parsed dict or list from a completion instructed to return
        JSON.

        We append a JSON-only instruction to the system prompt so all supported
        models comply. This avoids using `output_config` schema enforcement,
        which requires minimum token counts that vary by model. If the model
        includes markdown code fences, we strip them.
        """
        json_system = system + _JSON_SYSTEM_SUFFIX
        body = self._body(json_system, user, max_tokens)
        resp = self._call(body, label=label)
        text = self._first_text(resp).strip()
        # Some models emit fences labeled with JSON, so the code removes those
        # markers if they appear.
        if text.startswith("```"):
            parts = text.split("```")
            # `parts[1]` contains the text inside the first set of fences.
            inner = parts[1]
            if inner.startswith("json"):
                inner = inner[4:]
            text = inner.strip()
        return json.loads(text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _body(self, system: str, user: str, max_tokens: int) -> dict:
        """Constructs the request body for the Messages API."""
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            # The system block employs cache_control because a stable system
            # prompt works well for prompt-caching (the server honors this when
            # the model tier's prefix meets minimum length requirements).
            "system": [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": user}],
        }

    def _call(self, body: dict, label: str = "") -> dict:
        """Sends a POST request to the Messages API and returns the response as a
        parsed dictionary.
        """
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(ANTHROPIC_ENDPOINT, data=data, method="POST")
        req.add_header("x-api-key", self._api_key)
        req.add_header("anthropic-version", ANTHROPIC_API_VERSION)
        req.add_header("content-type", "application/json")
        req.add_header("accept", "application/json")
        runtime._dbg(req)
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req) as resp:
                resp_dict = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic service returned HTTP {exc.code}: "
                                   f"{body_text}") from exc
        duration_ms = int((time.monotonic() - t0) * 1000)
        self._write_transcript(body, resp_dict, label, duration_ms)
        return resp_dict

    def _write_transcript(
        self, body: dict, resp: dict, label: str, duration_ms: int
    ) -> None:
        if self._transcript_dir is None:
            return
        self._seq += 1
        slug = f"{label}_" if label else ""
        filename = f"{self._seq:03d}_{slug}{self.model}.json"
        path = self._transcript_dir / filename

        system_text = ""
        if isinstance(body.get("system"), list) and body["system"]:
            system_text = body["system"][0].get("text", "")
        user_text = ""
        msgs = body.get("messages", [])
        if msgs:
            c = msgs[0].get("content", "")
            user_text = c if isinstance(c, str) else json.dumps(c)

        usage = resp.get("usage", {})
        transcript = {
            "seq": self._seq,
            "label": label,
            "model": self.model,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "max_tokens": body.get("max_tokens"),
            "stop_reason": resp.get("stop_reason"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "system": system_text,
            "user": user_text,
            "response": self._first_text(resp) if resp.get("content") else None,
        }
        path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))
        print(f"  [llm] transcript → {path}", file=sys.stderr)

    @staticmethod
    def _first_text(resp: dict) -> str:
        """Extracts the text from the first content block of type "text".

        If no such block exists in the Anthropic response, we raise a
        `RuntimeError` that includes the `stop_reason`.
        """
        for block in resp.get("content", []):
            if block.get("type") == "text":
                return block["text"]
        raise RuntimeError(
            "Anthropic reply lacked a text block (stop_reason="
                f"{resp.get('stop_reason')})"
        )
