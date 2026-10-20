"""Codex usage read from its rollout files: the main thread plus its own subagents only."""

import json

from backend import usage


def _write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def _tokens(i, o):
    return {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": i, "output_tokens": o}}}}


def test_sums_parent_and_its_subagents_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    day = tmp_path / "sessions" / "2026" / "10" / "09"
    parent = "aaaa-1111"
    _write(day / f"rollout-2026-10-09T17-20-57-{parent}.jsonl", [
        {"type": "session_meta", "payload": {"id": parent}},
        _tokens(100, 10), _tokens(300, 30),  # cumulative: the last one counts
        {"type": "response_item", "payload": {"type": "web_search_call"}},
    ])
    _write(day / "rollout-2026-10-09T17-21-40-bbbb.jsonl", [
        {"type": "session_meta", "payload": {"id": "bbbb", "parent_thread_id": parent}},
        _tokens(50, 5),
    ])
    _write(day / "rollout-2026-10-09T17-22-00-cccc.jsonl", [  # someone else's thread
        {"type": "session_meta", "payload": {"id": "cccc", "parent_thread_id": "other"}},
        _tokens(999, 99),
    ])
    usage._rollout_cache.clear()
    got = usage.codex_thread_usage(parent)
    assert got == {"tokens_in": 350, "tokens_out": 35, "searches": 1, "threads": 2}


def test_unknown_thread_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert usage.codex_thread_usage("nope") is None


def test_child_threads_found_from_rollout_meta(tmp_path, monkeypatch):
    """`codex exec --json` streams no spawn item; the subagent's rollout records it."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    day = tmp_path / "sessions" / "2026" / "10" / "19"
    parent = "aaaa-1111"
    _write(day / f"rollout-2026-10-19T09-05-00-{parent}.jsonl", [{"type": "session_meta", "payload": {"id": parent}}])
    _write(day / "rollout-2026-10-19T09-05-20-bbbb.jsonl", [{"type": "session_meta", "payload": {
        "id": "bbbb", "parent_thread_id": parent,
        "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent, "agent_path": "/root/intro_critic"}}}}}])
    _write(day / "rollout-2026-10-19T09-06-00-cccc.jsonl", [{"type": "session_meta", "payload": {"id": "cccc", "parent_thread_id": "other"}}])
    children = usage.codex_child_threads(parent, 0)
    assert [c["id"] for c in children] == ["bbbb"]
    assert children[0]["path"] == "/root/intro_critic"
    assert usage.codex_child_threads(parent, 4_000_000_000) == []  # none since a later time
    assert usage.codex_child_threads(None, 0) == []
