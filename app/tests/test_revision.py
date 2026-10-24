"""Revision runs: the change plan the app shows, the author's decisions, and the apply action."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import RUN
from fastapi import HTTPException

from backend import main, revision


def _subject(root: Path) -> Path:
    run = root / "outputs" / RUN
    (run / "external_data").mkdir(exist_ok=True)
    (run / "external_data" / "plan.md").write_text(
        "# Plan\n\nThe market is worth USD 9 billion.\n\nWe sell peptides.\n"
    )
    scripts = root / ".claude/scripts"
    for args in (["add", str(run), "plan.md"], ["extract", str(run)]):
        subprocess.run([sys.executable, str(scripts / "subject.py"), *args], check=True,
                       capture_output=True)
    (run / "subjects" / "plan" / "changes.json").write_text(json.dumps({"changes": [
        {"id": "C01", "op": "replace", "target": "B002", "before": "USD 9 billion",
         "after": "USD 9.7 billion", "kind": "update", "basis": "author", "rationale": "Newer figure."},
        {"id": "C02", "op": "insert_after", "target": "B003", "after": "We start with Activin A.",
         "kind": "add", "basis": "author", "rationale": "Author's instruction.", "pairs_with": ["C01"]},
    ], "open": [{"where": "Costs", "what": "GMP quote", "why": "no public price"}]}))
    revision._modules.clear()          # the fixture workspace has its own copy of the scripts
    return run


class Sender:
    locks: dict[str, str] = {}

    async def send(self, session: str, prompt: str) -> None:
        self.session, self.prompt = session, prompt


def test_plan_decisions_and_apply(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _subject(root)
    listed = main.run_subjects(RUN)["subjects"]
    assert [(s["slug"], s["role"], s["counts"]) for s in listed] == [("plan", "subject", {"proposed": 2})]

    plan = main.run_changes(RUN, "plan")
    assert [c["status"] for c in plan["changes"]] == ["proposed", "proposed"]
    assert plan["changes"][0]["where"] == "Plan"
    assert plan["open"][0]["what"] == "GMP quote"

    sender = Sender()
    monkeypatch.setattr(main, "manager", sender)
    with pytest.raises(HTTPException, match="Accept at least one"):
        asyncio.run(main.apply_changes(RUN, main.ApplyChangesBody(slug="plan")))

    body = main.DecisionsBody(decisions={
        "C01": {"status": "accepted", "after": "USD 9.7 billion in 2026"},
        "C02": {"status": "rejected"},
    })
    plan = main.save_decisions(RUN, "plan", body)
    assert [c["status"] for c in plan["changes"]] == ["accepted", "rejected"]
    stored = json.loads((run / "subjects/plan/decisions.json").read_text())["decisions"]
    assert stored["C01"]["after"] == "USD 9.7 billion in 2026"
    assert stored["C01"]["by"] == "author"

    # The agent edits an accepted change: it goes back to the author.
    data = json.loads((run / "subjects/plan/changes.json").read_text())
    data["changes"][0]["after"] = "USD 9.8 billion"
    (run / "subjects/plan/changes.json").write_text(json.dumps(data))
    assert main.run_changes(RUN, "plan")["changes"][0]["status"] == "stale"
    main.save_decisions(RUN, "plan", main.DecisionsBody(decisions={"C01": {"status": "accepted"}}))

    result = asyncio.run(main.apply_changes(RUN, main.ApplyChangesBody(slug="plan", mode="clean", notes="Keep it short.")))
    assert result["session"] == sender.session
    assert sender.prompt.startswith(f"/revise outputs/{RUN} plan")
    request = next((run / "deliverable/plan").glob("request-*.json"))
    assert request.name in sender.prompt
    assert json.loads(request.read_text())["accepted"] == ["C01"]

    with pytest.raises(HTTPException):
        main.save_decisions(RUN, "plan", main.DecisionsBody(decisions={"C99": {"status": "accepted"}}))
    with pytest.raises(HTTPException):
        main.save_decisions(RUN, "plan", main.DecisionsBody(decisions={"C01": {"status": "maybe"}}))
    with pytest.raises(HTTPException):
        main.run_changes(RUN, "nope")


def test_pdf_subject_is_rebuilt(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _subject(root)
    source = run / "subjects/plan/source.json"
    meta = json.loads(source.read_text())
    meta.update({"editable": False, "format": "pdf"})
    source.write_text(json.dumps(meta))
    main.save_decisions(RUN, "plan", main.DecisionsBody(decisions={"C01": {"status": "accepted"}}))
    sender = Sender()
    monkeypatch.setattr(main, "manager", sender)
    asyncio.run(main.apply_changes(RUN, main.ApplyChangesBody(slug="plan")))
    assert sender.prompt.startswith(f"/rebuild outputs/{RUN} plan")
    request = next((run / "deliverable/plan").glob("request-*.json"))
    assert json.loads(request.read_text())["mode"] == "clean"


def test_apply_end_to_end_with_scripts(root: Path) -> None:
    """The workspace scripts apply an accepted Markdown change and the check passes."""
    run = _subject(root)
    main.save_decisions(RUN, "plan", main.DecisionsBody(decisions={
        "C01": {"status": "accepted"}, "C02": {"status": "accepted"}}))
    scripts = root / ".claude/scripts"
    subprocess.run([sys.executable, str(scripts / "apply_changes.py"), str(run), "plan"],
                   check=True, capture_output=True)
    out = (run / "deliverable/plan/v1/plan.md").read_text()
    assert "USD 9.7 billion" in out and "We start with Activin A." in out
    check = subprocess.run([sys.executable, str(scripts / "changes.py"), "check", str(run), "plan"],
                           capture_output=True, text=True)
    assert check.returncode == 0, check.stdout
    assert main.run_subjects(RUN)["subjects"][0]["deliverable"]["ok"] is True
