#!/usr/bin/env python3
"""wanted.py — the register of sources that could not be read, and the list the
author works from to fetch them by hand.

A page behind a paywall is a finding, and the report says so with a visible
placeholder. What the report cannot do is hand the author a way to close the
hole: the placeholder names what is missing and where a person would get it,
but not the exact URL that failed or why it failed. Without those two the
author cannot go and fetch the document, which is the one move that actually
closes an access-restricted gap.

    python3 .claude/scripts/wanted.py add <run> --wanted "…" --url "…" \\
        --reason "…" --kind access-restricted [--context "…"] [--section "§3"]
    python3 .claude/scripts/wanted.py build <run>    # write external_data/WANTED.md
    python3 .claude/scripts/wanted.py check <run>    # what is still open

Rows live in `<run>/blocked.jsonl`, append-only, one JSON object per line, and
never in evidence.jsonl: a source nobody could read backs no claim. `build`
turns them into `<run>/external_data/WANTED.md`, a checklist the author works
down. When they save a document into `<run>/external_data/`, the next
`external_index.py scan` reports it as unread and an agent mines it, and the
matching row is closed with `--resolves`.

The three kinds are the ones in .claude/references/gaps.md, and the distinction
is load-bearing:

    access-restricted   the author can get it: an account, a purchase, a call
    unpublished         nobody has it in public form; asking will not help
    not-searched        the run ran out of budget, and says so plainly

Recording a not-searched hole as access-restricted dresses a budget decision as
an epistemic limit, so `kind` is required and never guessed.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

KINDS = ("access-restricted", "unpublished", "not-searched")


def rows(run: Path):
    f = run / "blocked.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def add(a):
    run = Path(a.run)
    if not run.is_dir():
        sys.exit(f"no such run: {run}")
    existing = rows(run)
    for r in existing:
        if r.get("url") == a.url and r.get("status") != "resolved":
            print(f"already registered as {r['id']}: {r['wanted']}")
            return 0
    row = {
        "id": f"B{len(existing) + 1}",
        "wanted": a.wanted,
        "url": a.url,
        "reason": a.reason,
        "kind": a.kind,
        "context": a.context or "",
        "section": a.section or "",
        "tried": date.today().isoformat(),
        "status": "open",
    }
    with (run / "blocked.jsonl").open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{row['id']} registered: {row['wanted']}")
    return 0


def resolve(a):
    run = Path(a.run)
    all_rows = rows(run)
    hit = False
    for r in all_rows:
        if r["id"] == a.id:
            r["status"] = "resolved"
            r["resolved_by"] = a.by or "supplied by the author"
            r["resolved"] = date.today().isoformat()
            hit = True
    if not hit:
        sys.exit(f"no such row: {a.id}")
    (run / "blocked.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in all_rows))
    print(f"{a.id} closed")
    return 0


def build(a):
    run = Path(a.run)
    open_rows = [r for r in rows(run) if r.get("status") != "resolved"]
    ext = run / "external_data"
    ext.mkdir(parents=True, exist_ok=True)
    out = ext / "WANTED.md"

    if not open_rows:
        out.write_text("# Sources still wanted\n\n"
                       "Nothing outstanding: every source this run could not "
                       "read has been supplied or closed.\n")
        print(f"{out}: nothing outstanding")
        return 0

    lines = ["# Sources still wanted", "",
             "Documents this run could not read. Each one names the exact page "
             "that failed and why, so it can be fetched by hand.", "",
             "Save what you retrieve anywhere under this `external_data/` "
             "folder, in any format. The next run of "
             "`external_index.py scan` reports it as unread and an agent mines "
             "it into evidence; nothing needs renaming.", ""]

    by_kind = {}
    for r in open_rows:
        by_kind.setdefault(r.get("kind", "access-restricted"), []).append(r)

    heads = {
        "access-restricted": ("Retrievable", "Behind a paywall, a login, or an "
                              "account. These are the ones worth your time."),
        "unpublished": ("Not published anywhere", "No public form of this "
                        "figure was found. Fetching is unlikely to help; it is "
                        "listed so the hole is visible."),
        "not-searched": ("Not searched", "The run did not get to these. They "
                         "are open questions, not dead ends."),
    }
    for kind in KINDS:
        group = by_kind.get(kind)
        if not group:
            continue
        title, gloss = heads[kind]
        lines += [f"## {title}", "", gloss, ""]
        for r in group:
            lines.append(f"### {r['id']} · {r['wanted']}")
            lines.append("")
            lines.append(f"- **URL:** {r['url']}")
            lines.append(f"- **Why it failed:** {r['reason']}")
            if r.get("section"):
                lines.append(f"- **Needed by:** {r['section']}")
            if r.get("context"):
                lines.append(f"- **What is already known:** {r['context']}")
            lines.append(f"- **Last tried:** {r.get('tried', 'unrecorded')}")
            lines.append("")
    out.write_text("\n".join(lines))
    print(f"{out}: {len(open_rows)} source(s) wanted")
    return 0


def check(a):
    run = Path(a.run)
    all_rows = rows(run)
    if not all_rows:
        print("no blocked sources registered for this run")
        return 0
    open_rows = [r for r in all_rows if r.get("status") != "resolved"]
    for r in all_rows:
        mark = "open " if r.get("status") != "resolved" else "closed"
        print(f"  {mark} {r['id']:<5} [{r.get('kind','?')}] {r['wanted']}")
        print(f"        {r['url']}")
    print(f"\n{len(all_rows)} registered · {len(open_rows)} still open")

    # A row with no URL cannot be acted on, which defeats the point.
    bad = [r for r in open_rows if not r.get("url") or not r.get("reason")]
    if bad:
        print(f"\n{len(bad)} row(s) missing a URL or a reason: "
              f"{', '.join(r['id'] for r in bad)}")
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="register a source that could not be read")
    p.add_argument("run")
    p.add_argument("--wanted", required=True, help="the figure or fact you were after")
    p.add_argument("--url", required=True, help="the exact page that failed")
    p.add_argument("--reason", required=True, help="why it could not be read")
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--context", help="what you did establish around it")
    p.add_argument("--section", help="where the report needs it")
    p.set_defaults(fn=add)

    p = sub.add_parser("resolve", help="close a row the author has supplied")
    p.add_argument("run")
    p.add_argument("id")
    p.add_argument("--by", help="what closed it")
    p.set_defaults(fn=resolve)

    p = sub.add_parser("build", help="write external_data/WANTED.md")
    p.add_argument("run")
    p.set_defaults(fn=build)

    p = sub.add_parser("check", help="list registered rows and their state")
    p.add_argument("run")
    p.set_defaults(fn=check)

    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
