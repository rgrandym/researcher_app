"""Streamed Claude token totals and plan status from rate-limit events."""

from __future__ import annotations

import json
from typing import Any

from backend import usage
from backend.providers.claude import ClaudeParser


def test_claude_streamed_usage_uses_deltas_then_result_total() -> None:
    parser = ClaudeParser("claude-sub")
    message = {"type": "assistant", "message": {"id": "one", "model": "claude-sonnet", "content": [],
               "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 2}}}
    first = parser.feed(message)
    repeat = parser.feed(message)
    larger = json.loads(json.dumps(message))
    larger["message"]["usage"]["output_tokens"] = 5
    growth = parser.feed(larger)
    final = parser.feed({"type": "result", "usage": {"input_tokens": 10,
                         "cache_read_input_tokens": 90, "output_tokens": 12}})
    events = [*first, *repeat, *growth, *final]
    assert [(e.data["tokens_in"], e.data["tokens_out"]) for e in events] == [
        (100, 2), (0, 3), (0, 7)
    ]


def test_claude_rejection_preserves_reported_share(data: Any) -> None:
    usage.record_claude_limit({
        "rateLimitType": "five_hour", "status": "rejected", "utilization": 0.27
    })
    window = usage.claude_usage().windows[0]
    assert (window.name, window.used_percent, window.status) == ("5h", 27, "rejected")


def _live(monkeypatch: Any, owner: str = "me@example.com", expires_in: float = 3600,
          status: int = 200) -> list[str]:
    import time
    import urllib.error

    calls: list[str] = []
    monkeypatch.setattr(usage, "_oauth_token", lambda config_dir: ("tok", time.time() + expires_in))

    def get(url: str, token: str) -> Any:
        calls.append(url)
        if status != 200:
            raise urllib.error.HTTPError(url, status, "no", None, None)  # type: ignore[arg-type]
        if url == usage.PROFILE_URL:
            return {"account": {"email": owner}}
        return {"five_hour": {"utilization": 42.0, "resets_at": "2099-01-01T00:00:00+00:00"},
                "seven_day": {"utilization": 100.0, "resets_at": "2099-01-02T00:00:00+00:00"}}

    monkeypatch.setattr(usage, "_get", get)
    return calls


def test_live_read_stores_windows_and_throttles(data: Any, monkeypatch: Any) -> None:
    calls = _live(monkeypatch)
    assert usage.fetch_claude_usage("claude-x", "/cfg", "Me@Example.com") == ""
    windows = usage.claude_usage("claude-x", expected_email="me@example.com").windows
    assert [(w.name, w.used_percent, w.status) for w in windows] == [
        ("5h", 42.0, "allowed"), ("7d", 100.0, "rejected")]
    assert usage.fetch_claude_usage("claude-x", "/cfg", "me@example.com") == ""
    assert calls.count(usage.USAGE_URL) == 1      # the second read came inside MIN_FETCH_S


def test_live_read_refuses_another_accounts_token(data: Any, monkeypatch: Any) -> None:
    _live(monkeypatch, owner="other@example.com")
    assert "other@example.com" in usage.fetch_claude_usage("claude-x", "/cfg", "me@example.com")
    assert usage.claude_usage("claude-x", expected_email="me@example.com").windows == []


def test_live_read_never_uses_an_expired_token(data: Any, monkeypatch: Any) -> None:
    calls = _live(monkeypatch, expires_in=-10)
    assert "expired" in usage.fetch_claude_usage("claude-x", "/cfg", "me@example.com")
    assert calls == []


def test_live_read_backs_off_after_refusal(data: Any, monkeypatch: Any) -> None:
    calls = _live(monkeypatch, status=429)
    assert "refused" in usage.fetch_claude_usage("claude-x", "/cfg", "me@example.com")
    usage.fetch_claude_usage("claude-x", "/cfg", "me@example.com")
    assert len(calls) == 1


def test_keychain_service_names() -> None:
    assert usage.keychain_service("") == "Claude Code-credentials"
    assert usage.keychain_service("/home/example/.claude-work") == "Claude Code-credentials-af7cd477"
