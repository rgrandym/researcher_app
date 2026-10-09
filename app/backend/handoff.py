"""The handoff packet: what a new provider reads to pick up a session another provider
was running.

The packet is built from data, never from a model summary, so it cannot invent
progress: the author's messages verbatim, each run's `run_check.py` output, the last
tool calls as recorded in the transcript, the previous agent's last message, and the
files changed in the interrupted turn, with truncated writes flagged. It points to files
by path and never pastes their contents. Templates live in `app/prompts/`.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from backend import config, workspace
from backend.providers.base import Event
from backend.sessions import Session

MAX_TOOL_ROWS = 15
MAX_LAST_MESSAGE = 2000
STAGE_ORDER = [
    "prompt",
    "brief",
    "voice",
    "coverage",
    "evidence",
    "notes",
    "report",
    "verify",
    "critique",
    "repair",
    "context",
    "piece",
    "review",
]
REASONS = {
    "limit": "its plan or quota ran out",
    "auth": "its sign-in expired",
    "context": "its context window was full",
    "network": "the network failed",
    "error": "it stopped on an error",
    "stopped": "the author stopped it",
    "handover": "the author handed over before its plan ran out",
    "config": "the workspace configuration changed and a fresh session was started",
    "switch": "the author switched provider",
}


def _template(name: str) -> str:
    return (config.PROMPTS / name).read_text()


def _fill(template: str, values: dict[str, str]) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)


def _clock(ts: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts or time.time()))


# ------------------------------------------------------------------ pieces


def requests(events: list[Event], since: float = 0) -> str:
    texts = [str(e.data.get("text", "")) for e in events if e.type == "user" and e.ts >= since]
    if not texts:
        return "(none)"
    return "\n\n".join(f"{i}. {_quote(t)}" for i, t in enumerate(texts, 1))


def _quote(text: str) -> str:
    lines = text.strip().splitlines() or [""]
    return lines[0] + "".join(f"\n   {ln}" for ln in lines[1:])


def tool_rows(events: list[Event]) -> str:
    outcomes = {
        str(e.data.get("id")): ("error" if e.data.get("is_error") else "ok")
        for e in events
        if e.type == "tool_result"
    }
    calls = [e for e in events if e.type == "tool_call"][-MAX_TOOL_ROWS:]
    if not calls:
        return "(no tool calls recorded)"
    rows = []
    for e in calls:
        target = ", ".join(e.data.get("files") or []) or str(e.data.get("summary", ""))
        who = " (subagent)" if e.agent else ""
        rows.append(
            f"- {e.data.get('name')}{who} · {target} · {outcomes.get(str(e.data.get('id')), 'no result')}"
        )
    return "\n".join(rows)


def last_message(events: list[Event]) -> str:
    texts = [e for e in events if e.type == "assistant_text" and e.agent is None]
    if not texts:
        return "(none)"
    text = str(texts[-1].data.get("text", "")).strip()
    if len(text) > MAX_LAST_MESSAGE:
        text = text[:MAX_LAST_MESSAGE] + " […]"
    return "\n".join(f"> {ln}" for ln in text.splitlines())


def runs_block(runs: list[str]) -> str:
    if not runs:
        return "(no run folder yet)"
    blocks = []
    for name in runs:
        try:
            path = workspace.run_dir(name)
        except (ValueError, FileNotFoundError):
            blocks.append(f"### outputs/{name}\n\n(folder not found)")
            continue
        meta = workspace.run_meta(path)
        blocks.append(
            f"### outputs/{name}\n\nLane: {meta.get('kind')} · master: {meta.get('primary') or ', '.join(meta.get('masters') or [])}\n\n"
            f"```text\n{workspace.run_check_text(name)}\n```"
        )
    return "\n\n".join(blocks)


def jsonl_problem(path: Path) -> str | None:
    """The first line of a JSON-lines file that does not parse, if any."""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for n, line in enumerate(lines, 1):
        if line.strip():
            try:
                json.loads(line)
            except ValueError:
                return f"line {n} is not valid JSON"
    return None


def md_problem(path: Path) -> str | None:
    """A Markdown file whose last line looks cut off mid-sentence."""
    try:
        lines = [ln.rstrip() for ln in path.read_text(errors="replace").splitlines() if ln.strip()]
    except OSError:
        return None
    if not lines:
        return None
    last = lines[-1].strip()
    if last.startswith(("#", "|", "-", "*", ">", "```", "[", "<!--")) or re.match(r"^\d+\.", last):
        return None
    if re.search(r"[.!?:;)\]`\"'”’*_]$", last):
        return None
    return "ends mid-sentence"


def changed_files(runs: list[str], extra: list[str], since: float) -> list[dict[str, Any]]:
    """Files in the session's runs modified since `since`, plus files the turn named."""
    found: dict[str, Path] = {}
    for name in runs:
        try:
            base = workspace.run_dir(name)
        except (ValueError, FileNotFoundError):
            continue
        for p in base.rglob("*"):
            if (
                p.is_file()
                and "export" not in p.parts
                and ".history" not in p.parts
                and not p.name.startswith(".")
            ):
                try:
                    if p.stat().st_mtime >= since:
                        found[str(p)] = p
                except OSError:
                    continue
    for f in extra:
        p = Path(f) if Path(f).is_absolute() else config.ROOT / f
        if p.is_file() and p.stat().st_mtime >= since:
            found[str(p)] = p
    out = []
    for key in sorted(found):
        p = found[key]
        problem = (
            jsonl_problem(p)
            if p.suffix == ".jsonl"
            else md_problem(p)
            if p.suffix == ".md"
            else None
        )
        try:
            rel = str(p.resolve().relative_to(config.ROOT.resolve()))
        except ValueError:
            rel = str(p)
        st = p.stat()
        out.append({"path": rel, "size": st.st_size, "mtime": st.st_mtime, "flag": problem})
    return out


def files_block(files: list[dict[str, Any]]) -> str:
    if not files:
        return "(no files changed)"
    rows = []
    for f in sorted(files, key=lambda f: (f["flag"] is None, f["path"])):
        flag = f" · **FLAGGED: {f['flag']}**" if f["flag"] else ""
        rows.append(f"- {f['path']} · {f['size']} bytes · {_clock(f['mtime'])}{flag}")
    return "\n".join(rows)


def resume_at(runs: list[str], events: list[Event]) -> str:
    """The first stage run_check reports missing in the newest run, with the last call."""
    stage = None
    for name in sorted(runs, reverse=True):
        try:
            rows = workspace.stages(name, max_age=0)
        except (ValueError, FileNotFoundError):
            continue
        missing = [r["stage"] for r in rows if not r["ok"] and r["stage"] != "notes"]
        if missing:
            missing.sort(key=lambda s: STAGE_ORDER.index(s) if s in STAGE_ORDER else 99)
            stage = f"the {missing[0]} stage of outputs/{name}"
        elif rows:
            stage = (
                f"outputs/{name}, whose stages are all complete; finish what the author last asked"
            )
        break
    calls = [e for e in events if e.type == "tool_call"]
    last = (
        f" (the last call was {calls[-1].data.get('name')} on {', '.join(calls[-1].data.get('files') or []) or calls[-1].data.get('summary')})"
        if calls
        else ""
    )
    return (stage or "the author's last request") + last


def _last_turn_start(events: list[Event]) -> float:
    users = [e.ts for e in events if e.type == "user"]
    return users[-1] if users else 0.0


# ------------------------------------------------------------------ packets


def build(
    session: Session,
    events: list[Event],
    from_provider: str,
    from_model: str,
    reason: str,
    ended: float | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """The full packet for a provider that has not seen this session (or only a part of
    it it no longer remembers). Returns (packet, changed files)."""
    since = _last_turn_start(events)
    touched = [
        f
        for e in events
        if e.type == "tool_call" and e.ts >= since
        for f in e.data.get("files") or []
    ]
    files = changed_files(session.runs, touched, since)
    packet = _fill(
        _template("handoff.md"),
        {
            "provider": from_provider,
            "model": from_model or "default model",
            "time": _clock(ended),
            "reason": REASONS.get(reason, reason),
            "requests": requests(events),
            "runs": runs_block(session.runs),
            "tool_calls": tool_rows(events),
            "last_message": last_message(events),
            "files": files_block(files),
            "resume_at": resume_at(session.runs, events),
        },
    )
    return packet, files


def build_return(
    session: Session, events: list[Event], left_at: float, other_provider: str
) -> tuple[str, list[dict[str, Any]]]:
    """The shorter packet for a provider resuming its own native session after another
    provider worked on the session meanwhile."""
    files = changed_files(session.runs, [], left_at)
    packet = _fill(
        _template("handoff-return.md"),
        {
            "time": _clock(left_at),
            "provider": other_provider,
            "requests": requests(events, since=left_at),
            "runs": runs_block(session.runs),
            "files": files_block(files),
            "resume_at": resume_at(session.runs, [e for e in events if e.ts >= left_at]),
        },
    )
    return packet, files


def with_pending(packet: str, pending: str | None) -> str:
    if not pending:
        return packet
    return f"{packet}\n\n---\n\nThe author's new message, to act on after you have resumed:\n\n{pending}"
