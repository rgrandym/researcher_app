"""The staged pipeline: each stage of /research-pipeline in its own conversation, the app
starting the next when the one before has left its files, and waiting for the author
whenever a stage ends unfinished."""

from __future__ import annotations

import asyncio
from pathlib import Path

from conftest import RUN, FakeProvider
from test_turns import _settle

from backend import config, main, sessions
from backend.turns import TurnManager


def _notices(sid: str) -> list[str]:
    return [e.data["text"] for e in sessions.transcript(sid) if e.data.get("kind") == "pipeline"]


def test_stages_chain_and_wait_for_the_author(root: Path) -> None:
    claude = FakeProvider("claude-sub", ["claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})
    sid = main.project_chat(RUN, main.ProjectChat())["id"]

    async def go() -> None:
        # Gather is already complete on disk, so the app goes straight on to draft.
        await m.send(sid, "/research-pipeline lithium prices in 2026", "claude-sub")
        await _settle(m, sid)
        first, second = claude.prompts[0][0], claude.prompts[1]
        assert "Staged run" in first
        assert second[0].startswith(f"/research-pipeline stage=draft run=outputs/{RUN}")
        assert second[1] is None  # a fresh conversation
        assert sessions.load(sid).pipeline == {"run": RUN, "stage": "draft"}
        assert _notices(sid) == [
            "The gather stage is complete. Starting draft in a fresh conversation.",
            "Waiting on you: the draft stage is not complete yet (missing: draft). "
            "Reply to continue it.",
        ]

        # The author replies; the draft lands; the app goes on to review.
        (root / "outputs" / RUN / "draft.md").write_text("# Draft\n\nText [E1].\n")
        await m.send(sid, "go on", "claude-sub")
        await _settle(m, sid)
        assert claude.prompts[2][0] == "go on" and claude.prompts[2][1] is not None
        assert claude.prompts[3][0].startswith("/research-pipeline stage=review")
        assert sessions.load(sid).pipeline == {"run": RUN, "stage": "review"}
        assert all(o.model == "opus" for o in claude.options)

    asyncio.run(go())


def test_with_staging_off_the_pipeline_runs_in_one_conversation(root: Path) -> None:
    claude = FakeProvider("claude-sub", ["claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})
    config.save_settings({"staged_pipeline": False})
    sid = main.project_chat(RUN, main.ProjectChat())["id"]

    async def go() -> None:
        await m.send(sid, "/research-pipeline lithium prices in 2026", "claude-sub")
        await _settle(m, sid)
        assert len(claude.prompts) == 1 and "Staged run" not in claude.prompts[0][0]
        assert sessions.load(sid).pipeline is None

    asyncio.run(go())
