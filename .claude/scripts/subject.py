#!/usr/bin/env python3
"""subject.py: the documents a revision run improves, read into addressable parts.

    python3 .claude/scripts/subject.py add <run> <file> [--role subject|template]
    python3 .claude/scripts/subject.py extract <run> [<slug>]      # all, or one
    python3 .claude/scripts/subject.py list <run>
    python3 .claude/scripts/subject.py show <run> <slug> <ID> [<ID>...]

A file in `external_data/` is normally a source. Declared here, it becomes the
**subject** (the document being improved: its claims are audited, its form is kept)
or a **template** (its design and voice are copied, its content is not evidence).
Files under `external_data/subject/` and `external_data/template/` are declared by
where they sit. The declaration lives in the run's `.run.json`; nothing in
`external_data/` is ever modified. Doctrine: `.claude/references/revision.md`.

`extract` writes, per document, `<run>/subjects/<slug>/`:

    source.json      the file, its role, its content hash
    model.json       every addressable part: id, kind, text, style, section
    text.md          the same as readable text, one part per line with its ID
    document.md      (Word, PDF) the document as Markdown, each block under a hidden <!-- ID -->:
                     document.py start copies it to the run's revised-document master
    design.json      page set-up, fonts, sizes, colours, styles, layouts, theme
    references.json  how the document cites: footnotes, numbered, author-date, links
    pages/ images/   page renders and embedded pictures (PDF)

It re-extracts only when the file's hash changed. Exit 0 on success.
"""
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import officedoc  # noqa: E402

ROLES = ("subject", "template")


def slug_of(rel):
    stem = Path(rel).stem.lower()
    return re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:48] or "document"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_json(run):
    p = Path(run) / ".run.json"
    if p.is_file():
        try:
            data = json.loads(p.read_text())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"kind": "research", "doc_kind": "report", "masters": ["report.md", "draft.md"]}


def declared(run):
    """[{path, role, slug}] from .run.json plus the reserved folders."""
    run = Path(run)
    ext = run / "external_data"
    out, seen = [], set()
    for item in run_json(run).get("subjects", []):
        if isinstance(item, dict) and item.get("path"):
            out.append({"path": item["path"], "role": item.get("role", "subject"),
                        "slug": item.get("slug") or slug_of(item["path"])})
            seen.add(item["path"])
    for role in ROLES:
        folder = ext / role
        if folder.is_dir():
            for f in sorted(folder.rglob("*")):
                rel = str(f.relative_to(ext))
                if f.is_file() and officedoc.fmt_of(f) and rel not in seen:
                    out.append({"path": rel, "role": role, "slug": slug_of(rel)})
    slugs = set()
    for item in out:                          # two files with one stem keep apart
        base, n = item["slug"], 2
        while item["slug"] in slugs:
            item["slug"] = f"{base}-{n}"
            n += 1
        slugs.add(item["slug"])
    return out


def find(run, slug):
    for item in declared(run):
        if item["slug"] == slug or item["path"] == slug:
            return item
    sys.exit(f"ERROR no declared subject '{slug}' in {run}. "
             f"Declared: {', '.join(i['slug'] for i in declared(run)) or 'none'}")


def subject_dir(run, slug):
    return Path(run) / "subjects" / slug


def add(run, target, role):
    run = Path(run)
    ext = run / "external_data"
    p = Path(target)
    if not p.is_file():
        p = ext / target
    if not p.is_file():
        sys.exit(f"ERROR no such file under external_data: {target}")
    try:
        rel = str(p.resolve().relative_to(ext.resolve()))
    except ValueError:
        sys.exit(f"ERROR {target} is not under {ext}. Supplied documents live in external_data/.")
    if rel.startswith("ai_reports/") and role == "subject":
        print(f"note: {rel} is AI-generated. As a subject its claims are audited like any "
              f"other; it is still never a source.")
    if officedoc.fmt_of(p) is None:
        sys.exit(f"ERROR {p.name}: format not supported for revision")
    data = run_json(run)
    subjects = [s for s in data.get("subjects", []) if s.get("path") != rel]
    subjects.append({"path": rel, "role": role, "slug": slug_of(rel), "added": date.today().isoformat()})
    data["subjects"] = subjects
    (run / ".run.json").write_text(json.dumps(data, indent=2) + "\n")
    fmt = officedoc.fmt_of(p)
    editable = "edited in place" if fmt in officedoc.EDITABLE else "read-only: rebuilt, never edited"
    print(f"declared {rel} as {role} ({fmt}, {editable}) · slug {slug_of(rel)}")
    return 0


def render_text(model, item):
    fmt = model["format"]
    lines = [f"# {Path(item['path']).name}", "",
             f"Format: {fmt} · role: {item['role']} · {len(model['parts'])} parts. "
             f"Each line is one part: `[ID] (style) text`. Quote `before` text from here exactly.", ""]
    marks = model.get("marks") or {}
    comments = {c["id"]: c for c in model.get("comments", [])}
    if marks.get("struck_parts") or marks.get("draft_colors") or comments:
        lines += ["## Working marks (a draft's, not the document's design)", "",
                  f"- Struck out by the author: {', '.join(marks.get('struck_parts', [])) or 'none'}. "
                  f"Struck text is deleted text: never edit it or bring it back unless the audit says so.",
                  f"- Draft colours on body text: {', '.join(f'{c} ({n} chars)' for c, n in marks.get('draft_colors', {}).items()) or 'none'}.",
                  f"- Comments: {len(comments)}. Each is shown under the paragraph it is attached to; "
                  f"they are the authors' own instructions.", ""]
    section = None
    for p in model["parts"]:
        if p.get("section") != section and p["kind"] not in ("heading", "slide", "sheet", "page"):
            section = p.get("section")
        if p["kind"] in ("heading", "slide", "sheet", "page"):
            section = p.get("section")
            lines += ["", f"## [{p['id']}] {' '.join(p['text'].split())[:160]}"]
            if p["kind"] == "slide":
                lines.append(f"layout: {p.get('layout')}")
            continue
        text = p["text"].replace("\n", " ⏎ ")
        if p["kind"] == "table":
            lines.append(f"[{p['id']}] (table {p['rows']}×{p['cols']})")
            continue
        if p["kind"] == "shape":
            tag = p.get("placeholder") or ("picture" if p.get("picture") else p.get("name", ""))
            lines.append(f"[{p['id']}] (shape: {tag}; box {p.get('box_pt')})")
            continue
        meta = p.get("style") or p["kind"]
        if p.get("list"):
            meta += ", list"
        if p.get("level") is not None and p["kind"] in ("para", "notes"):
            meta += f", level {p['level']}"
        if fmt == "xlsx":
            extra = f"  → {p['cached']!r}" if p["kind"] == "formula" else ""
            extra += f"  [{p['format']}]" if p.get("format") else ""
            lines.append(f"[{p['id']}] {text}{extra}")
        elif text.strip():
            if p.get("struck"):
                meta += "; STRUCK OUT" if not p.get("unstruck", "").strip() else "; partly struck out"
            if p.get("colors"):
                meta += "; draft colour " + "/".join(p["colors"])
            lines.append(f"[{p['id']}] ({meta}) {text}")
            if p.get("struck") and p.get("unstruck", "").strip():
                struck_text = " … ".join(text[a:b] for a, b in p["struck"])
                lines.append(f"    struck: {struck_text}")
            for cid in p.get("comments") or []:
                c = comments.get(cid)
                if c:
                    lines.append(f"    ↳ comment {cid} ({c['author']}): {c['text']}")
    return "\n".join(lines) + "\n"


def pdf_markdown(model):
    """A PDF's text as Markdown, one block per text block under its `<!-- PG03.b2 -->` ID.
    Its headings are not marked: the PDF records sizes, not structure."""
    blocks = []
    for part in model["parts"]:
        if part["kind"] == "block" and part["text"].strip():
            blocks.append(f"<!-- {part['id']} -->\n" + " ".join(part["text"].split()))
    return "\n\n".join(blocks) + "\n"


def extract_one(run, item, force=False):
    run = Path(run)
    src = run / "external_data" / item["path"]
    if not src.is_file():
        print(f"MISSING {item['path']}: declared but no longer in external_data")
        return 1
    out = subject_dir(run, item["slug"])
    digest = sha256(src)
    meta_path = out / "source.json"
    if not force and meta_path.is_file():
        old = json.loads(meta_path.read_text())
        current = (out / "model.json").is_file() and (
            officedoc.fmt_of(src) not in ("docx", "pdf") or (out / "document.md").is_file())
        if old.get("sha256") == digest and current:
            print(f"UNCHANGED {item['slug']}  ({item['path']})")
            return 0
    out.mkdir(parents=True, exist_ok=True)
    model = officedoc.read(src)
    fmt = model["format"]
    extra = {}
    if fmt == "pdf":
        pages, images = officedoc.render_pdf(src, out)
        extra = {"pages": pages, "images": images}
    (out / "model.json").write_text(json.dumps(
        {"format": fmt, "parts": model["parts"], "links": model.get("links", []),
         "comments": model.get("comments", [])},
        indent=1, ensure_ascii=False, default=str) + "\n")
    (out / "design.json").write_text(json.dumps(model["design"], indent=2, ensure_ascii=False, default=str) + "\n")
    if fmt == "docx":
        # The editing surface: the document as Markdown, every block under its ID.
        (out / "document.md").write_text(officedoc.docx_markdown(src))
    elif fmt == "pdf":
        (out / "document.md").write_text(pdf_markdown(model))
    if model.get("marks"):
        (out / "marks.json").write_text(json.dumps(model["marks"], indent=2, ensure_ascii=False) + "\n")
    (out / "references.json").write_text(json.dumps(model["references"], indent=2, ensure_ascii=False) + "\n")
    (out / "text.md").write_text(render_text(model, item))
    meta = {"path": item["path"], "role": item["role"], "slug": item["slug"], "format": fmt,
            "editable": fmt in officedoc.EDITABLE, "sha256": digest,
            "extracted": date.today().isoformat(), "parts": len(model["parts"]), **extra}
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    refs = model["references"]
    d = model["design"]
    fonts = ", ".join(list(d.get("fonts", {}))[:4]) if isinstance(d.get("fonts"), dict) else ""
    print(f"EXTRACTED {item['slug']}  {fmt}, {len(model['parts'])} parts · citations: {refs['system']}"
          f" · fonts: {fonts or 'defaults'}" + (f" · {len(extra.get('pages', []))} page images" if extra else ""))
    print(f"  read {out / 'text.md'}")
    return 0


def extract(run, slug=None, force=False):
    items = [find(run, slug)] if slug else declared(run)
    if not items:
        sys.exit("ERROR no subject declared. Use: subject.py add <run> <file> --role subject")
    return max(extract_one(run, i, force) for i in items)


def list_(run):
    items = declared(run)
    if not items:
        print("no subjects declared")
        return 0
    for i in items:
        d = subject_dir(run, i["slug"])
        state = "extracted" if (d / "model.json").is_file() else "not extracted"
        ch = d / "changes.json"
        if ch.is_file():
            n = len(json.loads(ch.read_text()).get("changes", []))
            state += f" · {n} proposed change(s)"
        print(f"{i['slug']:<40} {i['role']:<9} {i['path']}  [{state}]")
    return 0


def show(run, slug, ids):
    model = json.loads((subject_dir(run, find(run, slug)["slug"]) / "model.json").read_text())
    byid = {p["id"]: p for p in model["parts"]}
    for i in ids:
        p = byid.get(i)
        if p is None:
            print(f"{i}: no such part")
            continue
        print(json.dumps(p, ensure_ascii=False, indent=1, default=str))
    return 0


def main():
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    role = "subject"
    if "--role" in sys.argv:
        role = sys.argv[sys.argv.index("--role") + 1]
        if role in args:
            args.remove(role)
        if role not in ROLES:
            sys.exit(f"ERROR --role is one of {', '.join(ROLES)}")
    if len(args) < 2:
        sys.exit(__doc__)
    cmd, run = args[0], Path(args[1])
    if not run.is_dir():
        sys.exit(f"ERROR no such run: {run}")
    if cmd == "add" and len(args) >= 3:
        return add(run, args[2], role)
    if cmd == "extract":
        return extract(run, args[2] if len(args) > 2 else None, "--force" in sys.argv)
    if cmd == "list":
        return list_(run)
    if cmd == "show" and len(args) >= 4:
        return show(run, args[2], args[3:])
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
