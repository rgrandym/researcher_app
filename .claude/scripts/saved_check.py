#!/usr/bin/env python3
"""Detect the one failure an agent cannot see: an edit still sitting in the
author's editor, never written to disk.

    saved_check.py <run>                 # did the author save since the agent wrote?
    saved_check.py <run> letter.md       # a named document rather than the run's first master
    saved_check.py <run> --wait 120      # say "save now", then poll for up to 120s
    saved_check.py <run> --rescue        # copy the editor's local history into <run>/.history/

An agent reads files. An editor holds unsaved buffers. Nothing bridges the two,
so a round that runs against a stale file produces a confident report about work
the author cannot see, and the author's next save silently overwrites the
agent's. Both halves of that are invisible without this check.

The signal is mtime. `voice.py mark` writes `.voice-mirror-<name>.md` on every
agent write, so the mirror's timestamp is "when the agent last wrote". If the
report is not newer than the mirror, the author has not saved since, and any
edit they believe they made is still in the editor.

Exit 0 = a save landed, go ahead. Exit 1 = nothing saved, stop and say so.
Exit 2 = no baseline, so the question cannot be answered.
"""
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runmeta                                            # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
# Where VS Code and its forks keep per-file local history. History is written on
# SAVE, so it recovers overwritten versions but never an unsaved buffer.
HISTORY_DIRS = [
    Path.home() / "Library/Application Support/Code/User/History",
    Path.home() / "Library/Application Support/Code - Insiders/User/History",
    Path.home() / "Library/Application Support/Cursor/User/History",
    Path.home() / "Library/Application Support/Windsurf/User/History",
    Path.home() / ".config/Code/User/History",
]


def stamp(path):
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%H:%M:%S")


def history_for(target):
    """Yield (entry_path, mtime) for every saved version of `target`, newest last."""
    uri = target.resolve().as_uri()
    for base in HISTORY_DIRS:
        if not base.is_dir():
            continue
        for meta in base.glob("*/entries.json"):
            try:
                data = json.loads(meta.read_text())
            except (OSError, ValueError):
                continue
            if data.get("resource") != uri:
                continue
            out = []
            for row in data.get("entries", []):
                p = meta.parent / row["id"]
                if p.exists():
                    out.append((p, row.get("timestamp", 0) / 1000))
            return sorted(out, key=lambda x: x[1])
    return []


def rescue(run, report):
    """Copy every saved version the editor still holds into the run folder.

    Editors prune local history. Once copied here it is part of the run and
    survives, which is what makes a lost round recoverable an hour later.
    """
    dest = run / ".history"
    dest.mkdir(exist_ok=True)
    entries = history_for(report)
    if not entries:
        print(f"no editor history found for {report}")
        return 1
    for path, ts in entries:
        name = f"{report.stem}-{datetime.fromtimestamp(ts):%Y%m%d-%H%M%S}.md"
        shutil.copy2(path, dest / name)
        print(f"  {name}  {(dest / name).stat().st_size:>6} bytes")
    print(f"{len(entries)} version(s) → {dest}")
    return 0


def check(run, wait=0, doc=None):
    report = doc or runmeta.primary(run)
    if report is None:
        print(f"FAIL no master document in {run} "
              f"(expected one of: {', '.join(runmeta.masters(run))})")
        return 2
    name = report.name
    mirror = run / f".voice-mirror-{report.stem}.md"
    if not report.exists():
        print(f"FAIL no document at {report}")
        return 2
    if not mirror.exists():
        print("UNKNOWN  no mirror, so 'since the agent last wrote' has no meaning.")
        print(f"         Run: python3 .claude/scripts/voice.py mark {report}")
        print("         after every agent write, and this check works from then on.")
        return 2

    deadline = time.time() + wait
    asked = False
    while True:
        if report.stat().st_mtime > mirror.stat().st_mtime:
            print(f"SAVED    {name} {stamp(report)} is newer than the agent's "
                  f"last write {stamp(mirror)}. Diff it and proceed.")
            return 0
        if wait and time.time() < deadline:
            if not asked:
                print(f"WAITING  press save in your editor. Polling for "
                      f"{wait}s, checking every 2s.")
                asked = True
            time.sleep(2)
            continue
        break

    print(f"NOT SAVED  {name} {stamp(report)} is not newer than the agent's "
          f"last write {stamp(mirror)}.")
    print()
    print("  Nothing the author typed since then is on disk. Two consequences,")
    print("  and both are silent without this check:")
    print("    1. A review or repair round would run against the agent's own text")
    print("       and report success on work the author cannot see.")
    print("    2. The author's next save carries a buffer that predates the")
    print("       agent's write, so it overwrites it.")
    print()
    print("  Do not proceed. Ask the author to save, or to paste the edit.")
    hist = history_for(report)
    if hist:
        newest = datetime.fromtimestamp(hist[-1][1])
        print(f"\n  Editor history holds {len(hist)} saved version(s), newest "
              f"{newest:%H:%M:%S}. Recover with --rescue.")
    return 1


def main():
    args = [a for a in sys.argv[1:]]
    if not args:
        print(__doc__)
        return 2
    run = Path(args[0])
    if not run.is_dir():
        print(f"FAIL not a run directory: {run}")
        return 2
    doc = None
    named = [a for a in args[1:] if not a.startswith("-") and a.endswith(".md")]
    if named:
        doc = Path(named[0]) if "/" in named[0] else run / named[0]
    if "--rescue" in args:
        return rescue(run, doc or runmeta.primary(run) or run / "report.md")
    wait = 0
    if "--wait" in args:
        i = args.index("--wait")
        wait = int(args[i + 1]) if len(args) > i + 1 else 120
    return check(run, wait, doc)


if __name__ == "__main__":
    sys.exit(main())
