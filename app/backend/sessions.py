"""The app's sessions: the author's conversation, independent of any one provider.

    app/data/sessions/<id>/session.json     title, runs touched, segments
    app/data/sessions/<id>/transcript.jsonl every normalised event, append-only
    app/data/sessions/<id>/handoffs/hN.md   each handoff packet sent

A segment is one stretch on one provider: `{provider, model, native_session_id,
started, ended, end_reason}`. A provider switch closes the current segment and opens
another; the transcript runs on across both.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend import config
from backend.providers.base import Event

_transcript_cache: OrderedDict[str, tuple[tuple[int, int, int], list[Event]]] = OrderedDict()
_transcript_lock = threading.RLock()
_TRANSCRIPT_CACHE_LIMIT = 64


def _stamp(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns


def _cache_put(key: str, stamp: tuple[int, int, int], events: list[Event]) -> None:
    _transcript_cache[key] = (stamp, events)
    _transcript_cache.move_to_end(key)
    if len(_transcript_cache) > _TRANSCRIPT_CACHE_LIMIT:
        _transcript_cache.popitem(last=False)


class Segment(BaseModel):
    provider: str
    model: str = ""
    effort: str = ""
    native_session_id: str | None = None
    # Fresh commands can create several native conversations inside one app segment.
    native_sessions: list[str] = Field(default_factory=list)
    # The command that started the native session; replies without one keep its route.
    route_key: str = ""
    # The last turn was work (a command, /continue, /do) that handed back to the author: a
    # reply without a command answers the agent and carries that work on with every tool.
    awaiting: bool = False
    # A read-only turn that ended asking the author whether to go ahead: the request it held.
    # A yes in reply (or Go ahead with tools) carries it out with every tool.
    offered: str = ""
    started: float = Field(default_factory=time.time)
    ended: float | None = None
    end_reason: str | None = None
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cached_in: int = 0
    cache_written: int = 0
    searches: int = 0
    fetches: int = 0


class Session(BaseModel):
    id: str
    title: str = "New session"
    created: float = Field(default_factory=time.time)
    updated: float = Field(default_factory=time.time)
    runs: list[str] = Field(default_factory=list)
    # The run this session was opened from (the project's Chat tab); every new agent
    # conversation in it is told so, and its commands act on that run.
    project: str = ""
    # A research pipeline the app is running stage by stage: {"run": ..., "stage": ...}.
    pipeline: dict[str, str] | None = None
    segments: list[Segment] = Field(default_factory=list)
    handoffs: int = 0
    # Set when a workspace file was saved after the current segment started.
    stale: bool = False
    # Imported Claude Code session from VS Code (read-only until continued).
    imported_from: str | None = None
    # "Continue with the same model later": when its window resets, the app carries the task
    # on by itself on this connection (backend/autoedits.py runs it).
    resume_at: float | None = None
    resume_connection: str | None = None

    def current(self) -> Segment | None:
        if self.segments and self.segments[-1].ended is None:
            return self.segments[-1]
        return None

    def last_for(self, provider: str) -> Segment | None:
        for seg in reversed(self.segments):
            if seg.provider == provider:
                return seg
        return None


def _dir(session_id: str) -> Path:
    if not re.match(r"^[A-Za-z0-9_-]{6,64}$", session_id):
        raise ValueError("bad session id")
    return config.data_dir("sessions") / session_id


def create(title: str = "New session") -> Session:
    session = Session(id=uuid.uuid4().hex[:12], title=title)
    _dir(session.id).mkdir(parents=True, exist_ok=True)
    save(session)
    return session


def save(session: Session) -> None:
    session.updated = time.time()
    path = _dir(session.id)
    path.mkdir(parents=True, exist_ok=True)
    tmp = path / f"session.{uuid.uuid4().hex}.tmp"
    try:
        tmp.write_text(session.model_dump_json(indent=2))
        tmp.replace(path / "session.json")
    finally:
        tmp.unlink(missing_ok=True)


def load(session_id: str) -> Session:
    path = _dir(session_id) / "session.json"
    if not path.is_file():
        raise FileNotFoundError(session_id)
    return Session.model_validate_json(path.read_text())


def for_project(run: str) -> Session | None:
    """The project's most recently used conversation, if it has one."""
    found: list[Session] = []
    for path in config.data_dir("sessions").glob("*/session.json"):
        try:
            s = Session.model_validate_json(path.read_text())
        except ValueError:
            continue
        if s.project == run:
            found.append(s)
    return max(found, key=lambda s: s.updated) if found else None


def list_all() -> list[dict[str, Any]]:
    out = []
    for path in config.data_dir("sessions").glob("*/session.json"):
        try:
            s = Session.model_validate_json(path.read_text())
        except ValueError:
            continue
        out.append(
            {
                "id": s.id,
                "title": s.title,
                "created": s.created,
                "updated": s.updated,
                "providers": [seg.provider for seg in s.segments],
                "runs": s.runs,
                "stale": s.stale,
            }
        )
    return sorted(out, key=lambda s: s["updated"], reverse=True)


def delete(session_id: str) -> None:
    import shutil

    folder = _dir(session_id)
    with _transcript_lock:
        _transcript_cache.pop(str(folder / "transcript.jsonl"), None)
    shutil.rmtree(folder, ignore_errors=True)


def append(session_id: str, event: Event) -> None:
    path = _dir(session_id) / "transcript.jsonl"
    key = str(path)
    with _transcript_lock:
        previous = _stamp(path) if path.exists() else None
        with path.open("a") as fh:
            fh.write(event.model_dump_json() + "\n")
        cached = _transcript_cache.get(key)
        if cached and cached[0] == previous:
            _cache_put(key, _stamp(path), [*cached[1], event])
        else:
            _transcript_cache.pop(key, None)


def transcript(session_id: str) -> list[Event]:
    path = _dir(session_id) / "transcript.jsonl"
    with _transcript_lock:
        if not path.is_file():
            return []
        key = str(path)
        stamp = _stamp(path)
        cached = _transcript_cache.get(key)
        if cached and cached[0] == stamp:
            _transcript_cache.move_to_end(key)
            return list(cached[1])
        out = []
        for line in path.read_text().splitlines():
            try:
                out.append(Event.model_validate_json(line))
            except ValueError:
                continue  # a torn last line after a crash
        _cache_put(key, stamp, out)
        return list(out)


def transcript_revision(session_id: str) -> tuple[int, int, int] | None:
    path = _dir(session_id) / "transcript.jsonl"
    return _stamp(path) if path.is_file() else None


def write_handoff(session: Session, packet: str) -> str:
    session.handoffs += 1
    folder = _dir(session.id) / "handoffs"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"h{session.handoffs}.md"
    (folder / name).write_text(packet)
    return name


def title_from(text: str) -> str:
    """A title from the author's first message, by code: the first line, trimmed."""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "New session")
    return line if len(line) <= 70 else line[:69] + "…"


def mark_stale_after(when: float) -> list[str]:
    """Mark every session whose open segment started before `when` as running an old
    version of the workspace configuration."""
    marked = []
    for path in config.data_dir("sessions").glob("*/session.json"):
        try:
            s = Session.model_validate_json(path.read_text())
        except ValueError:
            continue
        seg = s.current()
        if seg and seg.started < when and not s.stale:
            s.stale = True
            save(s)
            marked.append(s.id)
    return marked


def payload(session: Session) -> dict[str, Any]:
    return {
        **json.loads(session.model_dump_json()),
        "events": [e.model_dump() for e in transcript(session.id)],
    }
