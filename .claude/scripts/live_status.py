#!/usr/bin/env python3
"""live_status.py — what the research-live mod shows and acts on, as one JSON line.

    python3 .claude/scripts/live_status.py status [--since EPOCH] [--running]
    python3 .claude/scripts/live_status.py claim <run> <file> <mtime>
    python3 .claude/scripts/live_status.py export <run> <style>

`status` reports the most recently active run: its four steps (Gather, Draft,
Review, Finish), or an open expansion round's own four steps; an author save to
its master that no agent has absorbed (master newer than `.voice-mirror-*`, see
saved_check.py), once the file has been quiet; and HTML exports older than the
master. `--since` ignores saves made before that moment (the session's start);
`--running` keeps a round open while a turn works on it after `diff.md`.

`claim` takes the job of absorbing one save (exit 0), or says another watcher
already took it (exit 1).

`export` re-renders `<run>/export/<style>/report.html` with the app's own render
chain (app/backend/render.py), so the file matches what the app's Export writes.

The same stage rules as the app's activity panel (app/backend/activity.py,
ActivityPanel.tsx), so the two views agree.
"""
import contextlib
import io
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
RUN_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-")
STAGE_LINE = re.compile(r"^\s+(ok|MISSING)\s+(\S+)\s+(.*)$")
EDIT_QUIET_S = 60
EXPORT_QUIET_S = 15

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_check  # noqa: E402
import runmeta  # noqa: E402


def master_of(run: Path) -> Path | None:
    try:
        names = runmeta.masters(run)
    except Exception:  # noqa: BLE001  a run without metadata falls back to the files
        names = [n for n in ("report.md", "draft.md") if (run / n).is_file()]
    for name in names:
        if (run / name).is_file():
            return run / name
    return None


def newest(run: Path) -> float:
    # Hidden files are bookkeeping: the gate touches `.gate-stamp-*` in every run on
    # any write, so they say nothing about which run is being worked on.
    best = 0.0
    for p in run.rglob("*"):
        rel = p.relative_to(run).parts
        if "export" in rel or any(part.startswith(".") for part in rel):
            continue
        with contextlib.suppress(OSError):
            best = max(best, p.stat().st_mtime)
    return best


def run_steps(run: Path) -> list[dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_check.check(run, ship=False)
    ok = {m.group(2) for line in buf.getvalue().splitlines()
          if (m := STAGE_LINE.match(line)) and m.group(1) == "ok"}
    has = ok.__contains__
    return [
        {"label": "Gather", "done": all(map(has, ("brief", "voice", "coverage", "evidence")))},
        {"label": "Draft", "done": has("report") or has("verify") or has("critique")},
        {"label": "Review", "done": has("verify") and has("critique")},
        {"label": "Finish", "done": has("repair") and has("report")},
    ]


def open_round(run: Path, running: bool) -> dict | None:
    rounds = run / "rounds"
    found = [p for p in rounds.iterdir() if p.is_dir() and p.name[1:].isdigit()] \
        if rounds.is_dir() else []
    if not found:
        return None
    rnd = max(found, key=lambda p: int(p.name[1:]))
    integrated = (rnd / "diff.md").is_file()
    if integrated and not running:
        return None
    notes = sum(len(list((rnd / d).glob("*.md"))) for d in ("notes", "digests")
                if (rnd / d).is_dir())
    any_of = lambda *pats: any(True for pat in pats for _ in rnd.glob(pat))  # noqa: E731
    return {
        "name": rnd.name,
        "notes": notes,
        "steps": [
            {"label": "Gather", "done": (rnd / "reconcile.md").is_file() or integrated},
            {"label": "Integrate", "done": integrated},
            {"label": "Review", "done": any_of("verification*.md", "reverify*.md", "critique*.md")},
            {"label": "Finish", "done": any_of("repair-log*.md")},
        ],
    }


def status(since: float, running: bool) -> dict:
    runs = [p for p in OUT.iterdir() if p.is_dir() and RUN_NAME.match(p.name)] \
        if OUT.is_dir() else []
    out: dict = {"run": None, "pending_edit": None, "stale_exports": [], "at": time.time()}
    now = time.time()
    for run in runs:
        master = master_of(run)
        if not master:
            continue
        mtime = master.stat().st_mtime
        mirror = run / f".voice-mirror-{master.stem}.md"
        if (mirror.is_file() and mtime > mirror.stat().st_mtime and mtime > since
                and now - mtime >= EDIT_QUIET_S and out["pending_edit"] is None):
            out["pending_edit"] = {"run": run.name, "file": master.name, "mtime": mtime}
        for html in sorted((run / "export").glob("*/report.html")):
            if mtime > html.stat().st_mtime and now - mtime >= EXPORT_QUIET_S:
                out["stale_exports"].append(
                    {"run": run.name, "style": html.parent.name, "mtime": mtime})
    if runs:
        active = max(runs, key=newest)
        rnd = open_round(active, running)
        notes = len(list((active / "notes").glob("*.md"))) if (active / "notes").is_dir() else 0
        evidence = 0
        if (active / "evidence.jsonl").is_file():
            with open(active / "evidence.jsonl", "rb") as fh:
                evidence = sum(1 for line in fh if line.strip())
        out["run"] = {
            "name": active.name,
            "round": rnd["name"] if rnd else None,
            "steps": rnd["steps"] if rnd else run_steps(active),
            "notes": rnd["notes"] if rnd else notes,
            "evidence": evidence,
        }
    return out


def claim(run: Path, master: Path, mtime: float) -> bool:
    """Take the job of absorbing one save, atomically: the Research app and this mod may
    both be watching, and only the first to create the marker starts /user-edits.
    The app's backend/autoedits.py uses the same marker name."""
    marker = run / f".autoedit-{master.stem}-{int(mtime)}"
    try:
        os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    for old in run.glob(f".autoedit-{master.stem}-*"):
        if old != marker:
            with contextlib.suppress(OSError):
                old.unlink()
    return True


def export(run: str, style: str) -> int:
    sys.path.insert(0, str(ROOT / "app"))
    from backend import render  # noqa: PLC0415  the app's chain, loaded only to export
    result = render.export(run, None, style, True, ["html"])
    print(json.dumps({"files": result["files"], "check": result["check"].splitlines()[:1]}))
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["status"]:
        since = float(args[args.index("--since") + 1]) if "--since" in args else 0.0
        print(json.dumps(status(since, "--running" in args)))
        return 0
    if args[:1] == ["claim"] and len(args) == 4:
        run = OUT / args[1]
        return 0 if claim(run, run / args[2], float(args[3])) else 1
    if args[:1] == ["export"] and len(args) == 3:
        return export(args[1], args[2])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
