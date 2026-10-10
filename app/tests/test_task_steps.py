"""The activity panel's task stepper: each new task starts at step 1, judged from evidence
written after it began; a finished task shows the steps it never took as skipped."""

import time

from backend import activity, workspace
from backend.providers.base import Event


class S:
    project = "2026-10-09-run"
    runs = ["2026-10-09-run"]


def _run(tmp_path, monkeypatch):
    run = tmp_path / "2026-10-09-run"
    (run / "rounds" / "r1").mkdir(parents=True)
    (run / "report.md").write_text("# old\n")
    (run / "verification.md").write_text("old\n")
    monkeypatch.setattr(workspace, "run_dir", lambda name: run)
    return run


def test_new_task_starts_at_step_one_despite_old_files(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch)
    time.sleep(0.01)
    events = [Event(type="user", data={"text": "/verify the new claims"})]
    t = activity.task(S(), events, running=True)
    assert t["label"] == "Verification"
    assert [s["state"] for s in t["steps"]] == ["current", "todo", "todo", "todo"]


def test_progress_follows_files_written_after_the_task_began(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    events = [Event(type="user", data={"text": "/user-edits absorb"}, ts=time.time() - 5)]
    events.append(Event(type="tool_call", data={"name": "Bash"}))
    (run / "report.md").write_text("# new\n")
    t = activity.task(S(), events, running=True)
    assert [s["state"] for s in t["steps"]][:2] == ["done", "done"]


def test_finished_task_shows_untaken_steps_as_skipped(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    events = [Event(type="user", data={"text": "/expand cover disease"}, ts=time.time() - 5)]
    (run / "rounds" / "r1" / "diff.md").write_text("changed\n")
    (run / "rounds" / "r1" / "reconcile.md").write_text("classified\n")
    events.append(Event(type="done", data={}))
    t = activity.task(S(), events, running=False)
    assert [s["state"] for s in t["steps"]] == ["done", "done", "skipped", "done"]


def test_plain_question_is_a_chat_task(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch)
    events = [Event(type="user", data={"text": "what does the report say about cost?"})]
    t = activity.task(S(), events, running=True)
    assert t["command"] == "" and t["steps"][0]["state"] == "current"


def test_retry_keeps_the_command_it_continues(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch)
    events = [
        Event(type="user", data={"text": "Carry on with the task from before."}),
        Event(type="notice", data={"kind": "route", "text": "/expand (continued): frontier tier, opus at high effort"}),
    ]
    t = activity.task(S(), events, running=True)
    assert t["label"] == "Expansion"
