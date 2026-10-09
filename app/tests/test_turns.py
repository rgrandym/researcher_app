"""A session that starts on Claude Code, is cut off by a simulated limit, and finishes on
Codex without redoing a completed stage; permission prompts; switching back."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from conftest import RUN, FakeProvider

from backend import config, sessions
from backend.turns import TurnManager


def _manager(claude: list[str], codex: list[str]) -> tuple[TurnManager, FakeProvider, FakeProvider]:
    c = FakeProvider("claude-sub", claude)
    x = FakeProvider("codex-plan", codex)
    return TurnManager({"claude-sub": c, "codex-plan": x}), c, x


async def _settle(m: TurnManager, sid: str) -> None:
    for _ in range(200):
        r = m.running.get(sid)
        if not (r and r.task and not r.task.done()):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("turn did not finish")


def test_limit_then_continue_on_codex(root: Path) -> None:
    config.save_settings({"fallback_order": ["claude-sub", "codex-plan"]})
    m, claude, codex = _manager(["claude_limit.jsonl"], ["codex_turn.jsonl"])

    async def go() -> None:
        s = sessions.create()
        s.runs = [RUN]
        sessions.save(s)
        await m.send(
            s.id,
            "/research how much does battery-grade lithium cost per tonne in 2026",
            "claude-sub",
        )
        await _settle(m, s.id)

        s = sessions.load(s.id)
        assert s.current() is None and s.segments[0].end_reason == "limit"
        limit = [e for e in sessions.transcript(s.id) if e.type == "error"][-1]
        assert (
            limit.data["kind"] == "limit"
            and limit.data["next"] == "codex-plan"
            and limit.data["resets_at"] == 1791549600
        )
        assert codex.prompts == []  # the app never switches by itself

        # The cut-off turn was writing evidence.jsonl (the fixture's Write call) when it stopped.
        (root / "outputs" / RUN / "evidence.jsonl").touch()
        await m.switch(s.id, "codex-plan", reason="limit")
        await _settle(m, s.id)

        prompt, native = codex.prompts[0]
        assert native is None
        assert prompt.startswith("# Continuing a session from another agent")
        assert "1. /research how much does battery-grade lithium cost per tonne in 2026" in prompt
        assert f"Resume at: the report stage of outputs/{RUN}" in prompt
        assert "Do not redo a stage that run_check reports complete." in prompt
        assert "FLAGGED: line 3 is not valid JSON" in prompt

        s = sessions.load(s.id)
        assert [seg.provider for seg in s.segments] == ["claude-sub", "codex-plan"]
        assert s.segments[1].native_session_id == "0199aaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee"
        assert (config.DATA / "sessions" / s.id / "handoffs" / "h1.md").read_text() == prompt
        assert not (root / "outputs" / RUN / "handoffs").exists()  # the run layout is unchanged
        events = sessions.transcript(s.id)
        assert [e.type for e in events].count("handoff") == 1
        assert events[-1].type == "done" and events[-1].data["end_reason"] == "done"

    asyncio.run(go())


def test_switch_back_resumes_native_session(root: Path) -> None:
    m, claude, codex = _manager(
        ["claude_subagent.jsonl", "claude_subagent.jsonl"], ["codex_turn.jsonl"]
    )

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "first", "claude-sub")
        await _settle(m, s.id)
        await m.send(s.id, "second, on codex", "codex-plan")
        await _settle(m, s.id)
        await m.send(s.id, "third, back on claude", "claude-sub")
        await _settle(m, s.id)
        prompt, native = claude.prompts[-1]
        assert native == "11111111-2222-3333-4444-555555555555"  # Claude's own session, resumed
        assert prompt.startswith("# Back in this session")
        assert (
            "second, on codex" in prompt
            and "first"
            not in prompt.split("## The author's requests since you left")[1].split("##")[0]
        )
        assert prompt.rstrip().endswith("third, back on claude")
        assert len(sessions.load(s.id).segments) == 3

    asyncio.run(go())


def test_permission_round_trip(root: Path) -> None:
    m, claude, _ = _manager(["claude_permission.jsonl"], ["codex_turn.jsonl"])
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def go() -> None:
        m.hub.everyone.add(queue)
        s = sessions.create()
        await m.send(s.id, "clean up", "claude-sub")
        while True:
            msg = await asyncio.wait_for(queue.get(), 2)
            if msg.get("type") == "event" and msg["event"]["type"] == "permission_request":
                break
        await m.answer(s.id, "perm-1", "always")
        await _settle(m, s.id)
        answers = [e for e in sessions.transcript(s.id) if e.type == "permission_answer"]
        assert answers and answers[0].data["decision"] == "always"
        assert {"tool": "Bash", "rule": "rm -rf outputs/tmp"} in config.load_settings()[
            "allow_rules"
        ]

        # The rule now answers the same request without asking.
        await m.send(s.id, "again", "claude-sub")
        await _settle(m, s.id)
        requests = [e for e in sessions.transcript(s.id) if e.type == "permission_request"]
        assert len(requests) == 1

    asyncio.run(go())


def test_stop_denies_waiting_permission(root: Path) -> None:
    m, _, _ = _manager(["claude_permission.jsonl"], ["codex_turn.jsonl"])
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def go() -> None:
        m.hub.everyone.add(queue)
        s = sessions.create()
        await m.send(s.id, "clean up", "claude-sub")
        while True:
            msg = await asyncio.wait_for(queue.get(), 2)
            if msg.get("type") == "event" and msg["event"]["type"] == "permission_request":
                break
        await m.stop(s.id)
        await _settle(m, s.id)
        answers = [e for e in sessions.transcript(s.id) if e.type == "permission_answer"]
        assert answers[0].data["decision"] == "deny"

    asyncio.run(go())


def test_runs_detected_and_locked(root: Path) -> None:
    (root / "outputs" / "2026-01-15-lithium-costs").mkdir(exist_ok=True)
    m, _, _ = _manager(["claude_subagent.jsonl"], ["codex_turn.jsonl"])

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "research lithium", "claude-sub")
        await _settle(m, s.id)
        s = sessions.load(s.id)
        assert s.runs == [RUN]
        assert s.segments[0].searches == 1
        assert not (config.DATA / "locks" / f"{RUN}.lock").exists()  # released at turn end

    asyncio.run(go())


def test_stale_session_starts_fresh(root: Path) -> None:
    m, claude, _ = _manager(
        ["claude_subagent.jsonl", "claude_subagent.jsonl"], ["codex_turn.jsonl"]
    )

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "first", "claude-sub")
        await _settle(m, s.id)
        import time

        sessions.mark_stale_after(time.time() + 1)
        await m.send(s.id, "after a skill edit", "claude-sub")
        await _settle(m, s.id)
        prompt, native = claude.prompts[-1]
        assert native is None and prompt.startswith("# Continuing a session from another agent")
        assert "the workspace configuration changed" in prompt
        assert not sessions.load(s.id).stale

    asyncio.run(go())
