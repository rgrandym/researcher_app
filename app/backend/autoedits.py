"""Absorb the author's hand edits without a typed command.

Every few seconds the watcher looks at each run's master. When the master is newer than
its `.voice-mirror-<name>.md` (which the gate rewrites on every agent write, see
`saved_check.py`), the author has saved something no agent has absorbed. Once the file has
been quiet for `quiet_seconds`, and no turn is working on the run, the watcher sends
`/user-edits` to the project's conversation, as if the author had typed it.

It never fires twice for the same save, never on a write made while an agent held the run
(an agent write the gate did not mark), and never on an edit already pending when the app
started: only saves made while the app is open count.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from backend import config, edit_state, sessions, workspace

POLL_S = 5
# An agent write lands while the run is locked; one this close after the lock ends is
# still the agent's.
AGENT_GRACE_S = 10


class Watcher:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.seen: dict[str, float] = {}  # master path -> the mtime already handled
        self.busy_until: dict[str, float] = {}  # run -> last time a turn held it
        self.started = time.time()

    def settings(self) -> dict[str, Any]:
        conf = config.load_settings().get("auto_user_edits") or {}
        return {"enabled": conf.get("enabled", True), "quiet": float(conf.get("quiet_seconds", 60))}

    def pending(self) -> list[tuple[str, Path, float]]:
        """(run, master, mtime) for every master with an unabsorbed author save."""
        out = []
        base = workspace.outputs()
        if not base.is_dir():
            return out
        for path in base.iterdir():
            if not path.is_dir() or not workspace.RUN_NAME.match(path.name):
                continue
            name = workspace.run_meta(path).get("primary")
            if not name:
                continue
            master = path / name
            mirror = path / f".voice-mirror-{master.stem}.md"
            if not master.is_file() or not (mirror.is_file() or edit_state.pending(master)):
                continue  # no agent baseline or recorded app save to compare against
            mtime = master.stat().st_mtime
            if edit_state.pending(master) or mtime > mirror.stat().st_mtime:
                out.append((path.name, master, mtime))
        return out

    def run_busy(self, run: str) -> bool:
        owner = self.manager.locks.get(run)
        busy = bool(owner and self.manager.is_running(owner))
        session = sessions.for_project(run)
        busy = busy or bool(session and self.manager.is_running(session.id))
        if busy:
            self.busy_until[run] = time.time()
        return busy

    async def tick(self) -> None:
        conf = self.settings()
        now = time.time()
        for run, master, mtime in self.pending():
            key = str(master)
            if self.seen.get(key) == mtime:
                continue
            if mtime < self.started:
                self.seen[key] = mtime  # pending before the app opened: leave it to the author
                continue
            if self.run_busy(run):
                continue
            if mtime <= self.busy_until.get(run, 0) + AGENT_GRACE_S:
                self.seen[key] = mtime  # written while an agent held the run
                continue
            if not conf["enabled"] or now - mtime < conf["quiet"]:
                continue
            self.seen[key] = mtime
            if self.claim(master, mtime):
                await self.absorb(run, master, mtime)

    @staticmethod
    def claim(master: Path, mtime: float) -> bool:
        """Take this save atomically: a VS Code session running the research-live mod may be
        watching too (.claude/scripts/live_status.py claim, same marker name)."""
        marker = master.parent / f".autoedit-{master.stem}-{int(mtime)}"
        try:
            os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            return False
        for old in master.parent.glob(f".autoedit-{master.stem}-*"):
            if old != marker:
                old.unlink(missing_ok=True)
        return True

    async def absorb(self, run: str, master: Path, mtime: float) -> None:
        session = sessions.for_project(run)
        if session is None:
            session = sessions.create(run)
            session.project = run
            session.runs = [run]
            sessions.save(session)
        when = datetime.fromtimestamp(mtime).strftime("%H:%M")
        text = (
            f"/user-edits {master.name} was saved by hand at {when} and no agent has absorbed "
            "the edit yet. Absorb it. (Started automatically by the app.)"
        )
        try:
            await self.manager.send(session.id, text)
        except Exception:  # noqa: BLE001  a refused send waits for the author's next save
            pass

    async def resume_due(self) -> None:
        """Carry on the sessions scheduled to continue on the same model once its window
        reset ("Continue later" on the limit card)."""
        now = time.time()
        if now - getattr(self, "_resume_checked", 0) < 20:
            return
        self._resume_checked = now
        for row in sessions.list_all():
            try:
                session = sessions.load(row["id"])
            except (FileNotFoundError, ValueError):
                continue
            if not session.resume_at or session.resume_at > now or self.manager.is_running(session.id):
                continue
            conn = session.resume_connection
            session.resume_at, session.resume_connection = None, None
            sessions.save(session)
            try:
                await self.manager.retry(session.id, conn)
            except Exception:  # noqa: BLE001  shown in the session; the author can Retry
                pass

    async def loop(self) -> None:
        while True:
            try:
                await self.tick()
                await self.resume_due()
            except Exception:  # noqa: BLE001  the watcher must outlive one bad run folder
                pass
            await asyncio.sleep(POLL_S)
