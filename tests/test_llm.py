import json

import pytest

from contribution_reports import llm
from contribution_reports.llm import OllamaClient, OpenAIClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def capture_requests(monkeypatch, payload):
    sent = []

    def fake_urlopen(req):
        sent.append({"url": req.full_url, "body": json.loads(req.data)})
        return FakeResponse(payload)

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    return sent


def openai_reply(content, finish_reason="stop"):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_openai_client_posts_chat_completions(monkeypatch):
    sent = capture_requests(monkeypatch, openai_reply("hello"))
    client = OpenAIClient("qwen", base_url="http://localhost:11435")
    assert client.complete("sys", "hi", max_tokens=50) == "hello"
    assert sent[0]["url"] == "http://localhost:11435/v1/chat/completions"
    assert sent[0]["body"] == {
        "model": "qwen",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ],
        "max_tokens": 50,
        "stream": False,
    }


def test_openai_client_works_with_base_urls_ending_in_v1(monkeypatch):
    sent = capture_requests(monkeypatch, openai_reply("ok"))
    OpenAIClient("qwen", base_url="http://localhost:11435/v1/").complete("s", "u")
    assert sent[0]["url"] == "http://localhost:11435/v1/chat/completions"


def test_openai_client_requests_json_object_response_format(monkeypatch):
    sent = capture_requests(monkeypatch, openai_reply('```json\n{"ok": true}\n```'))
    result = OpenAIClient("qwen", base_url="http://h").complete_json("sys", "u")
    assert result == {"ok": True}
    assert sent[0]["body"]["response_format"] == {"type": "json_object"}


def test_openai_client_raises_runtime_error_on_empty_content(monkeypatch):
    capture_requests(monkeypatch, openai_reply("", finish_reason="length"))
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        OpenAIClient("qwen", base_url="http://h").complete("s", "u")


def test_openai_client_writes_transcript(monkeypatch, tmp_path):
    capture_requests(monkeypatch, openai_reply("hello"))
    OpenAIClient("org/qwen:1b", base_url="http://h", transcript_dir=tmp_path).complete(
        "sys", "hi", max_tokens=50, label="summary"
    )
    [path] = tmp_path.iterdir()
    assert path.name == "001_summary_org_qwen_1b.json"
    transcript = json.loads(path.read_text())
    assert transcript["max_tokens"] == 50
    assert transcript["finish_reason"] == "stop"
    assert transcript["prompt_tokens"] == 10
    assert transcript["completion_tokens"] == 5
    assert transcript["response"] == "hello"


def test_ollama_client_posts_to_api_chat(monkeypatch):
    sent = capture_requests(monkeypatch, {"message": {"content": "hi"}, "done_reason": "stop"})
    assert OllamaClient("qwen", base_url="http://h").complete("s", "u", max_tokens=7) == "hi"
    assert sent[0]["url"] == "http://h/api/chat"
    assert sent[0]["body"]["options"] == {"num_predict": 7}
