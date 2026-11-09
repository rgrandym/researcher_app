"""Stage timings and token categories from a small synthetic transcript."""

import json

from conftest import FIXTURES
from backend import activity
from backend.activity import stage_timings
from backend.providers.base import Event
from backend.providers.claude import ClaudeParser
from backend.sessions import Segment, Session


def test_stage_timing_keeps_parallel_agent_time_separate_from_wall() -> None:
    events = [
        Event(type="notice", ts=10, data={"kind": "route", "stage": "gather"}),
        Event(type="usage", ts=11, data={"tokens_in": 100, "cached_in": 75,
                                         "cache_written": 20, "tokens_out": 5}),
        Event(type="tool_call", ts=12, data={"id": "scout", "subagent": {"type": "research-scout"}}),
        Event(type="tool_result", ts=15, data={"id": "scout"}),
        Event(type="done", ts=20),
    ]
    row = stage_timings(events)[0]
    assert (row["wall_seconds"], row["agent_seconds"], row["subagent_seconds"]) == (10, 10, 3)
    assert (row["tool_wait_seconds"], row["fresh_in"], row["cached_in"], row["cache_written"]) == (3, 5, 75, 20)


def test_claude_stage_includes_subagent_usage_from_stream() -> None:
    parser = ClaudeParser("claude-sub")
    events = [Event(type="notice", ts=0, provider="claude-sub",
                    data={"kind": "route", "stage": "gather"})]
    for line in (FIXTURES / "claude_subagent.jsonl").read_text().splitlines():
        msg = json.loads(line)
        if msg.get("type") != "control_request":
            events.extend(parser.feed(msg))
    events.append(Event(type="done", provider="claude-sub"))
    row = activity.stage_usage(stage_timings(events))[0]
    assert (row["fresh_in"], row["cached_in"], row["cache_written"], row["tokens_out"]) == (3030, 80000, 1500, 410)
    assert row["tokens_complete"] is True


def test_codex_stage_adds_child_rollout_once_across_continued_turns(monkeypatch) -> None:
    monkeypatch.setattr(activity.usage, "codex_thread_usage", lambda native: {
        "tokens_in": 160, "cached_in": 60, "tokens_out": 20,
    })
    events = [
        Event(type="notice", ts=10, provider="codex-plan", data={"kind": "route", "stage": "gather", "fresh_native": True}),
        Event(type="session", ts=11, provider="codex-plan", data={"session_id": "thread-1"}),
        Event(type="usage", ts=12, provider="codex-plan", data={"tokens_in": 50, "cached_in": 20, "tokens_out": 5}),
        Event(type="done", ts=13, provider="codex-plan"),
        Event(type="notice", ts=14, provider="codex-plan", data={"kind": "route", "stage": "gather", "native_session": "thread-1", "fresh_native": False}),
        Event(type="usage", ts=15, provider="codex-plan", data={"tokens_in": 50, "cached_in": 20, "tokens_out": 5}),
        Event(type="done", ts=16, provider="codex-plan"),
    ]
    rows = activity.stage_usage(stage_timings(events))
    assert len(rows) == 1
    assert (rows[0]["fresh_in"], rows[0]["cached_in"], rows[0]["tokens_out"]) == (100, 60, 20)
    assert rows[0]["tokens_complete"] is True


def test_cost_sums_all_native_threads_in_one_codex_segment(monkeypatch) -> None:
    monkeypatch.setattr(activity.usage, "codex_thread_usage", lambda native: {
        "tokens_in": 100 if native == "first" else 200,
        "cached_in": 20 if native == "first" else 100,
        "tokens_out": 10 if native == "first" else 20,
        "searches": 0,
    })
    session = Session(id="session123", segments=[Segment(
        provider="codex-plan", native_session_id="second",
        native_sessions=["first", "second"], tokens_in=120, tokens_out=12,
    )])
    segment = activity.cost(session, [], {})["segments"][0]
    assert (segment["tokens_in"], segment["cached_in"], segment["tokens_out"]) == (300, 120, 30)


def test_live_stage_wait_advances_without_new_events(monkeypatch) -> None:
    rows = stage_timings([
        Event(type="notice", ts=10, provider="claude-sub", data={"kind": "route", "stage": "review"}),
        Event(type="tool_call", ts=12, provider="claude-sub", data={"id": "verifier"}),
    ])
    monkeypatch.setattr(activity.time, "time", lambda: 20)
    row = activity.stage_usage(rows)[0]
    assert (row["wall_seconds"], row["tool_wait_seconds"], row["agent_seconds"]) == (10, 8, 2)
    assert row["complete"] is False
