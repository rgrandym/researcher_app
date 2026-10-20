"""The auto /user-edits watcher: fires once per quiet author save, never on agent writes."""

import asyncio
import os
import time

from backend import autoedits, edit_state, workspace


class FakeManager:
    def __init__(self):
        self.locks = {}
        self.running = set()
        self.sent = []

    def is_running(self, sid):
        return sid in self.running

    async def send(self, sid, text):
        self.sent.append(text)


def _run(tmp_path, monkeypatch, age):
    run = tmp_path / "2026-10-09-test-run"
    run.mkdir()
    (run / "report.md").write_text("# T\n")
    (run / ".voice-mirror-report.md").write_text("# T\n")
    now = time.time()
    os.utime(run / ".voice-mirror-report.md", (now - 600, now - 600))
    os.utime(run / "report.md", (now - age, now - age))
    monkeypatch.setattr(workspace, "outputs", lambda: tmp_path)
    monkeypatch.setattr(workspace, "run_meta", lambda p: {"primary": "report.md"})
    monkeypatch.setattr(autoedits.sessions, "for_project", lambda r: type("S", (), {"id": "s1"})())
    return run


def _watcher(manager, quiet=60):
    w = autoedits.Watcher(manager)
    w.started = 0
    w.settings = lambda: {"enabled": True, "quiet": quiet}
    return w


def test_fires_once_after_quiet(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, age=120)
    m = FakeManager()
    w = _watcher(m)
    asyncio.run(w.tick())
    asyncio.run(w.tick())
    assert len(m.sent) == 1 and m.sent[0].startswith("/user-edits report.md")


def test_waits_while_author_still_saving(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, age=10)
    m = FakeManager()
    asyncio.run(_watcher(m).tick())
    assert m.sent == []


def test_ignores_write_made_while_agent_held_run(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, age=120)
    m = FakeManager()
    w = _watcher(m)
    w.busy_until["2026-10-09-test-run"] = time.time() - 115
    asyncio.run(w.tick())
    assert m.sent == []


def test_ignores_edit_pending_before_start(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, age=120)
    m = FakeManager()
    w = _watcher(m)
    w.started = time.time()
    asyncio.run(w.tick())
    assert m.sent == []


def test_waits_while_run_busy(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, age=120)
    m = FakeManager()
    m.running.add("s1")
    asyncio.run(_watcher(m).tick())
    assert m.sent == []


def test_second_watcher_skips_a_claimed_save(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, age=120)
    first, second = FakeManager(), FakeManager()
    asyncio.run(_watcher(first).tick())
    asyncio.run(_watcher(second).tick())
    assert len(first.sent) == 1 and second.sent == []


def test_author_save_survives_agent_mirror_refresh(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, age=120)
    doc = run / "report.md"
    mirror = run / ".voice-mirror-report.md"
    mirror.write_text("# Original\n")
    edit_state.record(doc, "# Original\n\n## Introduction\nAuthor's text.\n")
    doc.write_text(edit_state.saved_path(doc).read_text())
    mirror.write_text(doc.read_text())
    os.utime(doc, (time.time() - 120, time.time() - 120))
    assert edit_state.pending(doc)
    manager = FakeManager()
    asyncio.run(_watcher(manager).tick())
    assert len(manager.sent) == 1
