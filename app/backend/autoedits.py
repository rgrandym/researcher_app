"""The author's hand edits: what is pending, kept as written, or absorbed by an agent.

A precise edit (a corrected figure, a reworded sentence) needs no agent: **Keep as
written** (`keep`) closes it with the same mechanical steps a /user-edits round ends with,
and no model call. Notes for the agent, stubs and inserted fragments need /user-edits,
which the Edit tab starts with **Absorb with the agent** (`absorb`). `status` tells the
two apart for the Edit tab, and hints when the added text reads like notes.

Optionally (off by default, `auto_user_edits` in settings), every few seconds the watcher looks at each run's master. When the master is newer than
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
import difflib
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from backend import config, edit_state, sessions, workspace

POLL_S = 5
# Added text that reads as a note to the agent rather than finished prose.
NOTES = re.compile(
    r"\b(TODO|TBD|FIXME|XXX)\b|\?\?|<!--|\[\[(?![FT]\w+\]\])|^\s*[(\[]?(note|add|say|expand|check|cite|explain|"
    r"rewrite|research|source)\b[^.\n]{0,80}(:|$)",
    re.I | re.M,
)
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*(?:\{[^}]*\})?[ \t]*$", re.M)
SCRIPT_TIMEOUT_S = 120


class KeepRefused(ValueError):
    """The edit broke something a script checks: it needs an agent, or the author."""


def _mirror(master: Path) -> Path:
    return master.parent / f".voice-mirror-{master.stem}.md"


def _baseline(master: Path) -> Path | None:
    """The last agent text the author's edit started from."""
    if edit_state.active(master):
        return edit_state.base_path(master)
    mirror = _mirror(master)
    return mirror if mirror.is_file() else None


def _unabsorbed(master: Path) -> bool:
    mirror = _mirror(master)
    return edit_state.pending(master) or (
        mirror.is_file() and master.stat().st_mtime > mirror.stat().st_mtime
    )


def _sections(text: str) -> dict[str, str]:
    """Each section's text by its heading; the text before the first heading under ""."""
    out: dict[str, str] = {}
    marks = list(_HEADING.finditer(text))
    out[""] = text[: marks[0].start()] if marks else text
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        name = m.group(1).strip()
        while name in out:
            name += " "
        out[name] = text[m.end() : end]
    return out


def status(run: str, doc: str) -> dict[str, Any]:
    """What the author has changed by hand since the last agent write."""
    master = workspace.run_file(run, doc)
    base = _baseline(master)
    idle = {
        "pending": False,
        "sections": [],
        "added": 0,
        "removed": 0,
        "notes": False,
        "auto": Watcher.enabled(),
    }
    if base is None or not _unabsorbed(master):
        return idle
    old, new = base.read_text(), master.read_text()
    if old == new:
        return idle
    before, after = _sections(old), _sections(new)
    sections = [h.strip() or "(opening)" for h in after if before.get(h) != after[h]]
    sections += [f"{h.strip()} (removed)" for h in before if h not in after]
    added = removed = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, old.split(), new.split(), autojunk=False
    ).get_opcodes():
        removed += i2 - i1 if op in ("replace", "delete") else 0
        added += j2 - j1 if op in ("replace", "insert") else 0
    inserted = "\n".join(
        line[2:]
        for line in difflib.ndiff(old.splitlines(), new.splitlines())
        if line.startswith("+ ")
    )
    return {
        "pending": True,
        "sections": sections[:20],
        "added": added,
        "removed": removed,
        "notes": bool(NOTES.search(inserted)),
        "auto": Watcher.enabled(),
    }


def _script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [config.python(), str(config.ROOT / ".claude" / "scripts" / args[0]), *args[1:]],
        cwd=config.ROOT,
        capture_output=True,
        text=True,
        timeout=SCRIPT_TIMEOUT_S,
        env=config.child_env(),
    )


def keep(run: str, doc: str) -> dict[str, Any]:
    """Close the author's edit as written: the steps a /user-edits round ends with, by
    script. A check the edit broke (it passed on the text before the edit) refuses."""
    master = workspace.run_file(run, doc)
    if not status(run, doc)["pending"]:
        raise ValueError("There is no unabsorbed edit to keep.")
    if not edit_state.active(master):
        edit_state.capture_existing(master)  # freeze it, as /user-edits does first
    base = edit_state.base_path(master)
    folder = workspace.run_dir(run)
    checks = {
        "citations": (
            ("audit_citations.py", str(folder), master.name),
            ("audit_citations.py", str(folder), base.name),
        ),
        "figures": (("figures.py", "check", str(master)), ("figures.py", "check", str(base))),
        "writing rules": (("voice.py", "lint", str(master)), ("voice.py", "lint", str(base))),
    }
    broken = []
    for name, (now, before) in checks.items():
        done = _script(*now)
        if done.returncode != 0 and _script(*before).returncode == 0:
            tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-8:])
            broken.append(f"{name}:\n{tail}")
    if broken:
        raise KeepRefused(
            "The edit broke a check, so it was not kept as written. Fix it, or absorb it with "
            "the agent.\n\n" + "\n\n".join(broken)
        )
    learned = _script("voice.py", "learn", str(master))
    for step in (("section_guard.py", "snapshot", str(master)), ("voice.py", "mark", str(master))):
        done = _script(*step)
        if done.returncode != 0:
            raise ValueError(
                f"{step[0]} {step[1]} failed: {(done.stdout + done.stderr).strip()[-400:]}"
            )
    edit_state.acknowledge(master)
    _script("voice.py", "profile", "--rebuild")
    return {"ok": True, "learned": learned.stdout.strip().splitlines()[-1:] or [""]}


# An agent write lands while the run is locked; one this close after the lock ends is
# still the agent's.
AGENT_GRACE_S = 10


class Watcher:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.seen: dict[str, float] = {}  # master path -> the mtime already handled
        self.busy_until: dict[str, float] = {}  # run -> last time a turn held it
        self.started = time.time()

    @staticmethod
    def enabled() -> bool:
        return bool((config.load_settings().get("auto_user_edits") or {}).get("enabled", False))

    def settings(self) -> dict[str, Any]:
        conf = config.load_settings().get("auto_user_edits") or {}
        return {
            "enabled": conf.get("enabled", False),
            "quiet": float(conf.get("quiet_seconds", 60)),
        }

    def pending(self) -> list[tuple[str, Path, float]]:
        """(run, master, mtime) for every master with an unabsorbed author save."""
        out: list[tuple[str, Path, float]] = []
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

    async def absorb(self, run: str, master: Path, mtime: float, asked: bool = False) -> str:
        """Send /user-edits to the project's conversation; its session id."""
        session = sessions.for_project(run)
        if session is None:
            session = sessions.create(run)
            session.project = run
            session.runs = [run]
            sessions.save(session)
        when = datetime.fromtimestamp(mtime).strftime("%H:%M")
        text = (
            f"/user-edits {master.name} was saved by hand at {when} and no agent has absorbed "
            "the edit yet. Absorb it. "
            + (
                "(The author asked for this in the Edit tab.)"
                if asked
                else "(Started automatically by the app.)"
            )
        )
        if asked:
            self.seen[str(master)] = mtime
            await self.manager.send(session.id, text)  # the author sees a refusal
            return session.id
        try:
            await self.manager.send(session.id, text)
        except Exception:  # noqa: BLE001  a refused send waits for the author's next save
            pass
        return session.id

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
            if (
                not session.resume_at
                or session.resume_at > now
                or self.manager.is_running(session.id)
            ):
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
