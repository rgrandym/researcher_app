#!/usr/bin/env python3
"""kb.py — what the workspace already knows, across every run.

    kb.py search "<terms>" [--limit 20] [--run SLUG]   # evidence rows that match
    kb.py runs   "<question or terms>" [--limit 5]     # runs whose brief overlaps

`search` reads every run's evidence.jsonl and ranks rows by how many of the terms
appear in the claim, quote, title and publisher. Each hit names its run, ID, access
date and URL, so a brief can say "already established: E812 in <run>" and a scout
can be told to look only for what is missing. A row from another run is a lead
until it is cited in this one: copy it into this run's ledger with a new ID and the
same URL and quote (the library still holds the page), and check its date.

`runs` compares a question with each run's prompt.md and brief.md, and is what
`/research` consults before scaffolding: an existing report on the same ground is
usually better extended (`/expand`) than started again.

It makes no model call and writes nothing.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs"
STOP = set("""a an and are as at be by for from has have how in is it its of on or that
the their this to was were what when where which who why will with does do did can
could should would much many more most than into about over per vs versus""".split())


def terms(text):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9\-\.]+", text.lower())
            if w not in STOP and len(w) > 2]


def evidence(run_filter=None):
    for ledger in sorted(OUTPUTS.glob("*/evidence.jsonl")):
        run = ledger.parent.name
        if run_filter and run_filter not in run:
            continue
        for line in ledger.read_text(errors="ignore").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            yield run, row


def search(query, limit, run_filter):
    words = terms(query)
    if not words:
        print("no usable terms", file=sys.stderr)
        return 1
    hits = []
    for run, row in evidence(run_filter):
        hay = " ".join(str(row.get(k, "")) for k in ("claim", "quote", "title", "publisher")).lower()
        found = [w for w in words if w in hay]
        if len(found) >= max(1, (len(words) + 1) // 2):
            hits.append((len(found), sum(hay.count(w) for w in found), run, row))
    hits.sort(key=lambda h: (-h[0], -h[1], h[2]))
    for n, _, run, row in hits[:limit]:
        claim = re.sub(r"\s+", " ", str(row.get("claim", "")))[:160]
        print(f"{run}  {row.get('id', '?'):6} {row.get('accessed', '')[:10]}  "
              f"[{row.get('type', '')}{', ' + row['admiralty'] if row.get('admiralty') else ''}]  {claim}")
        print(f"{'':12}{row.get('url', '')}")
    if len(hits) > limit:
        print(f"… {len(hits) - limit} more; narrow the terms or pass --run")
    return 0 if hits else 1


def runs(query, limit):
    words = set(terms(query))
    if not words:
        return 1
    scored = []
    for folder in sorted(p for p in OUTPUTS.iterdir() if p.is_dir()):
        text = " ".join((folder / f).read_text(errors="ignore")
                        for f in ("prompt.md", "brief.md") if (folder / f).exists())
        if not text:
            continue
        have = set(terms(text))
        shared = words & have
        if shared:
            score = len(shared) / len(words)
            scored.append((score, folder.name, sorted(shared)))
    scored.sort(key=lambda s: -s[0])
    for score, name, shared in scored[:limit]:
        rows = sum(1 for _ in (OUTPUTS / name / "evidence.jsonl").open()) \
            if (OUTPUTS / name / "evidence.jsonl").exists() else 0
        print(f"{score:4.0%}  {name}  ({rows} evidence rows)  shares: {', '.join(shared[:12])}")
    return 0 if scored else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--run")
    p = sub.add_parser("runs")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()
    if args.cmd == "search":
        return search(args.query, args.limit, args.run)
    return runs(args.query, args.limit)


if __name__ == "__main__":
    sys.exit(main())
