#!/usr/bin/env python3
"""Mechanical citation and cleanliness audit for a run directory.

Catches, without spending model tokens, the failures that are pure bookkeeping:
dangling [E#] refs, malformed/duplicate evidence rows, unsourced paragraphs,
unused evidence, duplicate fetches, and agent artifacts left in the document.

    python3 .claude/scripts/audit_citations.py outputs/<slug> [draft.md]

Exit 1 if any ERROR-level problem is found.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biblio  # noqa: E402
import runmeta  # noqa: E402

REQUIRED = ("id", "claim", "quote", "url", "accessed", "type")
CITE = re.compile(r"\[(E\d+)\]")
UNVERIFIED = re.compile(r"\[UNVERIFIED\]|\bsuggests\b|\blikely\b|\bappears to\b", re.I)
FIGURE = re.compile(r"^```figure[ \t]*\n.*?^```[ \t]*$", re.S | re.M)
NEEDS = re.compile(r"\[NEEDS DATA(?:\s*—\s*([^\]]*))?\]")
SOURCE_ENTRY = re.compile(r"^\s*[-*]?\s*\**\[(E\d+)\]", re.M)   # one line per source entry

# Agent artifacts: pipeline scaffolding that must never reach the reader.
# These are ERRORs — a document containing them is not shippable.
ARTIFACTS = [
    (r"^#{1,6}\s*Round\s+\d", "round-shaped heading (extensions reconcile, never append)"),
    (r"\[(?:BLOCKING|MATERIAL|MINOR)\]", "critique severity tag"),
    (r"^\s*(?:VERDICT|CHECKED|FINDINGS|CONTRADICTIONS|NOT FOUND|SOURCE QUALITY)\s*:?\s*$", "subagent return-format block"),
    (r"\b(?:sub-?agent|scout|digest|verification\.md|coverage\.md|evidence\.jsonl|critique\.md|repair-log\.md|draft\.md)\b", "internal pipeline reference"),
    (r"\b(?:TODO|FIXME|XXX|placeholder text|<[a-z ]+here>)\b", "unfinished scaffold"),
    (r"\bas an AI\b|\bI (?:searched|looked|found|will now|should note)\b|\bmy (?:analysis|research) (?:showed|found)\b", "agent self-reference"),
    (r"\b(?:Great question|Let'?s dive|Let'?s (?:take a look|explore)|Here'?s what I found|I hope this helps)\b", "chat voice"),
]

# Slop: register violations. WARN — a human decides, but they are almost always cuts.
SLOP = [
    r"\bIn conclusion\b", r"\bIt (?:is|'s) (?:important|worth) (?:to )?not(?:e|ing)\b",
    r"\bAs (?:noted|discussed|mentioned) (?:above|earlier|previously)\b",
    r"\bThis (?:section|report|document) (?:will|aims to|examines)\b",
    r"\bIn today'?s\b", r"\bdelve into\b", r"\bunderscore[sd]?\b", r"\blandscape of\b",
    r"\bplays? a (?:crucial|key|vital|pivotal) role\b", r"\bserves? as a testament\b",
    r"\bNot only\b.{0,40}\bbut also\b",
]


def split_sources(text):
    """(body, reference list). The list is a bibliography, not prose that cites.

    Its heading depends on the citation system: Sources, Works Cited,
    References or Bibliography. See biblio.py.
    """
    return biblio.split_body(text)


def scan_artifacts(text, name):
    """Find pipeline scaffolding and register slop in a document body."""
    found = []
    # Scan the author's own prose only. Excluded, because their wording is not ours:
    # figure JSON (note/data_gaps discuss sourcing), block quotes (verbatim), and the
    # Sources list (titles are copied exactly and often contain slop words).
    body = FIGURE.sub("", text)
    body = biblio.split_body(body)[0]
    body = "\n".join("" if ln.lstrip().startswith(">") else ln for ln in body.splitlines())
    for pattern, why in ARTIFACTS:
        for m in re.finditer(pattern, body, re.I | re.M):
            line = body[: m.start()].count("\n") + 1
            found.append(f"ERROR {name}:{line} agent artifact — {why}: {m.group(0)[:50]!r}")
    for pattern in SLOP:
        for m in re.finditer(pattern, body, re.I):
            line = body[: m.start()].count("\n") + 1
            found.append(f"WARN  {name}:{line} slop phrase: {m.group(0)[:50]!r}")
    return found


def load_evidence(path):
    rows, errors = {}, []
    if not path.exists():
        return rows, [f"ERROR missing {path}"]
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"ERROR {path.name}:{n} invalid JSON ({e.msg})")
            continue
        missing = [f for f in REQUIRED if not row.get(f)]
        if missing:
            errors.append(f"ERROR {path.name}:{n} [{row.get('id','?')}] missing: {', '.join(missing)}")
        rid = row.get("id")
        if rid in rows:
            errors.append(f"ERROR {path.name}:{n} duplicate evidence id {rid}")
        if rid:
            rows[rid] = row
    return rows, errors


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run = Path(sys.argv[1])
    draft = run / (sys.argv[2] if len(sys.argv) > 2 else "draft.md")
    # A written piece cites nothing in its text on purpose: a cover letter that
    # says (Smith 2024) is not a cover letter. Its evidence rows back the
    # author's statements in the ledger and in chat, so the two checks that
    # assume a report (every paragraph cites, every row is used) are off here.
    compose = runmeta.meta(run)["kind"] == "compose"

    rows, problems = load_evidence(run / "evidence.jsonl")

    # duplicate fetches of the same URL
    for url, c in Counter(r.get("url") for r in rows.values()).items():
        if c > 1 and url:
            problems.append(f"WARN url fetched/recorded {c}x: {url}")

    # single-origin risk: many claims, few distinct domains
    domains = Counter(re.sub(r"^https?://([^/]+).*", r"\1", r.get("url", "")) for r in rows.values())
    if rows and len(domains) <= 2:
        problems.append(f"WARN all {len(rows)} evidence rows come from {len(domains)} domain(s): {', '.join(domains)}")

    if draft.exists():
        text = draft.read_text()
        body, sources = split_sources(text)
        # what the prose and the figure specs actually cite — NOT counting the
        # Sources list itself, or every listed entry would vouch for its own use
        cited = set(CITE.findall(body))
        listed = set(SOURCE_ENTRY.findall(sources))

        if sources.strip():
            # a citation deleted from the text leaves its entry stranded in the list
            for ref in sorted(listed - cited, key=lambda s: int(s[1:])):
                problems.append(f"ERROR {draft.name} [{ref}] is listed in ## Sources but no longer "
                                f"cited anywhere in the body — remove the entry (its evidence.jsonl "
                                f"row stays; evidence IDs are never renumbered)")
            for ref in sorted(cited - listed, key=lambda s: int(s[1:])):
                problems.append(f"ERROR {draft.name} cites {ref} but it has no entry in ## Sources")
        elif cited:
            problems.append(f"ERROR {draft.name} cites {len(cited)} evidence ID(s) but has no "
                            f"## Sources section")

        # placeholders are deliberate, but each must say what is missing and where
        holes = NEEDS.findall(text)
        for pointer in holes:
            if "·" not in pointer:
                problems.append(f"WARN  {draft.name} [NEEDS DATA] with no "
                                f"'what · where' pointer: {(pointer or '(bare)')[:50]}")
        if holes and "Data still to obtain" not in text:
            problems.append(f"ERROR {draft.name} has {len(holes)} [NEEDS DATA] "
                            f"placeholder(s) but no '## Data still to obtain' section")
        for ref in sorted((cited | listed) - set(rows), key=lambda s: int(s[1:])):
            problems.append(f"ERROR {draft.name} cites {ref} with no row in evidence.jsonl (fabricated citation?)")
        for ref in sorted(set(rows) - cited, key=lambda s: int(s[1:])):
            if not compose:
                problems.append(f"INFO  {ref} gathered but unused")

        problems += scan_artifacts(text, draft.name)

        # paragraphs of prose carrying no citation and no hedge marker
        # (figure blocks are data, not prose — their citations live in `source`)
        for para in [p.strip() for p in FIGURE.sub("", text).split("\n\n")]:
            if compose:
                break
            if len(para) < 120 or para.startswith(("#", "|", "```", ">", "-", "*")):
                continue
            if not CITE.search(para) and not UNVERIFIED.search(para):
                problems.append(f"WARN unsourced paragraph: {para[:70]}…")
    else:
        problems.append(f"INFO no draft at {draft}")

    for p in sorted(problems, key=lambda s: {"ERROR": 0, "WARN": 1, "INFO": 2}[s.split()[0]]):
        print(p)

    errs = sum(p.startswith("ERROR") for p in problems)
    arts = sum("agent artifact" in p for p in problems)
    holes = len(NEEDS.findall(draft.read_text())) if draft.exists() else 0
    print(f"\n{len(rows)} evidence rows · {len(domains)} domains · "
          f"{holes} data placeholders · {arts} agent artifacts · {errs} errors")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
