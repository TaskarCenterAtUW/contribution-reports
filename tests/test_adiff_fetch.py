import gzip
import http.client
import json
import urllib.parse

import pytest

from contribution_reports.osw import adiff


class FakeResponse:
    """Mock urlopen context manager that yields a static body."""

    def __init__(self, body, encoding=None):
        self._body = body
        self.headers = {"Content-Encoding": encoding} if encoding else {}

    def read(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_json_returns_parsed_body(monkeypatch):
    monkeypatch.setattr(adiff.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResponse(b'{"actions": []}'))
    assert adiff.fetch_json("http://x", {}) == {"actions": []}


def test_fetch_json_decompresses_gzip(monkeypatch):
    body = gzip.compress(b'{"actions": [1]}')
    monkeypatch.setattr(adiff.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResponse(body, encoding="gzip"))
    assert adiff.fetch_json("http://x", {}) == {"actions": [1]}


def test_fetch_json_succeeds_after_multiple_retries(monkeypatch):
    calls = {"n": 0}

    def flaky(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return FakeResponse(http.client.IncompleteRead(b"{partial", 99))
        return FakeResponse(b'{"actions": []}')

    monkeypatch.setattr(adiff.urllib.request, "urlopen", flaky)
    assert adiff.fetch_json("http://x", {}, sleep=lambda s: None) == {"actions": []}
    assert calls["n"] == 3


def test_fetch_json_raises_adiff_fetch_error_after_all_attempts(monkeypatch):
    def always_truncated(req, timeout=None):
        return FakeResponse(http.client.IncompleteRead(b"{partial", 99))

    monkeypatch.setattr(adiff.urllib.request, "urlopen", always_truncated)
    with pytest.raises(adiff.AdiffFetchError):
        adiff.fetch_json("http://x", {}, sleep=lambda s: None)


def test_fetch_json_raises_adiff_fetch_error_on_incomplete_read(monkeypatch):
    """Checks that `adiff.fetch_json` raises `adiff.AdiffFetchError` when
    `urllib.request.urlopen` returns an `http.client.IncompleteRead` with a
    partial body.

    We need this regression test because absorbing `IncompleteRead.partial`
    silently loses data.
    """
    monkeypatch.setattr(adiff.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResponse(
                            http.client.IncompleteRead(b'{"actions": [1,2', 40)))
    with pytest.raises(adiff.AdiffFetchError):
        adiff.fetch_json("http://x", {}, sleep=lambda s: None)


def test_fetch_json_raises_fetch_error_when_body_cannot_be_parsed(monkeypatch):
    monkeypatch.setattr(adiff.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResponse(b"<html>502</html>"))
    with pytest.raises(adiff.AdiffFetchError):
        adiff.fetch_json("http://x", {}, sleep=lambda s: None)


@pytest.mark.parametrize("body", [b"[]", b"null"])
def test_fetch_json_rejects_payload_that_is_not_a_dict(monkeypatch, body):
    """Rejects valid JSON payloads that lack a dictionary shape to enforce the
    `-> dict` contract.

    We need this restriction because callers expect to use `.get()` on the
    result.
    """
    monkeypatch.setattr(adiff.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResponse(body))
    with pytest.raises(adiff.AdiffFetchError):
        adiff.fetch_json("http://x", {}, sleep=lambda s: None)


def test_fetch_adiff_returns_actions_from_json(monkeypatch):
    monkeypatch.setattr(adiff, "fetch_json",
                        lambda url, headers, **kw: {"actions": [{"type": "create"}]})
    assert adiff.fetch_adiff("http://api/v1", 1280, 63, "tok") == [{"type": "create"}]


def test_fetch_changeset_list_paginates_and_removes_duplicates(monkeypatch):
    pages = [
        {"changesets": [{"id": i, "created_at": f"2026-06-{i:02d}T00:00:00Z"}
                        for i in range(25, 0, -1)]},
        {"changesets": [{"id": 1, "created_at": "2026-06-01T00:00:00Z"}]},
    ]
    seen = {"n": 0}
    urls = []

    def fake(url, headers, **kw):
        urls.append(url)
        result = pages[min(seen["n"], len(pages) - 1)]
        seen["n"] += 1
        return result

    monkeypatch.setattr(adiff, "fetch_json", fake)
    result = adiff.fetch_changeset_list("http://osm", 1280, "tok")
    assert len(result) == 25
    assert len({c["id"] for c in result}) == 25

    # We cap every request at PAGE_SIZE (25) because the server truncates
    # changeset-list responses that exceed ~64 KB.
    assert len(urls) == 2
    for url in urls:
        query = urllib.parse.urlsplit(url).query
        params = dict(p.split("=", 1) for p in query.split("&"))
        assert params.get("limit") == "25"

    # We don't set a lower bound for the first page.
    first_params = dict(p.split("=", 1)
                        for p in urllib.parse.urlsplit(urls[0]).query.split("&"))
    assert "time" not in first_params

    # We need to provide an explicit lower bound for the second page. This
    # server returns HTTP 400 when we use the bare "time=,<ts>" format, so we
    # always prepend "1970-01-01T00:00:00Z,". The code quotes the entire span
    # exactly, converting ":" to "%3A" and "," to "%2C".
    second_params = dict(p.split("=", 1)
                         for p in urllib.parse.urlsplit(urls[1]).query.split("&"))
    assert "time" in second_params
    expected_span = "1970-01-01T00:00:00Z,2026-06-01T00:00:00Z"
    assert second_params["time"] == urllib.parse.quote(expected_span)


def test_cache_saves_and_loads_through_gzip(tmp_path):
    path = tmp_path / "osw_test.json.gz"
    data = {"workspaces": {"1280": {"adiffs": {"63": [{"type": "create"}]}}}}
    adiff.save_cache(data, path)
    assert path.exists()
    with gzip.open(path, "rt") as f:
        assert json.load(f) == data
    assert adiff.load_cache(path) == data
