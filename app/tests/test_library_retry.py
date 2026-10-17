"""Temporary source failures get bounded retries; permanent failures do not."""

import importlib.util
import urllib.error
from pathlib import Path


def _library():
    path = Path(__file__).resolve().parents[2] / ".claude/scripts/library.py"
    spec = importlib.util.spec_from_file_location("source_library", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    headers = {"Content-Type": "text/plain"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _):
        return b"source text"

    def geturl(self):
        return "https://example.org/source"


def test_rate_limit_waits_and_retries(monkeypatch):
    library = _library()
    calls = iter([urllib.error.HTTPError("https://example.org/source", 429, "wait", {"Retry-After": "3"}, None), Response()])
    waits = []

    def open_url(*_, **__):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(library.urllib.request, "urlopen", open_url)
    monkeypatch.setattr(library.time, "sleep", waits.append)
    assert library.download("https://example.org/source") == ("text/plain", b"source text", "https://example.org/source")
    assert waits == [3]


def test_missing_source_does_not_retry(monkeypatch):
    library = _library()
    calls = []

    def open_url(*_, **__):
        calls.append(1)
        raise urllib.error.HTTPError("https://example.org/missing", 404, "missing", {}, None)

    monkeypatch.setattr(library.urllib.request, "urlopen", open_url)
    try:
        library.download("https://example.org/missing")
    except urllib.error.HTTPError:
        pass
    else:
        raise AssertionError("A missing page should fail")
    assert len(calls) == 1
