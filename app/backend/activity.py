"""The Activity panel: agents, pipeline progress, web use and cost, built from the
session's event stream and the run's files. No model call feeds it.

Web caps come from `.claude/monitor.json` and the research monitor's per-session raises
in `.claude/.monitor-state/`, read and written through the workspace's own
`monitor.py`, so the app, the Claude Code mod and the Codex hook share one set of caps.
"""

from __future__ import annotations

import importlib.util
import json
import time
from types import ModuleType
from typing import Any

from backend import config, sessions, workspace
from backend.providers.base import Event
from backend.sessions import Segment

WEB_TOOLS = ("WebSearch", "WebFetch")
_monitor: ModuleType | None = None


def monitor() -> ModuleType | None:
    global _monitor
    if _monitor is None:
        path = config.ROOT / ".claude/scripts/monitor.py"
        spec = importlib.util.spec_from_file_location("ws_monitor", path)
        if spec is None or spec.loader is None or not path.exists():
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _monitor = module
    return _monitor


def caps_config() -> dict[str, Any]:
    try:
        return dict(json.loads((config.ROOT / ".claude/monitor.json").read_text()))
    except (OSError, ValueError):
        return {
            "searchCap": 400,
            "fetchCap": 700,
            "warnEvery": 100,
            "raise": {"searches": 100, "fetches": 150},
        }


def save_caps(values: dict[str, Any]) -> dict[str, Any]:
    """The Models settings edit `.claude/monitor.json` and nothing else."""
    current = caps_config()
    for key in ("searchCap", "fetchCap", "warnEvery"):
        if key in values:
            current[key] = max(0, int(values[key]))
    if isinstance(values.get("raise"), dict):
        current["raise"] = {
            k: max(0, int(v)) for k, v in values["raise"].items() if k in ("searches", "fetches")
        }
    (config.ROOT / ".claude/monitor.json").write_text(json.dumps(current, indent=2) + "\n")
    return current


def caps_for(native: str | None) -> tuple[int, int]:
    mon = monitor()
    if mon is not None and native:
        searches, fetches = mon.caps(native)
        return int(searches), int(fetches)
    c = caps_config()
    return int(c.get("searchCap", 400)), int(c.get("fetchCap", 700))


def cap_reached(seg: Segment) -> bool:
    searches, fetches = caps_for(seg.native_session_id)
    return seg.searches >= searches or seg.fetches >= fetches


def raise_cap(native: str) -> tuple[int, int]:
    """The research monitor's `more`, for this session rather than the newest one."""
    mon = monitor()
    if mon is None:
        raise RuntimeError("monitor.py not found")
    state = mon.state(native)
    add = mon.config()["raise"]
    mon.save_state(
        native,
        {
            **state,
            "extraSearches": state["extraSearches"] + add["searches"],
            "extraFetches": state["extraFetches"] + add["fetches"],
        },
    )
    return caps_for(native)


def agents(events: list[Event], running: bool) -> list[dict[str, Any]]:
    main: dict[str, Any] = {
        "id": "main",
        "type": "main",
        "description": "Main thread",
        "status": "running" if running else "idle",
        "started": events[0].ts if events else None,
        "ended": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "web": 0,
        "calls": [],
    }
    subs: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.type == "tool_call" and e.data.get("subagent"):
            info = e.data["subagent"]
            subs[str(e.data.get("id"))] = {
                "id": e.data.get("id"),
                "type": info.get("type"),
                "description": info.get("description"),
                "status": "running",
                "started": e.ts,
                "ended": None,
                "tokens_in": 0,
                "tokens_out": 0,
                "web": 0,
                "calls": [],
            }
    for e in events:
        owner = subs.get(str(e.agent)) if e.agent else main
        if owner is None:
            owner = main
        if e.type == "usage" and e.data.get("tokens_in") is not None:
            owner["tokens_in"] += int(e.data.get("tokens_in") or 0)
            owner["tokens_out"] += int(e.data.get("tokens_out") or 0)
        elif e.type == "tool_call":
            if e.data.get("name") in WEB_TOOLS:
                owner["web"] += 1
            owner["calls"].append(
                {"name": e.data.get("name"), "summary": e.data.get("summary"), "ts": e.ts}
            )
            owner["calls"] = owner["calls"][-40:]
        elif e.type == "tool_result" and e.data.get("subagent_done"):
            sub = subs.get(str(e.data.get("id")))
            if sub:
                sub["status"] = "failed" if e.data.get("is_error") else "done"
                sub["ended"] = e.ts
    for sub in subs.values():
        if sub["status"] == "running" and not running:
            sub["status"] = "stopped"
    return [main, *subs.values()]


def progress(runs: list[str]) -> list[dict[str, Any]]:
    out = []
    for name in runs[-3:]:
        try:
            path = workspace.run_dir(name)
        except (ValueError, FileNotFoundError):
            continue
        out.append(
            {
                "run": name,
                "kind": workspace.run_meta(path).get("kind"),
                "stages": workspace.stages(name),
                "evidence_rows": workspace.count_jsonl(path / "evidence.jsonl"),
                "notes": len(list((path / "notes").glob("*.md")))
                if (path / "notes").is_dir()
                else 0,
            }
        )
    return out


def cost(
    session: sessions.Session, events: list[Event], providers: dict[str, Any]
) -> dict[str, Any]:
    context = next(
        (
            e.data
            for e in reversed(events)
            if e.type == "usage" and e.data.get("context_percent") is not None
        ),
        {},
    )
    segments = []
    for seg in session.segments:
        searches, fetches = caps_for(seg.native_session_id)
        segments.append(
            {
                "provider": seg.provider,
                "label": providers[seg.provider].label
                if seg.provider in providers
                else seg.provider,
                "model": seg.model,
                "cost_usd": round(seg.cost_usd, 4),
                "tokens_in": seg.tokens_in,
                "tokens_out": seg.tokens_out,
                "searches": seg.searches,
                "fetches": seg.fetches,
                "search_cap": searches,
                "fetch_cap": fetches,
                "open": seg.ended is None,
                "native": seg.native_session_id,
            }
        )
    return {
        "total_usd": round(sum(s.cost_usd for s in session.segments), 4),
        "context_percent": context.get("context_percent"),
        "context_tokens": context.get("context_tokens"),
        "segments": segments,
        "notices": [e.data for e in events if e.type == "notice" and e.data.get("kind") == "cap"][
            -3:
        ],
    }


def permissions(events: list[Event]) -> list[dict[str, Any]]:
    """Every permission request and question this session raised, newest first, with the
    answer it got. Denials and refusals the provider reported come in as tool errors."""
    answers = {str(e.data.get("id")): e.data for e in events if e.type == "permission_answer"}
    out = []
    for e in events:
        if e.type != "permission_request":
            continue
        a = answers.get(str(e.data.get("id")), {})
        out.append(
            {
                "ts": e.ts,
                "tool": e.data.get("tool"),
                "kind": e.data.get("kind", "permission"),
                "summary": e.data.get("summary")
                or next((q.get("header") for q in e.data.get("questions") or []), ""),
                "decision": a.get("decision")
                or ("waiting" if running_of(events) else "unanswered"),
                "provider": e.provider,
            }
        )
    blocked = [
        {
            "ts": e.ts,
            "tool": "Bash",
            "kind": "blocked",
            "summary": str(e.data.get("summary", ""))[:160],
            "decision": "blocked",
            "provider": e.provider,
        }
        for e in events
        if e.type == "tool_result"
        and e.data.get("is_error")
        and "launch-codes: blocked" in str(e.data.get("summary", ""))
    ]
    return sorted(out + blocked, key=lambda r: r["ts"], reverse=True)[:40]


def running_of(events: list[Event]) -> bool:
    """Whether the last turn in the transcript has not finished."""
    for e in reversed(events):
        if e.type == "done":
            return False
        if e.type == "user":
            return True
    return False


def build(session_id: str, running: bool, providers: dict[str, Any]) -> dict[str, Any]:
    session = sessions.load(session_id)
    events = sessions.transcript(session_id)
    current = session.current() or (session.segments[-1] if session.segments else None)
    windows = None
    if current and current.provider in providers:
        try:
            u = providers[current.provider].usage()
            windows = u.model_dump() if u else None
        except Exception:  # noqa: BLE001  usage is advisory
            windows = None
    return {
        "agents": agents(events, running),
        "permissions": permissions(events),
        "progress": progress(session.runs),
        # The staged pipeline's place, when the app is running one: {"run", "stage"}.
        "pipeline": session.pipeline,
        "project": session.project,
        "cost": cost(session, events, providers),
        "windows": windows,
        "at": time.time(),
    }
