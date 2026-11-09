"""The Activity panel: agents, pipeline progress, web use and cost, built from the
session's event stream and the run's files. No model call feeds it.

Web caps come from `.claude/monitor.json` and the research monitor's per-session raises
in `.claude/.monitor-state/`, read and written through the workspace's own
`monitor.py`, so the app, the Claude Code mod and the Codex hook share one set of caps.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from backend import config, router, sessions, usage, workspace
from backend.providers.base import Event
from backend.sessions import Segment

WEB_TOOLS = ("WebSearch", "WebFetch")
_monitor: ModuleType | None = None
_event_cache: OrderedDict[tuple[str, tuple[int, int, int] | None, bool], dict[str, Any]] = OrderedDict()
_event_cache_lock = threading.Lock()


@lru_cache(maxsize=128)
def _evidence_count(path: Path, mtime_ns: int, size: int) -> int:
    return workspace.count_jsonl(path)


def evidence_count(path: Path) -> int:
    try:
        stat = path.stat()
    except OSError:
        return 0
    return _evidence_count(path, stat.st_mtime_ns, stat.st_size)


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
    finished = next((e for e in reversed(events) if e.type == "done"), None) if not running else None
    failed = bool(finished and finished.data.get("end_reason") not in (None, "done", "stopped"))
    main: dict[str, Any] = {
        "id": "main",
        "type": "main",
        "description": "Main thread",
        "status": "running" if running else ("failed" if failed else "done") if finished else "idle",
        "started": events[0].ts if events else None,
        "ended": finished.ts if finished else None,
        "tokens_in": 0,
        "tokens_out": 0,
        "web": 0,
        "calls": [],
        "calls_total": 0,
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
                "calls_total": 0,
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
            owner["calls_total"] += 1
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
                "evidence_rows": evidence_count(path / "evidence.jsonl"),
                "notes": len(list((path / "notes").glob("*.md")))
                if (path / "notes").is_dir()
                else 0,
                "round": open_round(path, running),
            }
        )
    return out


def cost(
    session: sessions.Session, events: list[Event], providers: dict[str, Any],
    stage_rows: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
    cap_notices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context = context if context is not None else next(
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
        cached_in = seg.cached_in
        if seg.provider.startswith("codex"):
            # Codex's stream reports usage only for a completed turn and only the main
            # thread's; its rollout files hold the rest (a turn stopped by a limit, subagents).
            natives = seg.native_sessions or ([seg.native_session_id] if seg.native_session_id else [])
            rollouts = [usage.codex_thread_usage(native) for native in dict.fromkeys(natives)]
            found = [row for row in rollouts if row]
            if found:
                tokens_in = max(tokens_in, sum(row["tokens_in"] for row in found))
                tokens_out = max(tokens_out, sum(row["tokens_out"] for row in found))
                cached_in = max(cached_in, sum(row.get("cached_in", 0) for row in found))
                used_searches = max(used_searches, sum(row["searches"] for row in found))
        segments.append(
            {
                "provider": seg.provider,
                "label": providers[seg.provider].label
                if seg.provider in providers
                else seg.provider,
                "model": seg.model,
                "cost_usd": round(seg.cost_usd, 4),
                "tokens_in": tokens_in,
                "fresh_in": max(0, tokens_in - cached_in - seg.cache_written),
                "cached_in": cached_in,
                "cache_written": seg.cache_written,
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
        "pipeline_stages": stage_usage(stage_rows if stage_rows is not None else stage_timings(events)),
        "notices": cap_notices if cap_notices is not None else [
            e.data for e in events if e.type == "notice" and e.data.get("kind") == "cap"
        ][-3:],
    }


def stage_timings(events: list[Event]) -> list[dict[str, Any]]:
    """Measure staged turns from transcript timestamps. Overlapping tool and agent
    durations are reported separately; neither is subtracted from wall time."""
    starts = [i for i, e in enumerate(events) if e.type == "notice" and e.data.get("kind") == "route" and e.data.get("stage")]
    result: list[dict[str, Any]] = []
    for pos, start in enumerate(starts):
        stop = starts[pos + 1] if pos + 1 < len(starts) else len(events)
        batch = events[start:stop]
        first = batch[0]
        done = next((e for e in batch if e.type == "done"), None)
        end = done.ts if done else batch[-1].ts
        waits: dict[str, tuple[float, bool]] = {}
        agents: dict[str, float] = {}
        tool_seconds = subagent_seconds = 0.0
        main_waits: list[tuple[float, float]] = []
        for e in batch:
            ident = str(e.data.get("id") or "")
            if e.type == "tool_call" and ident:
                waits[ident] = (e.ts, e.agent is None)
                if e.data.get("subagent"):
                    agents[ident] = e.ts
            elif e.type == "tool_result" and ident:
                if ident in waits:
                    begun, main_wait = waits.pop(ident)
                    tool_seconds += max(0, e.ts - begun)
                    if main_wait:
                        main_waits.append((begun, e.ts))
                if ident in agents:
                    subagent_seconds += max(0, e.ts - agents.pop(ident))
        tool_seconds += sum(max(0, end - t) for t, _ in waits.values())
        subagent_seconds += sum(max(0, end - t) for t in agents.values())
        main_waits.extend((t, end) for t, main_wait in waits.values() if main_wait)
        covered = 0.0
        last = first.ts
        for a, b in sorted(main_waits):
            covered += max(0, b - max(a, last))
            last = max(last, b)
        main_agent_seconds = max(0, end - first.ts - covered)
        input_total = sum(int(e.data.get("tokens_in") or 0) for e in batch if e.type == "usage")
        cached = sum(int(e.data.get("cached_in") or 0) for e in batch if e.type == "usage")
        written = sum(int(e.data.get("cache_written") or 0) for e in batch if e.type == "usage")
        repair_calls = sum(
            e.type == "tool_call" and (e.data.get("subagent") or {}).get("type") in
            ("report-writer", "report-repairer")
            for e in batch
        )
        native = next((str(e.data["session_id"]) for e in batch
                       if e.type == "session" and e.data.get("session_id")), None)
        native = native or first.data.get("native_session")
        result.append({
            "stage": first.data["stage"], "run": first.data.get("run"),
            "wall_seconds": round(max(0, end - first.ts), 1),
            "agent_seconds": round(main_agent_seconds + subagent_seconds, 1),
            "subagent_seconds": round(subagent_seconds, 1),
            "tool_wait_seconds": round(tool_seconds, 1),
            "fresh_in": max(0, input_total - cached - written),
            "cached_in": cached, "cache_written": written,
            "tokens_out": sum(int(e.data.get("tokens_out") or 0) for e in batch if e.type == "usage"),
            "repair_loops": max(0, repair_calls - 1) + sum(
                e.type == "notice" and e.data.get("kind") == "repair_loop" for e in batch
            ),
            "complete": done is not None,
            "_live_at": end,
            "_open_tools": len(waits),
            "_open_subagents": len(agents),
            "_main_waiting": any(main_wait for _, main_wait in waits.values()),
            "_turns": [{"provider": first.provider, "native": native,
                        "fresh_native": first.data.get("fresh_native"),
                        "tokens_in": input_total, "cached_in": cached,
                        "cache_written": written,
                        "tokens_out": sum(int(e.data.get("tokens_out") or 0) for e in batch if e.type == "usage")}],
        })
    grouped: list[dict[str, Any]] = []
    for row in result:
        if grouped and grouped[-1]["stage"] == row["stage"] and (
            not grouped[-1]["run"] or not row["run"] or grouped[-1]["run"] == row["run"]
        ):
            current = grouped[-1]
            current["run"] = current["run"] or row["run"]
            for key in ("wall_seconds", "agent_seconds", "subagent_seconds",
                        "tool_wait_seconds", "fresh_in", "cached_in", "cache_written",
                        "tokens_out", "repair_loops"):
                current[key] += row[key]
            current["_turns"].extend(row["_turns"])
            current["complete"] = row["complete"]
            for key in ("_live_at", "_open_tools", "_open_subagents", "_main_waiting"):
                current[key] = row[key]
        else:
            grouped.append(row)
    return grouped


def stage_usage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add Codex's subagent rollouts to stage totals. Claude stream events already
    include each subagent's usage. A shared or missing Codex thread stays labelled
    partial so the panel cannot suggest that its main-thread tokens are complete."""
    result = []
    for row in rows:
        shown = {key: value for key, value in row.items() if not key.startswith("_")}
        if not row["complete"]:
            elapsed = max(0.0, time.time() - row["_live_at"])
            shown["wall_seconds"] = round(shown["wall_seconds"] + elapsed, 1)
            shown["tool_wait_seconds"] = round(
                shown["tool_wait_seconds"] + elapsed * row["_open_tools"], 1
            )
            shown["subagent_seconds"] = round(
                shown["subagent_seconds"] + elapsed * row["_open_subagents"], 1
            )
            shown["agent_seconds"] = round(
                shown["agent_seconds"] + elapsed * (
                    row["_open_subagents"] + (0 if row["_main_waiting"] else 1)
                ), 1
            )
        codex = [turn for turn in row["_turns"] if str(turn["provider"]).startswith("codex")]
        shown["tokens_complete"] = True
        if codex:
            natives: dict[str, bool] = {}
            for turn in codex:
                native = turn["native"]
                if not native:
                    shown["tokens_complete"] = False
                    continue
                natives.setdefault(native, bool(turn["fresh_native"]))
            total = {"tokens_in": 0, "cached_in": 0, "tokens_out": 0}
            for native, fresh in natives.items():
                if not fresh:
                    shown["tokens_complete"] = False
                    continue
                rollout = usage.codex_thread_usage(native)
                if not rollout:
                    shown["tokens_complete"] = False
                    continue
                for key in total:
                    total[key] += rollout[key]
            codex_in = sum(turn["tokens_in"] for turn in codex)
            codex_cached = sum(turn["cached_in"] for turn in codex)
            codex_out = sum(turn["tokens_out"] for turn in codex)
            if total["tokens_in"] < codex_in or total["tokens_out"] < codex_out:
                shown["tokens_complete"] = False
            if shown["tokens_complete"]:
                shown["fresh_in"] = max(0, shown["fresh_in"] - (codex_in - codex_cached)
                                         + total["tokens_in"] - total["cached_in"])
                shown["cached_in"] += total["cached_in"] - codex_cached
                shown["tokens_out"] += total["tokens_out"] - codex_out
        result.append(shown)
    return result


def permissions(events: list[Event], open_permissions: set[str]) -> list[dict[str, Any]]:
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
                "id": str(e.data.get("id")),
                "ts": e.ts,
                "tool": e.data.get("tool"),
                "kind": e.data.get("kind", "permission"),
                "summary": e.data.get("summary")
                or next((q.get("header") for q in e.data.get("questions") or []), ""),
                "decision": a.get("decision")
                or ("waiting" if str(e.data.get("id")) in open_permissions else "unanswered"),
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


def build(session_id: str, running: bool, providers: dict[str, Any], open_permissions: set[str] | None = None) -> dict[str, Any]:
    session = sessions.load(session_id)
    events = sessions.transcript(session_id)
    key = (session_id, sessions.transcript_revision(session_id), running)
    with _event_cache_lock:
        summary = _event_cache.get(key)
        if summary is not None:
            _event_cache.move_to_end(key)
    if summary is None:
        summary = {
            "agents": agents(events, running),
            "agents_earlier": earlier_agents(events),
            "stage_rows": stage_timings(events),
            "context": next((e.data for e in reversed(events)
                             if e.type == "usage" and e.data.get("context_percent") is not None), {}),
            "cap_notices": [e.data for e in events
                            if e.type == "notice" and e.data.get("kind") == "cap"][-3:],
        }
        with _event_cache_lock:
            _event_cache[key] = summary
            _event_cache.move_to_end(key)
            if len(_event_cache) > 64:
                _event_cache.popitem(last=False)
    current = session.current() or (session.segments[-1] if session.segments else None)
    windows = None
    if current and current.provider in providers:
        try:
            u = providers[current.provider].usage()
            windows = u.model_dump() if u else None
        except Exception:  # noqa: BLE001  usage is advisory
            windows = None
    return {
        "agents": summary["agents"],
        "agents_earlier": summary["agents_earlier"],
        "permissions": permissions(events, open_permissions or set()),
        "progress": progress(session.runs, running),
        # The task the latest message started, with its own steps (TASK_STEPS).
        "task": task(session, events, running),
        # The staged pipeline's place, when the app is running one: {"run", "stage"}.
        "pipeline": session.pipeline,
        "project": session.project,
        "cost": cost(session, events, providers, summary["stage_rows"],
                     summary["context"], summary["cap_notices"]),
        "windows": windows,
        "at": time.time(),
    }
