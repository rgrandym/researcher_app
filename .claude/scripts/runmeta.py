#!/usr/bin/env python3
"""runmeta.py: what kind of run this is, and which documents are its masters.

    python3 .claude/scripts/runmeta.py <run>              # print the metadata
    python3 .claude/scripts/runmeta.py <run> --masters    # one path per line
    python3 .claude/scripts/runmeta.py <run> --kind       # research

Which documents are a run's masters, read in one place so every script follows
the same answer rather than matching on filenames. A run with no `.run.json` (the
normal case) is a research run whose masters are report.md and draft.md; a
`.run.json` can name other masters:

    {"kind": "research", "masters": ["report.md", "draft.md"]}

A revision run adds one master per supplied document it revises in Markdown, named in
`documents` (written by document.py start, never by hand):

    {"documents": [{"slug": "business-plan", "master": "business-plan.md"}]}

    python3 .claude/scripts/runmeta.py <run> --documents  # slug and master, one per line
"""
import json
import sys
from pathlib import Path

RESEARCH_MASTERS = ["report.md", "draft.md"]
DEFAULT = {"kind": "research", "doc_kind": "report", "masters": RESEARCH_MASTERS}


def meta(run) -> dict:
    """The run's metadata, with defaults filled in. Never raises."""
    run = Path(run)
    out = dict(DEFAULT)
    path = run / ".run.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                out.update({k: v for k, v in data.items() if v})
        except (json.JSONDecodeError, ValueError, OSError):
            pass                     # a corrupt file must not break the gates
    masters = list(out.get("masters") or RESEARCH_MASTERS)
    docs = [d for d in out.get("documents") or [] if isinstance(d, dict) and d.get("master")]
    out["documents"] = docs
    masters += [d["master"] for d in docs if d["master"] not in masters]
    out["masters"] = [m for m in masters if isinstance(m, str) and m.endswith(".md")]
    return out


def document(doc):
    """The `documents` entry for a revised-document master, or None for a report."""
    doc = Path(doc)
    return next((d for d in meta(doc.parent)["documents"] if d["master"] == doc.name), None)


def masters(run) -> list:
    """Master filenames for this run, existing ones first."""
    run = Path(run)
    names = meta(run)["masters"]
    return sorted(names, key=lambda n: not (run / n).is_file())


def is_master(doc) -> bool:
    """True if this path is a master document of the run that contains it."""
    doc = Path(doc)
    return doc.name in meta(doc.parent)["masters"]


def primary(run):
    """The document a round should act on: the first master that exists."""
    run = Path(run)
    for name in masters(run):
        if (run / name).is_file():
            return run / name
    return None


def write(run, kind, doc_kind, masters_, created=None):
    """Record the metadata. Called by the scaffolds, not by hand."""
    run = Path(run)
    data = {"kind": kind, "doc_kind": doc_kind, "masters": list(masters_)}
    if created:
        data["created"] = created
    (run / ".run.json").write_text(json.dumps(data, indent=2) + "\n")
    return data


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        sys.stderr.write(__doc__)
        return 2
    run = Path(args[0])
    if not run.is_dir():
        sys.stderr.write(f"no such run: {run}\n")
        return 1
    m = meta(run)
    if "--kind" in sys.argv:
        print(m["kind"])
    elif "--documents" in sys.argv:
        for d in m["documents"]:
            print(f"{d['slug']}\t{run / d['master']}")
    elif "--masters" in sys.argv:
        for name in masters(run):
            print(run / name)
    else:
        print(json.dumps(m, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
