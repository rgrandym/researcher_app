#!/usr/bin/env python3
"""run_card.py: where a run stands, in one call.

    python3 .claude/scripts/run_card.py <run> [--doc <master.md>]

A command typed into a run starts a fresh session that knows nothing about the run.
Without this card it spends its first ten calls listing folders, reading .run.json,
grepping the report and opening logs, and every later call re-reads what those
calls returned. The card answers the same questions in about a hundred lines:

  - the run's kind and its masters, with words and when each was last written
  - whether the author has saved an edit the agent has not yet seen (saved_check)
  - the stages still missing (run_check), not the ones that are done
  - the section map of the master the request is about: line ranges and headings
  - the last entries in the repair log, and how many findings are still open
  - the files changed most recently

It reads and prints; it never writes. Read a section with
`section_map.py <run> --show <heading>` after it, never the whole document.
"""
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import runmeta  # noqa: E402

MAX_SECTIONS = 40
MAX_RECENT = 8


def run(args) -> tuple:
    p = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=HERE.parents[1])
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def when(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def card(run_dir: Path, doc: str = "") -> str:
    out = []
    meta = runmeta.meta(run_dir)
    masters = [run_dir / m for m in runmeta.masters(run_dir) if (run_dir / m).is_file()]
    primary = run_dir / doc if doc else runmeta.primary(run_dir)
    out.append(f"# {run_dir.name} · {meta.get('kind', 'research')}")
    for m in masters:
        mark = "  ← primary" if primary and m == primary else ""
        out.append(f"- {m.name}: {len(m.read_text().split())} words, written {when(m)}{mark}")

    code, text = run([str(HERE / "saved_check.py"), str(run_dir)])
    first = text.strip().splitlines()[:1]
    out.append(f"\nAuthor edits: {first[0] if first else 'nothing to report'}")

    code, text = run([str(HERE / "run_check.py"), str(run_dir)])
    missing = [l.strip() for l in text.splitlines() if "MISSING" in l]
    out.append("Stages missing: " + ("none" if not missing else ""))
    out += [f"  {re.sub(r'\\s+', ' ', l)[:160]}" for l in missing[:8]]

    if primary and primary.is_file():
        code, text = run([str(HERE / "section_map.py"), str(primary)])
        rows = [l for l in text.splitlines()[1:] if re.match(r"\s*\d+-\d+", l)]
        out.append(f"\nSections of {primary.name} (line range, words, heading):")
        out += [f"  {re.sub(r'\\s+', ' ', l.strip())[:150]}" for l in rows[:MAX_SECTIONS]]
        if len(rows) > MAX_SECTIONS:
            out.append(f"  (+{len(rows) - MAX_SECTIONS} more; section_map.py shows them all)")

    log = run_dir / "repair-log.md"
    if log.is_file():
        text = log.read_text()
        heads = re.findall(r"^#{2,3} .+$", text, re.M)
        open_items = len(re.findall(r"\bopen \(", text, re.I))
        out.append(f"\nRepair log: {len(heads)} entries, {open_items} marked open. Latest:")
        out += [f"  {h[:150]}" for h in heads[-3:]]

    files = [p for p in run_dir.rglob("*") if p.is_file() and not p.name.startswith(".")
             and not ({"export", ".history", "library"} & set(p.relative_to(run_dir).parts))]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out.append("\nChanged most recently:")
    out += [f"  {when(p)}  {p.relative_to(run_dir)}" for p in files[:MAX_RECENT]]
    return "\n".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.stderr.write(__doc__)
        return 2
    run_dir = Path(args[0])
    if run_dir.is_file():
        run_dir = run_dir.parent
    if not run_dir.is_dir():
        sys.stderr.write(f"no such run: {run_dir}\n")
        return 1
    doc = sys.argv[sys.argv.index("--doc") + 1] if "--doc" in sys.argv else ""
    print(card(run_dir, Path(doc).name if doc else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
