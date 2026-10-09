#!/usr/bin/env python3
"""run_check.py — report which pipeline stages actually ran in a run.

    python3 .claude/scripts/run_check.py <run>            # state of every stage
    python3 .claude/scripts/run_check.py <run> --ship     # exit 1 if not shippable

A stage is judged by its artefact, and an artefact left as the scaffolded
template counts as a stage that did not run. That distinction is the whole
point of this script: a run once shipped a report whose coverage.md still held
the empty table new_run.sh wrote, so the gap hunt and the coverage audit had
never happened and nothing said so.

Under --ship a research run must have: a prompt, a brief, a recorded voice, a
coverage table with rows in it, evidence, a report, a verification ledger, a
critique, and a repair log. A compose run (a CV, a letter, an answer) is judged
on a shorter list: the prompt, the context the piece was written against, the
piece, and an independent review. Which list applies comes from `.run.json`,
through runmeta.py. Missing stages are named. A run that deliberately skips a
stage says so in the run's own files rather than by leaving a template behind.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runmeta                                            # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# Placeholder text new_run.sh writes. A file still carrying it never got filled.
TEMPLATE = re.compile(r"<what was excluded|<question>|^\s*\|\s*-+\s*\|", re.M)
COMPOSE_TEMPLATE = re.compile(r"<who reads it|<the one thing|<the story the piece")


def has_rows(md: str) -> bool:
    """True if a Markdown table in this file carries at least one data row."""
    rows = 0
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or all(set(c) <= set("-: ") for c in cells):
            continue                      # separator row
        if cells[0].lower() in ("#", "dimension", "sub-question", "claim"):
            continue                      # header row
        if any(c and not c.startswith("<") for c in cells):
            rows += 1
    return rows > 0


def check(run: Path, ship: bool) -> int:
    if not run.is_dir():
        sys.stderr.write(f"no such run: {run}\n")
        return 1
    if runmeta.meta(run)["kind"] == "compose":
        return check_compose(run, ship)

    def text(name):
        p = run / name
        return p.read_text() if p.is_file() else None

    stages, missing = [], []

    def stage(label, ok, detail, blocking=True):
        stages.append((label, ok, detail))
        if not ok and blocking:
            missing.append(label)

    prompt = text("prompt.md")
    stage("prompt", bool(prompt and len(prompt.split()) > 5),
          "the request, verbatim" if prompt else "not written")

    brief = text("brief.md")
    stage("brief", bool(brief and not TEMPLATE.search(brief or "")),
          "question, sub-questions, scope" if brief else "not written")

    voice = text("voice.md")
    stage("voice", bool(voice),
          "narration mode recorded" if voice else "mode never decided")

    cov = text("coverage.md")
    if cov is None:
        stage("coverage", False, "not written")
    elif not has_rows(cov):
        stage("coverage", False, "scaffolded template, never filled: "
                                 "the gap hunt and coverage audit did not run")
    else:
        stage("coverage", True, "sub-questions and dimensions have a status")

    ev = run / "evidence.jsonl"
    n_ev = 0
    if ev.is_file():
        for line in ev.read_text().splitlines():
            if line.strip():
                try:
                    json.loads(line)
                    n_ev += 1
                except json.JSONDecodeError:
                    pass
    stage("evidence", n_ev > 0, f"{n_ev} row(s)")

    notes = list((run / "notes").glob("*.md")) if (run / "notes").is_dir() else []
    stage("notes", bool(notes), f"{len(notes)} scout note file(s)", blocking=False)

    report = text("report.md")
    stage("report", bool(report),
          f"{len((report or '').split())} words" if report
          else "draft never promoted to report.md")

    ver = [p.name for p in run.glob("verification*.md")]
    stage("verify", bool(ver), ", ".join(ver) if ver else "sources never re-checked")

    crit = [p.name for p in run.glob("critique*.md")]
    stage("critique", bool(crit), ", ".join(crit) if crit
          else "reasoning never attacked")

    rep = [p.name for p in run.glob("repair-log*.md")]
    stage("repair", bool(rep), ", ".join(rep) if rep
          else "findings never dispositioned")

    width = max(len(s[0]) for s in stages)
    print(f"run: {run}")
    for label, ok, detail in stages:
        print(f"  {'ok ' if ok else 'MISSING'.ljust(3)} {label.ljust(width)}  {detail}")

    if not ship:
        return 0
    if missing:
        print(f"\nNOT SHIPPABLE: {len(missing)} stage(s) never ran: "
              f"{', '.join(missing)}")
        print("A stage that was deliberately skipped is recorded as a decision "
              "in the run, not left as an empty template.")
        return 1
    print("\nEvery stage has its artefact. Run gate.py on report.md before handover.")
    return 0


def check_compose(run: Path, ship: bool) -> int:
    """A written piece is shippable on different evidence from a report.

    There is no coverage table and no scout evidence: a cover letter answers a
    posting, not a research question. What has to exist is the request, the
    context the piece was written against, the piece itself, and a review round
    somebody other than the drafting thread ran.
    """
    m = runmeta.meta(run)

    def text(name):
        p = run / name
        return p.read_text() if p.is_file() else None

    stages, missing = [], []

    def stage(label, ok, detail, blocking=True):
        stages.append((label, ok, detail))
        if not ok and blocking:
            missing.append(label)

    prompt = text("prompt.md")
    stage("prompt", bool(prompt and len(prompt.split()) > 5),
          "the request, verbatim" if prompt else "not written")

    # context.md keeps its constraints table when filled, so the research
    # TEMPLATE pattern would condemn a good file. Judge it on the angle-bracket
    # prompts instead: those only survive in a file nobody filled in.
    ctx = text("context.md")
    stage("context", bool(ctx and not COMPOSE_TEMPLATE.search(ctx)),
          "reader, purpose, line, constraints" if ctx
          else "scaffolded template, never filled: the piece was written "
               "without deciding who reads it")

    doc = runmeta.primary(run)
    body = doc.read_text() if doc else None
    stage("piece", bool(body and len(body.split()) > 20),
          f"{doc.name}, {len((body or '').split())} words" if doc
          else f"no master document ({', '.join(m['masters'])})")

    rev = [p.name for p in run.glob("review*.md")] + \
          [p.name for p in run.glob("critique*.md")]
    stage("review", bool(rev), ", ".join(rev) if rev
          else "never read by anyone but the thread that wrote it")

    ver = [p.name for p in run.glob("verification*.md")]
    stage("verify", bool(ver), ", ".join(ver) if ver
          else "no claims were checked (only needed if the piece asserts "
               "facts about the world)", blocking=False)

    width = max(len(s[0]) for s in stages)
    print(f"run: {run}   kind: compose · {m['doc_kind']}")
    for label, ok, detail in stages:
        print(f"  {'ok ' if ok else 'MISSING'.ljust(3)} {label.ljust(width)}  {detail}")

    if not ship:
        return 0
    if missing:
        print(f"\nNOT SHIPPABLE: {len(missing)} stage(s) never ran: "
              f"{', '.join(missing)}")
        return 1
    print(f"\nEvery stage has its artefact. Run gate.py on {doc} before handover.")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        sys.exit(__doc__)
    sys.exit(check(Path(args[0]), "--ship" in sys.argv))
