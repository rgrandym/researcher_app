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
from pathlib import Path
from types import ModuleType
from typing import Any

from backend import config, router, sessions, usage, workspace
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


def task_start(events: list[Event]) -> int:
    """Where the current task begins: the latest message, or a handover that carried it on."""
    return next(
        (i for i in range(len(events) - 1, -1, -1) if events[i].type in ("user", "handoff")), 0
    )


def earlier_agents(events: list[Event]) -> int:
    """Subagents launched by earlier tasks of this conversation, not shown in the panel."""
    start = task_start(events)
    return sum(1 for e in events[:start] if e.type == "tool_call" and e.data.get("subagent"))


def agents(events: list[Event], running: bool) -> list[dict[str, Any]]:
    """The current task's main thread and subagents: what is working now, not the whole
    conversation's history (earlier_agents counts those)."""
    events = events[task_start(events) :]
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


def open_round(path: Path, running: bool) -> dict[str, Any] | None:
    """The run's latest expansion round, with its stages, while it is open: not yet
    integrated (no diff.md), or still being worked on by this session's turn. A finished
    round returns None and the run's own stages stand."""
    rounds = path / "rounds"
    found = (
        [p for p in rounds.iterdir() if p.is_dir() and p.name[1:].isdigit()]
        if rounds.is_dir()
        else []
    )
    if not found:
        return None
    rnd = max(found, key=lambda p: int(p.name[1:]))
    integrated = (rnd / "diff.md").is_file()
    if integrated and not running:
        return None

    def count(sub: str) -> int:
        return len(list((rnd / sub).glob("*.md"))) if (rnd / sub).is_dir() else 0

    def named(*patterns: str) -> list[str]:
        return sorted(p.name for pat in patterns for p in rnd.glob(pat))

    notes, digests = count("notes"), count("digests")
    review = named("verification*.md", "reverify*.md")
    critique = named("critique*.md")
    repair = named("repair-log*.md")
    stages = [
        ("ask", (rnd / "ask.md").is_file(), "the follow-up, verbatim"),
        ("research", notes + digests > 0, f"{notes} note file(s), {digests} digest(s)"),
        ("reconcile", (rnd / "reconcile.md").is_file(), "new findings classified"),
        ("integrate", integrated, "report.md updated, diff.md written"),
        ("verify", bool(review), ", ".join(review) or "not yet"),
        ("critique", bool(critique), ", ".join(critique) or "not yet"),
        ("repair", bool(repair), ", ".join(repair) or "not yet"),
    ]
    return {
        "name": rnd.name,
        "notes": notes,
        "stages": [{"stage": k, "ok": "yes" if ok else "", "detail": d} for k, ok, d in stages],
    }


# ------------------------------------------------------------------ the current task's steps

# Each task, named by the command its message started with, has its own four steps. A step is
# done only on evidence from after the task began: a file of the run written since then, an
# agent of a kind launched since then, or the turn having finished. So a new task always
# starts from its first step, whatever the run already holds.
TASK_STEPS: dict[str, tuple[str, list[str]]] = {
    "research": ("Research", ["Gather", "Draft", "Review", "Finish"]),
    "research-pipeline": ("Research pipeline", ["Gather", "Draft", "Review", "Finish"]),
    "expand": ("Expansion", ["Gather", "Integrate", "Review", "Finish"]),
    "user-edits": ("Absorbing your edits", ["Read", "Absorb", "Check", "Done"]),
    "verify": ("Verification", ["Read", "Re-check", "Grade", "Done"]),
    "critique": ("Critique", ["Read", "Critique", "Write up", "Done"]),
    "repair": ("Repair", ["Read", "Fix", "Log", "Done"]),
    "report": ("Draft", ["Read", "Write", "Check", "Done"]),
    "export": ("Export", ["Read", "Render", "Check", "Done"]),
}
CHAT_STEPS = ("Question", ["Read", "Work", "Answer", "Done"])


def _written(run: Path | None, since: float, *patterns: str) -> bool:
    """Whether any file of the run matching the patterns was written after `since`."""
    if run is None:
        return False
    for pat in patterns:
        for p in run.glob(pat):
            try:
                if p.is_file() and p.stat().st_mtime >= since:
                    return True
            except OSError:
                continue
    return False


def task(session: sessions.Session, events: list[Event], running: bool) -> dict[str, Any] | None:
    """The steps of the task the latest message started, judged from evidence since then."""
    start = next((i for i in range(len(events) - 1, -1, -1) if events[i].type == "user"), None)
    if start is None:
        return None
    since = events[start].ts
    after = events[start + 1 :]
    text = str(events[start].data.get("text") or "")
    # A message without a command can still carry one on (Retry, a handover): the routing
    # notice that follows it names the command it continued ("/expand (continued): ...").
    route = next(
        (str(e.data.get("text") or "") for e in after if e.type == "notice" and e.data.get("kind") == "route"),
        "",
    )
    name = router.command_of(text) or router.command_of(route.split(" ", 1)[0]) or ""
    label, steps = TASK_STEPS.get(name, CHAT_STEPS)
    finished = not running and any(e.type == "done" for e in after)
    calls = [e for e in after if e.type == "tool_call"]
    agents = [str((e.data.get("subagent") or {}).get("type") or "") for e in calls if e.data.get("subagent")]
    worked = bool(calls)
    run_name = session.project or (session.runs[-1] if session.runs else None)
    try:
        run = workspace.run_dir(run_name) if run_name else None
    except (ValueError, FileNotFoundError):
        run = None
    w = lambda *pats: _written(run, since, *pats)  # noqa: E731
    report = w("report.md", "draft.md")

    if name in ("research", "research-pipeline"):
        done = [
            w("brief.md", "coverage.md") and w("evidence.jsonl") or report,
            report,
            w("verification*.md") and w("critique*.md"),
            w("repair-log*.md") or finished,
        ]
    elif name == "expand":
        rnd = next(iter(sorted((run / "rounds").glob("r*"), key=lambda p: p.stat().st_mtime, reverse=True)), None) \
            if run and (run / "rounds").is_dir() else None
        fresh = rnd is not None and rnd.stat().st_mtime >= since - 5
        r = (lambda *pats: fresh and _written(rnd, since, *pats))  # noqa: E731
        # A continued round (Retry, a handover) already holds its files, so the agents say
        # where it stands too: a writer launched means gathering is over and integration on.
        writing = any("writer" in a for a in agents)
        writer_done = any(
            e.type == "tool_result" and e.data.get("subagent_done")
            and any(c.data.get("id") == e.data.get("id") and "writer" in str((c.data.get("subagent") or {}).get("type")) for c in calls)
            for e in after
        )
        done = [
            r("reconcile.md", "diff.md") or writing,
            r("diff.md") or (writer_done and report),
            r("verification*.md", "reverify*.md", "critique*.md") or any("verif" in a or "critic" in a for a in agents),
            r("repair-log*.md") or finished,
        ]
    elif name == "user-edits":
        done = [worked, report, report and len(calls) > 0 and finished or w(".voice-mirror-*.md") and report, finished]
    elif name == "verify":
        done = [worked, any("verif" in a for a in agents), w("verification*.md"), finished]
    elif name == "critique":
        done = [worked, any("critic" in a for a in agents), w("critique*.md"), finished]
    elif name == "repair":
        done = [worked, report, w("repair-log*.md"), finished]
    elif name == "report":
        done = [worked, report, report and finished, finished]
    elif name == "export":
        done = [worked, w("export/*/*.html", "export/*/*.pdf"), finished, finished]
    else:
        answered = any(e.type == "assistant_text" for e in after)
        done = [worked or answered, worked and answered or finished, finished, finished]
    if finished:
        # The task is over: what it did is done, and a step it never took (an expansion with
        # no review, say) is shown as skipped rather than left pending for ever.
        state = ["done" if d else "skipped" for d in done[:-1]] + ["done"]
    else:
        # Still working: the stepper fills from the left, and the first open step is current.
        state, ok = [], True
        for d in done:
            ok = ok and bool(d)
            state.append("done" if ok else "todo")
        if "todo" in state:
            state[state.index("todo")] = "current"
    return {
        "command": name,
        "label": label,
        "text": text[:160],
        "started": since,
        "running": running and not finished,
        "steps": [{"label": lbl, "state": st} for lbl, st in zip(steps, state)],
        "run": run.name if run else None,
    }


def progress(runs: list[str], running: bool = False) -> list[dict[str, Any]]:
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
                "round": open_round(path, running),
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
        tokens_in, tokens_out, used_searches = seg.tokens_in, seg.tokens_out, seg.searches
        if seg.provider.startswith("codex"):
            # Codex's stream reports usage only for a completed turn and only the main
            # thread's; its rollout files hold the rest (a turn stopped by a limit, subagents).
            rollout = usage.codex_thread_usage(seg.native_session_id)
            if rollout:
                tokens_in = max(tokens_in, rollout["tokens_in"])
                tokens_out = max(tokens_out, rollout["tokens_out"])
                used_searches = max(used_searches, rollout["searches"])
        segments.append(
            {
                "provider": seg.provider,
                "label": providers[seg.provider].label
                if seg.provider in providers
                else seg.provider,
                "model": seg.model,
                "cost_usd": round(seg.cost_usd, 4),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "searches": used_searches,
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
        "agents_earlier": earlier_agents(events),
        "permissions": permissions(events),
        "progress": progress(session.runs, running),
        # The task the latest message started, with its own steps (TASK_STEPS).
        "task": task(session, events, running),
        # The staged pipeline's place, when the app is running one: {"run", "stage"}.
        "pipeline": session.pipeline,
        "project": session.project,
        "cost": cost(session, events, providers),
        "windows": windows,
        "at": time.time(),
    }
