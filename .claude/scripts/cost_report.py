#!/usr/bin/env python3
"""cost_report.py — where a session's tokens went: orchestrating thread vs subagents.

    python3 .claude/scripts/cost_report.py                  # every session, newest last
    python3 .claude/scripts/cost_report.py --run <slug>     # sessions that worked on a run
    python3 .claude/scripts/cost_report.py --last 3         # the three most recent
    python3 .claude/scripts/cost_report.py --json           # machine-readable

Reads the Claude Code transcripts for this workspace
(~/.claude/projects/<workspace>/<session>.jsonl and <session>/subagents/*.jsonl),
counting each API call once (a streamed message repeats its usage on every line).
It makes no model call and changes nothing.

The figure to watch is "mean context per call" on the main thread. It is re-read in
full on every call, so it drives cost far more than the scouts do. Baseline, the
five research sessions run before 2026-10-09: the main thread took 65–81% of all
input, at a mean of 216k–339k tokens per call.

Codex sessions are not covered; their transcripts live under ~/.codex/.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = Path.home() / ".claude" / "projects"
RUN = re.compile(r"outputs/(20\d\d-\d\d-\d\d-[a-z0-9-]+)")


def transcripts_dir() -> Path:
    """Claude Code names the folder after the workspace path, with every
    non-alphanumeric character replaced by a dash."""
    return PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))


def scan(path: Path) -> dict:
    seen: set = set()
    models: dict = defaultdict(lambda: {"calls": 0, "input": 0, "cache_write": 0,
                                         "cache_read": 0, "output": 0})
    contexts: list = []
    runs: dict = defaultdict(int)
    started = None
    for line in path.open(errors="ignore"):
        for slug in RUN.findall(line):
            runs[slug] += 1
        try:
            d = json.loads(line)
        except ValueError:
            continue
        started = started or d.get("timestamp")
        if d.get("type") != "assistant":
            continue
        msg = d.get("message") or {}
        mid = msg.get("id")
        if not mid or mid in seen or msg.get("model") == "<synthetic>":
            continue
        seen.add(mid)
        u = msg.get("usage") or {}
        m = models[msg.get("model", "?")]
        m["calls"] += 1
        m["input"] += u.get("input_tokens", 0)
        m["cache_write"] += u.get("cache_creation_input_tokens", 0)
        m["cache_read"] += u.get("cache_read_input_tokens", 0)
        m["output"] += u.get("output_tokens", 0)
        contexts.append(u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                        + u.get("cache_read_input_tokens", 0))
    return {"started": started, "models": dict(models), "contexts": contexts,
            "runs": dict(runs)}


def total(models: dict) -> dict:
    out = {"calls": 0, "input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    for m in models.values():
        for k in out:
            out[k] += m[k]
    out["input_all"] = out["input"] + out["cache_write"] + out["cache_read"]
    return out


def session(path: Path) -> dict:
    head = scan(path)
    sub_models: dict = defaultdict(lambda: {"calls": 0, "input": 0, "cache_write": 0,
                                             "cache_read": 0, "output": 0})
    subs = sorted((path.parent / path.stem / "subagents").glob("*.jsonl"))
    for s in subs:
        for model, m in scan(s)["models"].items():
            for k, v in m.items():
                sub_models[model][k] += v
    main_t, sub_t = total(head["models"]), total(dict(sub_models))
    ctx = head["contexts"]
    both = main_t["input_all"] + sub_t["input_all"]
    return {
        "session": path.stem,
        "started": head["started"],
        "runs": sorted(head["runs"], key=lambda r: -head["runs"][r]),
        "subagents": len(subs),
        "main": {**main_t, "models": head["models"],
                 "mean_context": sum(ctx) // len(ctx) if ctx else 0,
                 "peak_context": max(ctx) if ctx else 0},
        "sub": {**sub_t, "models": dict(sub_models)},
        "main_share": round(main_t["input_all"] / both, 3) if both else 0.0,
    }


def fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", help="only sessions whose transcript names this run")
    ap.add_argument("--last", type=int, help="only the N most recent sessions")
    ap.add_argument("--min-calls", type=int, default=5,
                    help="skip sessions with fewer main-thread calls (default 5)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    folder = transcripts_dir()
    if not folder.is_dir():
        print(f"No transcripts at {folder}", file=sys.stderr)
        return 1
    rows = [session(p) for p in folder.glob("*.jsonl")]
    rows = [r for r in rows if r["main"]["calls"] >= args.min_calls]
    if args.run:
        rows = [r for r in rows if any(args.run in slug for slug in r["runs"])]
    rows.sort(key=lambda r: r["started"] or "")
    if args.last:
        rows = rows[-args.last:]

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"{'session':9} {'started':16} {'calls':>5} {'mean ctx':>8} {'peak':>6} "
          f"{'main in':>8} {'main out':>8} {'sub in':>7} {'agents':>6} {'main %':>6}  run")
    for r in rows:
        m, s = r["main"], r["sub"]
        print(f"{r['session'][:8]:9} {(r['started'] or '')[:16]:16} {m['calls']:>5} "
              f"{fmt(m['mean_context']):>8} {fmt(m['peak_context']):>6} "
              f"{fmt(m['input_all']):>8} {fmt(m['output']):>8} {fmt(s['input_all']):>7} "
              f"{r['subagents']:>6} {r['main_share'] * 100:>5.0f}%  "
              f"{r['runs'][0] if r['runs'] else '-'}")
    print("\nin = fresh input + cache writes + cache reads. main % = the orchestrating "
          "thread's share of all input.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
