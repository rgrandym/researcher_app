#!/usr/bin/env python3
"""Index of user-supplied sources in a run's `external_data/` folder.

The author drops files into `<run>/external_data/` by hand: datasheets, PDFs
they bought or were sent, spreadsheets, scans, internal memos. Those are
sources, and they are read exactly like a fetched page: verbatim extract into
`notes/`, structured row into `evidence.jsonl`.

The problem this solves is re-reading. A run with forty PDFs in it cannot have
an agent open all forty on every round, and an agent has no way to remember
which ones it already mined. This keeps a content-hash index, so `scan` answers
one question cheaply and exactly: **which files has nobody read yet?**

    external_index.py scan     <run> [--json]   # NEW / CHANGED / INDEXED / MISSING
    external_index.py status   <run>            # one-line summary
    external_index.py register <run> <file> --evidence E900-E907 --notes notes/x.md
                                                [--summary "..."] [--nothing-usable]
    external_index.py show     <run> <file>

Files under `ai_reports/` are model output, not documents from real sources.
They are LEADS: read them for the claims and pointers they contain, then source
every claim independently. `register` refuses `--evidence` for them, so an
AI-written assertion cannot become an evidence row by accident.

`scan` exits 2 when there is unread material, so a pipeline stage can branch on
it. `register` is what marks a file read; nothing else writes the index.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path, PurePath

INDEX_NAME = ".index.json"
# Subfolders whose contents are model output rather than documents from real
# sources. Everything under here is a LEAD: read it for the claims and pointers
# it contains, then source those claims independently. A fact never enters
# evidence.jsonl on the authority of a file in one of these folders.
AI_DIRS = {"ai_reports"}
# WANTED.md is this workspace's own output, the list of sources it could not
# read. It is written into external_data/ so the author finds it beside the
# files they are being asked for, and it is never a supplied source itself.
SKIP_NAMES = {".DS_Store", "Thumbs.db", INDEX_NAME, "README.md", "WANTED.md"}
TEXTLIKE = {".md", ".txt", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".html", ".htm"}
READABLE = TEXTLIKE | {".pdf", ".docx", ".xlsx", ".pptx", ".rtf", ".odt"}
IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".heic"}


def ext_dir(run):
    """The folder of supplied files this index covers.

    A research run keeps them in `external_data/`; a compose run keeps the
    brief for one piece in `source_material/`; the standing dossier of the
    author's own record is itself a folder of files and is scanned directly.
    Falling back to the argument only when it holds no prompt.md keeps this
    from ever indexing a run folder whole.
    """
    run = Path(run)
    for name in ("external_data", "source_material"):
        if (run / name).is_dir():
            return run / name
    if not (run / "prompt.md").exists():
        return run
    return run / "external_data"


def index_path(run):
    return ext_dir(run) / INDEX_NAME


def load_index(run):
    p = index_path(run)
    if not p.exists():
        return {"version": 1, "files": {}}
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR {p} is not valid JSON ({e.msg}). Fix or delete it; "
                 f"deleting only costs a re-read of the files.")
    data.setdefault("files", {})
    return data


def save_index(run, data):
    p = index_path(run)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pdf_pages(path):
    """Best-effort page count without a PDF dependency.

    Reads the /Count of the page tree, falling back to counting /Type /Page.
    Returns None when the file uses object streams that hide both, which is
    common enough that a missing count is not an error.
    """
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    counts = [int(m) for m in re.findall(rb"/Count\s+(\d+)", blob)]
    if counts:
        return max(counts)
    n = len(re.findall(rb"/Type\s*/Page[^s]", blob))
    return n or None


def is_ai_generated(rel):
    """True when the file sits under a folder reserved for model output."""
    parts = PurePath(str(rel)).parts
    return bool(parts) and parts[0] in AI_DIRS


def describe(path, rel=None):
    suf = path.suffix.lower()
    meta = {"size": path.stat().st_size, "ext": suf}
    if suf == ".pdf":
        meta["pages"] = pdf_pages(path)
    elif suf in TEXTLIKE:
        try:
            meta["lines"] = sum(1 for _ in path.open("r", errors="replace"))
        except OSError:
            pass
    if rel is not None and is_ai_generated(rel):
        meta["kind"] = "ai_generated"
    elif suf in IMAGE:
        meta["kind"] = "image"
    elif suf in READABLE:
        meta["kind"] = "document"
    else:
        meta["kind"] = "other"
    return meta


def walk(run):
    root = ext_dir(run)
    if not root.exists():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_dir() or p.name in SKIP_NAMES or p.name.startswith("."):
            continue
        out.append(p)
    return out


def scan(run, as_json=False):
    root = ext_dir(run)
    if not root.exists():
        print(f"nothing to index under {run} (no files supplied by hand)")
        return 0
    idx = load_index(run)
    files = idx["files"]
    seen, rows = set(), []
    for p in walk(run):
        rel = str(p.relative_to(root))
        seen.add(rel)
        digest = sha256(p)
        rec = files.get(rel)
        if rec is None:
            state = "NEW"
        elif rec.get("sha256") != digest:
            state = "CHANGED"
        else:
            state = "INDEXED"
        rows.append({"file": rel, "state": state, "sha256": digest[:12],
                     **describe(p, rel),
                     "evidence": (rec or {}).get("evidence", []),
                     "leads": (rec or {}).get("leads"),
                     "notes": (rec or {}).get("notes")})
    for rel in sorted(set(files) - seen):
        rows.append({"file": rel, "state": "MISSING", "evidence": files[rel].get("evidence", [])})

    if as_json:
        print(json.dumps(rows, indent=2))
    else:
        order = {"NEW": 0, "CHANGED": 1, "MISSING": 2, "INDEXED": 3}
        for r in sorted(rows, key=lambda r: (order[r["state"]], r["file"])):
            bits = []
            if r.get("pages"):
                bits.append(f"{r['pages']}p")
            if r.get("lines"):
                bits.append(f"{r['lines']} lines")
            if r.get("size"):
                bits.append(f"{r['size'] // 1024}KB")
            if r.get("evidence"):
                ev = r["evidence"]
                bits.append(f"{ev[0]}–{ev[-1]}" if len(ev) > 1 else ev[0])
            if r.get("leads") is not None:
                bits.append(f"{r['leads']} leads")
            tag = "  [AI: leads only, verify independently]" \
                if r.get("kind") == "ai_generated" else ""
            print(f"{r['state']:<8} {r['file']}"
                  + (f"  ({', '.join(bits)})" if bits else "") + tag)

    pending = [r for r in rows if r["state"] in ("NEW", "CHANGED")]
    unreadable = [r for r in pending if r.get("kind") == "other"]
    print(f"\n{len(rows)} file(s) · {len(pending)} unread · "
          f"{sum(1 for r in rows if r['state'] == 'INDEXED')} already mined · "
          f"{sum(1 for r in rows if r['state'] == 'MISSING')} missing")
    ai_pending = [r for r in pending if r.get("kind") == "ai_generated"]
    if unreadable:
        print(f"note: {len(unreadable)} unread file(s) are of a type this workspace "
              f"cannot open directly; ask the author what they contain.")
    if ai_pending:
        print(f"note: {len(ai_pending)} unread file(s) are under "
              f"{'/, '.join(sorted(AI_DIRS))}/ and are AI-generated. They are LEADS, "
              f"not sources: mine them for claims and pointers, then source every "
              f"claim independently. `register` refuses --evidence for them.")
    if pending:
        print("read only the unread files, then `register` each one.")
    return 2 if pending else 0


def status(run):
    idx = load_index(run)
    files = walk(run)
    known = idx["files"]
    ev = sorted({e for r in known.values() for e in r.get("evidence", [])},
                key=lambda s: int(s[1:]) if s[1:].isdigit() else 0)
    print(f"external_data: {len(files)} file(s) present, {len(known)} indexed, "
          f"{len(ev)} evidence row(s) derived")
    if ev:
        print(f"evidence from user-supplied sources: {ev[0]}–{ev[-1]}")
    return 0


def expand_range(spec):
    """'E900-E907,E910' → ['E900', …, 'E907', 'E910']."""
    out = []
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"E(\d+)\s*[-–]\s*E?(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if b < a:
                sys.exit(f"ERROR bad range {part}")
            out += [f"E{i}" for i in range(a, b + 1)]
        elif re.fullmatch(r"E\d+", part):
            out.append(part)
        else:
            sys.exit(f"ERROR not an evidence id or range: {part!r}")
    return out


def register(run, target, evidence, notes, summary, nothing_usable,
             leads=None, about_document=False):
    root = ext_dir(run)
    p = Path(target)
    if not p.exists():
        p = root / target
    if not p.exists():
        sys.exit(f"ERROR no such file: {target}")
    rel = str(p.resolve().relative_to(root.resolve()))
    ids = expand_range(evidence) if evidence else []
    ai = is_ai_generated(rel)

    if ai and ids and not about_document:
        sys.exit(
            f"ERROR {rel} is under {PurePath(rel).parts[0]}/ and is AI-generated "
            f"content. It is a LEAD, not a source: a fact never enters "
            f"evidence.jsonl on its authority.\n"
            f"  Mine it for claims and pointers, source each claim independently "
            f"from a real document, then register this file with:\n"
            f"    --leads N --notes notes/<file>.md\n"
            f"  The only evidence row it may back is one making a statement *about "
            f"the document itself*, and that needs --about-document.")
    if ai and leads is None and not nothing_usable and not about_document:
        sys.exit(f"ERROR {rel} is AI-generated. Register it with --leads N (how many "
                 f"claims you extracted for independent sourcing) and --notes, or "
                 f"--nothing-usable if it yielded none.")
    if not ai and (leads is not None or about_document):
        sys.exit(f"ERROR --leads/--about-document apply only to files under "
                 f"{'/, '.join(sorted(AI_DIRS))}/. {rel} is a real document; give it "
                 f"--evidence or --nothing-usable.")
    if not ids and not nothing_usable and leads is None:
        sys.exit("ERROR give --evidence E900-E905, or --nothing-usable if the file "
                 "held no citable fact. Registering a file with neither would mark "
                 "it read while leaving no trace of what it said.")
    if ids:
        ledger = Path(run) / "evidence.jsonl"
        if ledger.exists():
            have = {json.loads(l)["id"] for l in ledger.read_text().splitlines() if l.strip()}
            missing = [i for i in ids if i not in have]
            if missing:
                sys.exit(f"ERROR these ids are not in evidence.jsonl yet: "
                         f"{', '.join(missing[:8])}. Write the rows first, then register.")
    idx = load_index(run)
    rec = {
        "sha256": sha256(p),
        "size": p.stat().st_size,
        "indexed": date.today().isoformat(),
        "evidence": ids,
        "notes": notes,
        "summary": summary or ("no citable content" if nothing_usable else ""),
        **{k: v for k, v in describe(p, rel).items() if k in ("pages", "lines", "kind")},
    }
    if ai:
        rec["leads"] = leads or 0
        rec["verification"] = "required: claims must be sourced independently"
        if ids:
            rec["evidence_scope"] = "about the document itself, not about the world"
    idx["files"][rel] = rec
    save_index(run, idx)
    tail = f" · {len(ids)} evidence row(s)" if ids else ""
    if ai:
        tail += f" · {leads or 0} lead(s) for independent sourcing"
    print(f"registered {rel}{tail}" + (f" · {notes}" if notes else ""))
    return 0


def show(run, target):
    idx = load_index(run)
    root = ext_dir(run)
    p = Path(target)
    rel = str((p if p.exists() else root / target).resolve().relative_to(root.resolve()))
    rec = idx["files"].get(rel)
    if not rec:
        print(f"{rel}: not indexed")
        return 1
    print(json.dumps({rel: rec}, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["scan", "status", "register", "show"])
    ap.add_argument("run")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--evidence", help="ids or ranges written from this file, e.g. E900-E907")
    ap.add_argument("--notes", help="notes file holding the verbatim extracts")
    ap.add_argument("--summary", help="one line: what this file is and what it gave")
    ap.add_argument("--nothing-usable", action="store_true",
                    help="the file was read and held no citable fact")
    ap.add_argument("--leads", type=int,
                    help="AI-generated files only: how many claims were extracted "
                         "for independent sourcing")
    ap.add_argument("--about-document", action="store_true",
                    help="AI-generated files only: the evidence rows describe the "
                         "document itself, not the world it talks about")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if not Path(a.run).is_dir():
        sys.exit(f"ERROR no such run directory: {a.run}")
    if a.cmd == "scan":
        sys.exit(scan(a.run, a.json))
    if a.cmd == "status":
        sys.exit(status(a.run))
    if not a.file:
        ap.error(f"{a.cmd} needs a file")
    if a.cmd == "register":
        sys.exit(register(a.run, a.file, a.evidence, a.notes, a.summary,
                          a.nothing_usable, a.leads, a.about_document))
    sys.exit(show(a.run, a.file))


if __name__ == "__main__":
    main()
