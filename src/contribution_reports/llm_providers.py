"""Clients for self-hosted and local LLMs, including Ollama and OpenAI-compatible
servers.

We've had `OpenAIClient` inherit from `OllamaClient` so we can share transcript
writing, JSON parsing, and transport logic within a single module. Both clients
are re-exported from `contribution_reports.llm` along with `LLMClient`.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import runtime

DEFAULT_OLLAMA_URL = "http://localhost:11434"

_JSON_SYSTEM_SUFFIX = (
    "\n\nYou MUST respond with valid JSON only — no prose, no markdown fences, "
    "no explanation. Output the JSON object/array directly."
)


class OllamaClient:
    """Provides minimal access to the `/api/chat` endpoint of a self-hosted or
    local Ollama server.

    We've matched the `complete` and `complete_json` interface of `LLMClient`
    to make these interchangeable when `issues.py` expects an `llm` object.
    Because no API key exists for this service, we only need to configure
    `model` and `base_url`. We plumb both values from environment variables and
    CLI flags to support any model served locally.
    """

    _PATH = "/api/chat"
    _SERVER = "Ollama"

    def __init__(
        self,
        model: str,
        base_url: str = DEFAULT_OLLAMA_URL,
        transcript_dir: Path | None = None,
    ):
        self.model = model
        self._base_url = base_url.rstrip("/")
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
        body = self._body(system, user, max_tokens)
        resp = self._call(body, label=label)
        return self._content(resp)

    def complete_json(
        self,
        system: str,
        user: str,
        max_tokens: int = 4096,
        label: str = "json",
    ) -> dict | list:
        """Returns a parsed dict or list from a completion instructed to return
        JSON.

        We pass the `format: "json"` request field for Ollama (which constrains
        decoding to valid JSON on supported models) and include the JSON-only
        system-prompt suffix also used by the Anthropic client. Then, we
        defensively strip markdown code fences.
        """
        json_system = system + _JSON_SYSTEM_SUFFIX
        body = self._body(json_system, user, max_tokens, json_format=True)
        resp = self._call(body, label=label)
        text = self._content(resp).strip()
        if text.startswith("```"):
            parts = text.split("```")
            inner = parts[1]
            if inner.startswith("json"):
                inner = inner[4:]
            text = inner.strip()
        return json.loads(text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _body(
        self, system: str, user: str, max_tokens: int, json_format: bool = False
    ) -> dict:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if json_format:
            body["format"] = "json"
        return body

    def _call(self, body: dict, label: str = "") -> dict:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}{self._PATH}", data=data, method="POST"
        )
        req.add_header("content-type", "application/json")
        runtime._dbg(req)
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req) as resp:
                resp_dict = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{self._SERVER} endpoint returned HTTP {exc.code}: "
                    f"{body_text}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Unable to connect to the {self._SERVER} host via "
                    f"{self._base_url}: {exc.reason}"
            ) from exc
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
        safe_model = self.model.replace("/", "_").replace(":", "_")
        filename = f"{self._seq:03d}_{slug}{safe_model}.json"
        path = self._transcript_dir / filename

        msgs = body.get("messages", [])
        system_text = next(
            (m["content"] for m in msgs if m.get("role") == "system"), ""
        )
        user_text = next((m["content"] for m in msgs if m.get("role") == "user"), "")

        transcript = {
            "seq": self._seq,
            "label": label,
            "model": self.model,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            **self._transcript_stats(body, resp),
            "system": system_text,
            "user": user_text,
            "response": self._message(resp).get("content"),
        }
        path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))
        print(f"  [llm] transcript → {path}", file=sys.stderr)

    @staticmethod
    def _transcript_stats(body: dict, resp: dict) -> dict:
        return {
            "max_tokens": body.get("options", {}).get("num_predict"),
            "done_reason": resp.get("done_reason"),
            "prompt_eval_count": resp.get("prompt_eval_count"),
            "eval_count": resp.get("eval_count"),
        }

    @staticmethod
    def _message(resp: dict) -> dict:
        return resp.get("message") or {}

    @staticmethod
    def _stop_reason(resp: dict) -> str:
        return f"done_reason={resp.get('done_reason')}"

    def _content(self, resp: dict) -> str:
        content = self._message(resp).get("content")
        if not content:
            raise RuntimeError(
                f"The {self._SERVER} reply contained no data ("
                    f"{self._stop_reason(resp)})"
            )
        return content


class OpenAIClient(OllamaClient):
    """Interfaces with servers that provide the OpenAI `/v1/chat/completions` API.

    We reuse the transcript logic, JSON parsing, and transport from
    `OllamaClient`, but we redefine the response shape and request body. When
    we provide the `base_url`, we can include or omit the trailing `/v1`.
    """

    _PATH = "/v1/chat/completions"
    _SERVER = "OpenAI-compatible"

    def __init__(
        self,
        model: str,
        base_url: str,
        transcript_dir: Path | None = None,
    ):
        base_url = base_url.rstrip("/").removesuffix("/v1")
        super().__init__(model, base_url=base_url, transcript_dir=transcript_dir)

    def _body(
        self, system: str, user: str, max_tokens: int, json_format: bool = False
    ) -> dict:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_format:
            body["response_format"] = {"type": "json_object"}
        return body

    @staticmethod
    def _transcript_stats(body: dict, resp: dict) -> dict:
        choice = (resp.get("choices") or [{}])[0]
        usage = resp.get("usage") or {}
        return {
            "max_tokens": body.get("max_tokens"),
            "finish_reason": choice.get("finish_reason"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }

    @staticmethod
    def _message(resp: dict) -> dict:
        return ((resp.get("choices") or [{}])[0]).get("message") or {}

    @staticmethod
    def _stop_reason(resp: dict) -> str:
        return (
            f"finish_reason={((resp.get('choices') or [{}])[0]).get('finish_reason')}"
        )
