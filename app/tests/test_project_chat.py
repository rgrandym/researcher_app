"""Chatting from inside a project: one conversation per project, reused until the author
starts another, and every new agent conversation in it told which run it is about."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from conftest import RUN, FakeProvider
from test_turns import _settle

from backend import config, main, sessions
from backend.turns import TurnManager


def test_project_conversation_is_reused_until_a_new_one_is_asked_for(root: Path) -> None:
    first = main.project_chat(RUN, main.ProjectChat())
    assert first["project"] == RUN and first["runs"] == [RUN] and first["title"] == RUN
    again = main.project_chat(RUN, main.ProjectChat())
    assert again["id"] == first["id"]
    fresh = main.project_chat(RUN, main.ProjectChat(new=True))
    assert fresh["id"] != first["id"]
    assert main.project_chat(RUN, main.ProjectChat())["id"] == fresh["id"]


def test_new_agent_conversations_are_told_the_project(root: Path) -> None:
    claude = FakeProvider("claude-sub", ["claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})
    sid = main.project_chat(RUN, main.ProjectChat())["id"]

    async def go() -> None:
        await m.send(sid, "which figure is weakest?", "claude-sub")
        await _settle(m, sid)
        await m.send(sid, "and why?", "claude-sub")
        await _settle(m, sid)
        await m.send(sid, "/verify E42", "claude-sub")
        await _settle(m, sid)
        told = f"inside the project outputs/{RUN}"
        (p1, n1), (p2, n2), (p3, n3) = claude.prompts
        assert told in p1 and n1 is None
        assert p2 == "and why?" and n2 is not None  # same conversation, already told
        assert p3.startswith("/verify E42") and told in p3 and n3 is None
        assert "This app session has worked on" not in p3

    asyncio.run(go())
    assert sessions.load(sid).project == RUN


def test_removing_a_project_takes_its_conversations_and_caches(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    chat = main.project_chat(RUN, main.ProjectChat())["id"]
    only = sessions.create("about this run")
    only.runs = [RUN]
    sessions.save(only)
    both = sessions.create("two runs")
    both.runs = [RUN, "2026-01-16-other"]
    sessions.save(both)
    cache = config.DATA / "render" / RUN / "meridian-cited"
    cache.mkdir(parents=True)
    (cache / "report.html").write_text("<p>cached</p>")
    lock = config.data_dir("locks") / f"{RUN}.lock"
    lock.write_text("{}")

    res = main.delete_run(RUN)
    assert set(res["removed_sessions"]) == {chat, only.id}
    ids = {s["id"] for s in sessions.list_all()}
    assert chat not in ids and only.id not in ids and both.id in ids
    assert sessions.load(both.id).runs == ["2026-01-16-other"]
    assert not (config.DATA / "render" / RUN).exists() and not lock.exists()
    assert not (root / "outputs" / RUN).exists()
    assert (tmp_path / "home" / ".Trash" / RUN / "prompt.md").is_file()
