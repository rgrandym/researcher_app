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
