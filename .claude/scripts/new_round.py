#!/usr/bin/env python3
"""new_round.py — open the next expansion round inside a run, never over an old one.

    python3 .claude/scripts/new_round.py <run>          # creates rounds/rN/, prints it
    python3 .claude/scripts/new_round.py <run> --list   # the rounds that exist

Counts the existing rounds in Python, because a shell alias on `ls` once made the
count come back zero and a new round was written over r1, destroying the author's
verbatim follow-up. Refuses (exit 1) if the next round folder already exists.
Creates `rounds/rN/notes/` and `rounds/rN/digests/`.
"""
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    run = Path(sys.argv[1])
    if not run.is_dir():
        print(f"no run folder: {run}", file=sys.stderr)
        return 2
    rounds = run / "rounds"
    existing = sorted((p for p in rounds.iterdir() if p.is_dir() and p.name[1:].isdigit()),
                      key=lambda p: int(p.name[1:])) if rounds.is_dir() else []
    if "--list" in sys.argv:
        print("rounds:", ", ".join(p.name for p in existing) or "none")
        return 0
    n = (int(existing[-1].name[1:]) if existing else 0) + 1
    target = rounds / f"r{n}"
    if target.exists():
        print(f"{target} already exists; recount before writing anything", file=sys.stderr)
        return 1
    (target / "notes").mkdir(parents=True)
    (target / "digests").mkdir()
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
