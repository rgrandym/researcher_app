"""Independent critique and the author's explicit apply action."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from conftest import RUN, FakeProvider
from test_turns import _settle

from backend import main, sessions, workspace
from backend.providers.base import Event, TurnResult
from backend.turns import TurnManager


def test_apply_critique_starts_scoped_repair(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = root / "outputs" / RUN
    (run / "report.md").write_text("# Report\nText.\n")
    (run / "critique.md").write_text("[MATERIAL] Tighten claim.\n")
    (run / "critique-questions.json").write_text(json.dumps({"questions": [{
        "id": "q1", "finding": "Tighten claim", "question": "Which period did you mean?",
        "options": [{"label": "2025", "description": "Last year"}, {"label": "2026", "description": "This year"}],
    }]}))

    class Sender:
        locks: dict[str, str] = {}

        async def send(self, session: str, prompt: str) -> None:
            self.session, self.prompt = session, prompt

    sender = Sender()
    monkeypatch.setattr(main, "manager", sender)
    questions = main.critique_questions(RUN)["questions"]
    assert questions[0]["question"] == "Which period did you mean?"
    with pytest.raises(HTTPException, match="Answer every author question"):
        asyncio.run(main.apply_critique(RUN, main.ApplyCritiqueBody()))
    result = asyncio.run(main.apply_critique(RUN, main.ApplyCritiqueBody(answers={"q1": "2025, based on my experience"}, notes="Keep my conclusion as an opinion.")))
    assert result["session"] == sender.session
    assert sender.prompt.startswith(f"/repair outputs/{RUN}/critique.md")
    assert "Respect final sections" in sender.prompt
    feedback = list(run.glob("repair-feedback-*.json"))
    assert len(feedback) == 1
    recorded = json.loads(feedback[0].read_text())
    assert recorded["answers"]["q1"] == "2025, based on my experience"
    assert recorded["notes"] == "Keep my conclusion as an opinion."
    assert feedback[0].name in sender.prompt

    with pytest.raises(HTTPException, match="Describe which findings"):
        asyncio.run(main.apply_critique(RUN, main.ApplyCritiqueBody(scope="specified", answers={"q1": "2025"})))

    with pytest.raises(HTTPException):
        asyncio.run(main.apply_critique(RUN, main.ApplyCritiqueBody(path="../report.md")))
    (run / ".critique-isolation-failed").write_text("no critic\n")
    with pytest.raises(HTTPException, match="independent review"):
        asyncio.run(main.apply_critique(RUN, main.ApplyCritiqueBody()))


def test_critique_without_subagent_fails_review_gate(root: Path) -> None:
    run = root / "outputs" / RUN
    (run / "report.md").write_text("# Report\nText.\n")
    (run / "critique.md").write_text("Old critique.\n")
    provider = FakeProvider("codex-plan", ["codex_turn.jsonl"])
    manager = TurnManager({"codex-plan": provider})
    session = sessions.create("review")
    session.project = RUN
    session.runs = [RUN]
    sessions.save(session)

    async def run_turn() -> None:
        await manager.send(session.id, f"/critique outputs/{RUN}", "codex-plan")
        await _settle(manager, session.id)

    asyncio.run(run_turn())
    events = sessions.transcript(session.id)
    assert any(e.type == "error" and "independent report-critic" in e.data.get("text", "") for e in events)
    assert (run / ".critique-isolation-failed").is_file()
    assert not next(row for row in workspace.stages(RUN, max_age=0) if row["stage"] == "critique")["ok"]
    assert not any(e.type == "notice" and e.data.get("kind") == "critique_ready" for e in events)


def test_independent_critique_clears_failed_review(root: Path) -> None:
    run = root / "outputs" / RUN
    (run / "report.md").write_text("# Report\nText.\n")
    (run / ".critique-isolation-failed").write_text("earlier failure\n")

    class Critic(FakeProvider):
        async def run_turn(self, prompt, native_session, on_event, cancelled, permission, options):
            await on_event(Event(type="tool_call", data={"id": "critic", "subagent": {"type": "report-critic"}}))
            (run / "critique.md").write_text("No blocking findings.\nVERDICT: ship\n")
            (run / "critique-questions.json").write_text('{"questions": []}\n')
            return TurnResult(native_session="critic-session")

    manager = TurnManager({"codex-plan": Critic("codex-plan", ["codex_turn.jsonl"])})
    session = sessions.create("review")
    session.project = RUN
    session.runs = [RUN]
    sessions.save(session)

    async def run_turn() -> None:
        await manager.send(session.id, f"/critique outputs/{RUN}", "codex-plan")
        await _settle(manager, session.id)

    asyncio.run(run_turn())
    assert not (run / ".critique-isolation-failed").exists()
    assert next(row for row in workspace.stages(RUN, max_age=0) if row["stage"] == "critique")["ok"]
    ready = [e for e in sessions.transcript(session.id) if e.type == "notice" and e.data.get("kind") == "critique_ready"]
    assert len(ready) == 1
    assert ready[0].data["run"] == RUN and ready[0].data["path"] == "critique.md"
