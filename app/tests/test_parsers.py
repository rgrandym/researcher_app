"""Stream handling and the error classifier, on recorded and constructed fixtures."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import lines

from backend import usage
from backend.providers.base import Event
from backend.providers.claude import ClaudeParser
from backend.providers.codex import CodexParser


def replay(parser: Any, name: str) -> list[Event]:
    out: list[Event] = []
    for msg in lines(name):
        if msg.get("type") != "control_request":
            out += parser.feed(msg)
    return out


def test_recorded_claude_turn(data: Any) -> None:
    p = ClaudeParser("claude-sub")
    events = replay(p, "claude_turn.jsonl")
    kinds = [e.type for e in events]
    assert kinds[0] == "session" and "tool_call" in kinds and "tool_result" in kinds
    call = next(e for e in events if e.type == "tool_call")
    assert call.data["name"] == "Bash" and "touch" in call.data["summary"]
    assert any(e.type == "assistant_text" and e.data["text"] == "done" for e in events)
    result = p.outcome(0, "", False)
    assert result.end_reason == "done" and result.native_session == p.session_id and result.cost_usd
    # One message arrives once per content block; its usage counts once.
    usage_events = [e for e in events if e.type == "usage" and e.data.get("tokens_in") is not None]
    assert len(usage_events) == 2


def test_claude_subagent_and_context(data: Any) -> None:
    p = ClaudeParser("claude-sub")
    events = replay(p, "claude_subagent.jsonl")
    agent = next(e for e in events if e.type == "tool_call" and e.data["name"] == "Agent")
    assert agent.data["subagent"] == {"type": "research-scout", "description": "SQ1 market prices"}
    search = next(e for e in events if e.type == "tool_call" and e.data["name"] == "WebSearch")
    assert search.agent == "t_agent"
    done = next(e for e in events if e.type == "tool_result" and e.data["id"] == "t_agent")
    assert done.data["subagent_done"] is True
    final = [e for e in events if e.type == "usage" and e.data.get("context_percent") is not None][
        -1
    ]
    assert final.data["context_percent"] == pytest.approx(100 * 40510 / 200000, abs=0.1)


@pytest.mark.parametrize(
    ("fixture", "stderr", "reason"),
    [
        ("claude_limit.jsonl", "", "limit"),
        ("claude_auth.jsonl", "", "auth"),
        ("claude_network.jsonl", "API Error: Connection error. (ECONNRESET)", "network"),
    ],
)
def test_claude_failures(data: Any, fixture: str, stderr: str, reason: str) -> None:
    p = ClaudeParser("claude-sub")
    replay(p, fixture)
    result = p.outcome(1, stderr, False)
    assert result.end_reason == reason
    if reason == "limit":
        assert result.resets_at == 1791549600


def test_claude_stopped(data: Any) -> None:
    p = ClaudeParser("claude-sub")
    replay(p, "claude_turn.jsonl")
    assert p.outcome(0, "", True).end_reason == "stopped"


def test_codex_turn() -> None:
    p = CodexParser("codex-plan")
    events = replay(p, "codex_turn.jsonl")
    assert events[0].type == "session" and p.thread_id
    names = [e.data["name"] for e in events if e.type == "tool_call"]
    assert names == ["Shell", "Edit", "WebSearch"]
    assert p.web == 1 and "outputs/2026-01-15-lithium-costs/draft.md" in p.files
    texts = [e.data["text"] for e in events if e.type == "assistant_text"]
    assert texts[-1].startswith("Resuming at the report stage")
    assert p.outcome(0, "", False).end_reason == "done"


def test_codex_limit() -> None:
    p = CodexParser("codex-plan")
    replay(p, "codex_limit.jsonl")
    result = p.outcome(1, "", False)
    assert result.end_reason == "limit" and "usage limit" in result.error


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("You've hit your limit · resets 3pm", "limit"),
        ("Claude AI usage limit reached|1791549600", "limit"),
        ("Your credit balance is too low to access the Anthropic API", "limit"),
        ("429 Too Many Requests: rate_limit_error", "limit"),
        ("You've hit your usage limit. Upgrade to Pro", "limit"),
        ("insufficient_quota", "limit"),
        ("Invalid API key · Please run /login", "auth"),
        ("OAuth token has expired. Please obtain a new token", "auth"),
        ("Not logged in · Please run /login", "auth"),
        ("Prompt is too long", "context"),
        ("API Error: Connection error.", "network"),
        ("getaddrinfo ENOTFOUND api.anthropic.com", "network"),
        # Ordinary failures must never read as a spent plan.
        ("Tool Bash failed with exit code 1", "other"),
        ("File does not exist: outputs/x/report.md", "other"),
        ("The model produced an invalid tool call", "other"),
        ("gate.py reports 3 hard failures in report.md", "other"),
    ],
)
def test_classifier(text: str, kind: str) -> None:
    assert usage.classify(text) == kind


def test_reset_from_text() -> None:
    assert usage.reset_from_text("Claude AI usage limit reached|1791549600") == 1791549600.0
    assert usage.reset_from_text("no time here") is None


def test_claude_windows_recorded(data: Any) -> None:
    p = ClaudeParser("claude-sub")
    replay(p, "claude_turn.jsonl")
    windows = {w.name: w for w in usage.claude_usage().windows}
    assert set(windows) >= {"5h", "7d"}
