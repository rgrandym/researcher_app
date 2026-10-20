#!/usr/bin/env python3
"""monitor.py: the research monitor for any agent, Claude Code or Codex.

    monitor.py status                  # one view of the newest session in this workspace
    monitor.py watch                   # the same, refreshed every 5 s (a VS Code terminal)
    monitor.py more                    # raise the newest session's web caps
    monitor.py codex-hook              # Codex hook: reads the event on stdin

Claude Code gets these features from the research-monitor mod in
.claude/skills/research-monitor/, which can refuse a search outright. Codex has
no mods, and its web search is a hosted tool that never reaches a hook, so for
Codex this script counts searches from the session log and tells the agent to
stop once the cap is reached. Both read their caps from .claude/monitor.json.

The view reads transcripts and the run folder only. It makes no model call.
A hook that fails prints nothing and exits 0: the monitor never blocks work.
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".claude/monitor.json"
STATE = ROOT / ".claude/.monitor-state"
CLAUDE_DIR = Path.home() / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))
CODEX_DIR = Path.home() / ".codex/sessions"
RUN = re.compile(r"outputs/(\d{4}-\d{2}-\d{2}-[A-Za-z0-9._-]+)")
DEFAULTS = {"searchCap": 400, "fetchCap": 700, "warnEvery": 100, "raise": {"searches": 100, "fetches": 150}}


# ---------------------------------------------------------------- config and state

def config() -> dict:
    try:
        return {**DEFAULTS, **json.loads(CONFIG.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def state(session: str) -> dict:
    try:
        return json.loads((STATE / f"{session}.json").read_text())
    except (OSError, ValueError):
        return {"extraSearches": 0, "extraFetches": 0, "noticed": -1}


def save_state(session: str, value: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / f"{session}.json").write_text(json.dumps(value))


def caps(session: str) -> tuple[int, int]:
    c, s = config(), state(session)
    return c["searchCap"] + s["extraSearches"], c["fetchCap"] + s["extraFetches"]


# ---------------------------------------------------------------- reading sessions

def _lines(path: Path):
    try:
        with path.open(errors="replace") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def _agent(name: str, kind: str, status: str = "") -> dict:
    return {"name": name, "type": kind, "status": status, "tokensIn": 0, "tokensOut": 0, "web": 0}


def claude_session(path: Path) -> dict:
    """Counts from a Claude Code transcript and its subagents' transcripts."""
    out = {"provider": "Claude Code", "id": path.stem, "searches": 0, "fetches": 0,
           "agents": [], "windows": [], "run": None, "mtime": path.stat().st_mtime}
    files = [(path, _agent("main", "main"))]
    for sub in sorted((path.parent / path.stem / "subagents").glob("agent-*.jsonl")):
        meta = {}
        try:
            meta = json.loads(sub.with_suffix(".meta.json").read_text())
        except (OSError, ValueError):
            pass
        files.append((sub, _agent(meta.get("description", sub.stem), meta.get("agentType", "agent"))))
    for f, agent in files:
        for row in _lines(f):
            msg = row.get("message") or {}
            usage = msg.get("usage") or {}
            agent["tokensIn"] += sum(usage.get(k, 0) or 0 for k in
                                     ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            agent["tokensOut"] += usage.get("output_tokens", 0) or 0
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name, args = block.get("name"), block.get("input") or {}
                if name in ("WebSearch", "WebFetch"):
                    out["searches" if name == "WebSearch" else "fetches"] += 1
                    agent["web"] += 1
                m = RUN.search(" ".join(str(args.get(k, "")) for k in ("file_path", "command", "path")))
                if m:
                    out["run"] = m.group(1)
        agent["status"] = "recent" if time.time() - f.stat().st_mtime < 60 else "idle"
        out["agents"].append(agent)
    return out


def _codex_meta(path: Path) -> dict:
    for row in _lines(path):
        return row.get("payload", {}) if row.get("type") == "session_meta" else {}
    return {}


def codex_files(days: int = 3) -> list[tuple[Path, dict]]:
    """Codex rollouts for this workspace from the last few days, newest first."""
    found = []
    for back in range(days):
        day = CODEX_DIR / (datetime.now() - timedelta(days=back)).strftime("%Y/%m/%d")
        for f in day.glob("rollout-*.jsonl"):
            meta = _codex_meta(f)
            if meta.get("cwd") == str(ROOT):
                found.append((f, meta))
    return sorted(found, key=lambda p: p[0].stat().st_mtime, reverse=True)


def codex_session(session_id: str, files: list[tuple[Path, dict]] | None = None) -> dict:
    """Counts from every Codex thread of one session, subagents included."""
    files = files if files is not None else codex_files()
    threads = [(f, m) for f, m in files if m.get("session_id") == session_id]
    out = {"provider": "Codex", "id": session_id, "searches": 0, "fetches": 0, "agents": [],
           "windows": [], "run": None, "mtime": max((f.stat().st_mtime for f, _ in threads), default=0)}
    for f, meta in sorted(threads, key=lambda p: "parent_thread_id" in p[1]):
        is_main = "parent_thread_id" not in meta
        agent = _agent("main" if is_main else meta.get("thread_source", "agent"),
                       "main" if is_main else "subagent")
        for row in _lines(f):
            p = row.get("payload") or {}
            kind = p.get("type")
            if kind == "web_search_end":
                action = (p.get("action") or {}).get("type")
                out["searches" if action == "search" else "fetches"] += 1
                agent["web"] += 1
            elif kind == "token_count":
                total = (p.get("info") or {}).get("total_token_usage") or {}
                agent["tokensIn"] = total.get("input_tokens", 0)
                agent["tokensOut"] = total.get("output_tokens", 0)
                limits = p.get("rate_limits") or {}
                if is_main and limits:
                    out["windows"] = [
                        {"kind": f"{w['window_minutes'] // 60}h" if w["window_minutes"] < 1440
                         else f"{w['window_minutes'] // 1440}d",
                         "percentUsed": w.get("used_percent", 0),
                         "resetsAt": datetime.fromtimestamp(w["resets_at"]).strftime("%H:%M %a")}
                        for w in (limits.get("primary"), limits.get("secondary")) if w
                    ]
            m = RUN.search(json.dumps(p)[:4000]) if kind in ("exec_command_end", "patch_apply_end") else None
            if m:
                out["run"] = m.group(1)
        agent["status"] = "recent" if time.time() - f.stat().st_mtime < 60 else "idle"
        out["agents"].append(agent)
    return out


def newest_session() -> dict | None:
    """The newest session in this workspace, whichever provider ran it."""
    candidates = []
    claude = sorted(CLAUDE_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if claude:
        candidates.append(("claude", claude[0], claude[0].stat().st_mtime))
    codex = codex_files()
    if codex:
        candidates.append(("codex", codex[0], codex[0][0].stat().st_mtime))
    if not candidates:
        return None
    kind, ref, _ = max(candidates, key=lambda c: c[2])
    return claude_session(ref) if kind == "claude" else codex_session(ref[1].get("session_id", ""), codex)


# ---------------------------------------------------------------- the run

def newest_run() -> str | None:
    runs = [d for d in (ROOT / "outputs").glob("*") if d.is_dir() and RUN.search(f"outputs/{d.name}")]
    return max(runs, key=lambda d: d.stat().st_mtime).name if runs else None


def stages(run: str) -> list[tuple[str, str, str]]:
    done = subprocess.run([sys.executable, str(ROOT / ".claude/scripts/run_check.py"), f"outputs/{run}"],
                          cwd=ROOT, capture_output=True, text=True, timeout=20)
    rows = []
    for line in done.stdout.splitlines():
        m = re.match(r"^ {2}(ok|MISSING)\s+(\S+)\s+(.*)$", line)
        if m:
            rows.append((m.group(1), m.group(2), m.group(3).strip()))
    return rows


def saved_check(run: str) -> tuple[int, str]:
    done = subprocess.run([sys.executable, str(ROOT / ".claude/scripts/saved_check.py"), f"outputs/{run}"],
                          cwd=ROOT, capture_output=True, text=True, timeout=20)
    return done.returncode, "\n".join(done.stdout.strip().splitlines()[:6])


# ---------------------------------------------------------------- the view

def _k(n: int) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{round(n / 1000)}k" if n >= 1000 else str(n)


def render(s: dict | None) -> str:
    if s is None:
        return "No Claude Code or Codex session found for this workspace."
    search_cap, fetch_cap = caps(s["id"])
    run = s["run"] or newest_run()
    out = [f"{s['provider']} · session {s['id'][:8]} · {datetime.fromtimestamp(s['mtime']):%H:%M}", ""]
    out += ["Usage"] + [f"  {w['kind']} {round(w['percentUsed'])}% · resets {w['resetsAt']}" for w in s["windows"]]
    if not s["windows"] and s["provider"] == "Claude Code":
        out.append("  cost and plan windows: /monitor or the status line in Claude Code")
    out.append(f"  web {s['searches']}/{search_cap} searches · {s['fetches']}/{fetch_cap} fetches")
    out += ["", "Agents"]
    for a in s["agents"][-20:]:
        out.append(f"  {a['status']:<7} {a['type']} · {a['name'][:50]} · "
                   f"{_k(a['tokensIn'])} in / {_k(a['tokensOut'])} out · {a['web']} web")
    out += ["", f"Run {run or '(none yet)'}"]
    if run:
        out += [f"  {'done   ' if st == 'ok' else 'pending'} {name:<9} {detail}" for st, name, detail in stages(run)]
    return "\n".join(out)


# ---------------------------------------------------------------- Codex hooks

def _context(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


def codex_hook(event: dict) -> None:
    name = event.get("hook_event_name", "")
    session = event.get("session_id", "")
    if not session:
        return
    counts = codex_session(session)
    search_cap, fetch_cap = caps(session)
    over = counts["searches"] >= search_cap or counts["fetches"] >= fetch_cap
    notes = []

    if name == "UserPromptSubmit" and "user-edits" in event.get("prompt", ""):
        run = (RUN.search(event.get("prompt", "")) or [None, None])[1] or counts["run"] or newest_run()
        if run:
            code, said = saved_check(run)
            if code == 1:
                notes.append(f"research-monitor ran saved_check.py on outputs/{run}: exit 1, no save has landed "
                             "since the agent last wrote. Ask the author to save or paste the edit, keep this "
                             f"task pending, and rerun the check after they answer.\n{said}")
            elif code != 0:
                notes.append(f"research-monitor ran saved_check.py on outputs/{run}: exit {code}, so whether the "
                             "author saved cannot be told. Say so to the author before reading their edits.")

    st = state(session)
    if over and (name == "UserPromptSubmit" or st["noticed"] != counts["searches"] + counts["fetches"]):
        notes.append(f"research-monitor: this session's web cap is reached ({counts['searches']}/{search_cap} "
                     f"searches, {counts['fetches']}/{fetch_cap} fetches). Do not search or open pages further. "
                     "Finish the current stage with the evidence already on disk, and register what is still "
                     "missing as a gap with wanted.py. The author can raise the cap with "
                     "`python3 .claude/scripts/monitor.py more`.")
        save_state(session, {**st, "noticed": counts["searches"] + counts["fetches"]})

    if notes:
        _context(name, "\n\n".join(notes))


# ---------------------------------------------------------------- entry

def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "codex-hook":
        try:
            codex_hook(json.loads(sys.stdin.read() or "{}"))
        except Exception:                                  # noqa: BLE001  a hook never blocks work
            pass
        return 0
    if cmd == "more":
        s = newest_session()
        if s is None:
            print("No session found.")
            return 1
        st, add = state(s["id"]), config()["raise"]
        save_state(s["id"], {**st, "extraSearches": st["extraSearches"] + add["searches"],
                             "extraFetches": st["extraFetches"] + add["fetches"]})
        search_cap, fetch_cap = caps(s["id"])
        print(f"{s['provider']} session {s['id'][:8]}: caps now {search_cap} searches, {fetch_cap} fetches.")
        return 0
    if cmd == "watch":
        try:
            while True:
                print("\033[2J\033[H" + render(newest_session()), flush=True)
                time.sleep(5)
        except KeyboardInterrupt:
            return 0
    print(render(newest_session()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
