#!/usr/bin/env python3
"""document.py: a supplied Word or PDF document revised as a Markdown master.

    python3 .claude/scripts/document.py start  <run> <slug> [--from FILE]   # create <slug>.md
    python3 .claude/scripts/document.py diff   <run> <slug> [--write]       # what changed, by section
    python3 .claude/scripts/document.py export <run> <slug> [--to docx,pdf] [--track] [--author NAME] [--partial]

`start` copies `subjects/<slug>/document.md` (the document as Markdown, each block under
a hidden `<!-- ID -->`) to `<run>/<slug>.md` and declares it a master of the run in
`.run.json`. From then on it is a master like report.md: the gates run on every write,
and /critique, /repair, /expand, /verify and the author's own edits act on it. `--from`
seeds it from another Markdown file with the same anchors (an earlier revised.md).

`diff` lists every block the master changed, added or removed against the original,
section by section; `--write` saves it as `subjects/<slug>/diff.md` for a reviewer.

`export` turns the master back into the original's form, with no agent turn:

- Word: the master's difference from document.md becomes a change plan in memory, applied
  to a copy of the original inside its own structure (styles, numbering, footnotes,
  headers survive), with the draft's working marks cleaned. Evidence IDs are removed: the
  document cites in its own system. Written to `deliverable/<slug>/vN/` with applied.json,
  then `changes.py check` compares it with the original. `--track` writes tracked changes.
- PDF: a PDF cannot be edited in place, so the Word file is made from the master with
  pandoc in plain styles. Supplying the source .docx keeps the original design.
- `--to pdf` adds a PDF of the Word file, made by Microsoft Word or LibreOffice.

Export refuses a master that still carries `[UNVERIFIED]`: a claim nobody could source
does not reach a finished document silently. Exit 1 on any refusal or failed check.
Doctrine: `.claude/references/revision.md`.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_changes  # noqa: E402
import changes as plans  # noqa: E402
import subject as subjects  # noqa: E402

CITE = re.compile(r"\s*\[E\d+\](?:\[E\d+\])*")
UNVERIFIED = re.compile(r"\[UNVERIFIED\]")
NOTE_LINE = re.compile(r"^\s*<!--\s*(?:why|open|comment)\b.*?-->\s*$", re.M | re.S | re.I)
ANCHOR_LINE = re.compile(r"^\s*<!--\s*[A-Z]+[\w.]*\s*-->\s*$", re.M)


def master_of(run, slug):
    return Path(run) / f"{slug}.md"


def register(run, slug, master):
    """Declare the master in .run.json, keeping every other key."""
    path = Path(run) / ".run.json"
    data = json.loads(path.read_text()) if path.is_file() else {"kind": "research"}
    docs = [d for d in data.get("documents") or [] if d.get("slug") != slug]
    docs.append({"slug": slug, "master": master.name,
                 "created": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    data["documents"] = docs
    path.write_text(json.dumps(data, indent=2) + "\n")


def start(run, slug, seed=None):
    item = subjects.find(run, slug)
    if item["role"] != "subject":
        sys.exit(f"ERROR {item['path']} is a template: its design is copied, the file is not revised")
    source = plans.sdir(run, slug) / "document.md"
    if not source.is_file():
        sys.exit(f"ERROR {slug} has no document.md: run subject.py extract {run} {slug} "
                 f"(Word and PDF documents; decks and spreadsheets take a change plan)")
    master = master_of(run, slug)
    if master.exists():
        sys.exit(f"ERROR {master} already exists: it is the master; edit it in place")
    text = Path(seed).read_text() if seed else source.read_text()
    master.write_text(text)
    register(run, slug, master)
    print(f"wrote {master} · declared a master of {Path(run).name}")
    return 0


def blocks(text):
    """[(anchor or None, block text)] with notes dropped."""
    out = []
    for raw in re.split(r"\n\s*\n", text):
        anchor = None
        lines = []
        for line in raw.strip("\n").split("\n"):
            m = re.match(r"^\s*<!--\s*([A-Z]+[\w.]*)\s*-->\s*$", line)
            if m and not lines:
                anchor = m.group(1)
            elif not NOTE_LINE.match(line):
                lines.append(line.rstrip())
        body = "\n".join(lines).strip()
        if body:
            out.append((anchor, body))
    return out


def diff(run, slug, write=False):
    master = master_of(run, slug)
    if not master.is_file():
        sys.exit(f"ERROR no master for {slug}: document.py start {run} {slug}")
    original = blocks((plans.sdir(run, slug) / "document.md").read_text())
    revised = blocks(master.read_text())
    before = {a: b for a, b in original if a}
    kept = {a for a, _ in revised if a}
    lines, section, counts = [], "the opening", {"changed": 0, "added": 0, "removed": 0}
    shown = None
    for anchor, body in revised:
        if body.startswith("#"):
            section = body.lstrip("# ").strip()[:80]
        kind = ("added" if anchor not in before else "changed" if before[anchor] != body else None)
        if kind is None:
            continue
        counts[kind] += 1
        if shown != section:
            lines += ["", f"## {section}", ""]
            shown = section
        if kind == "changed":
            lines += [f"**Changed** ({anchor})", "", "> " + before[anchor].replace("\n", "\n> "), "", body, ""]
        else:
            lines += ["**Added**", "", body, ""]
    gone = [(a, b) for a, b in original if a and a not in kept]
    if gone:
        lines += ["", "## Removed", ""]
        for a, b in gone:
            counts["removed"] += 1
            lines += [f"({a})", "", "> " + b.replace("\n", "\n> "), ""]
    head = (f"# Changes to {subjects.find(run, slug)['path']}\n\n"
            f"{counts['changed']} changed, {counts['added']} added, {counts['removed']} removed.\n")
    text = head + "\n".join(lines) + "\n"
    if write:
        out = plans.sdir(run, slug) / "diff.md"
        out.write_text(text)
        print(f"wrote {out} · {head.splitlines()[-1]}")
    else:
        print(text)
    return 0


def to_pdf(docx, out_dir):
    """A PDF of a Word file, made by LibreOffice or Microsoft Word. None if neither can."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    target = out_dir / (docx.stem + ".pdf")
    if soffice:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx)],
                       capture_output=True, timeout=180)
        if target.is_file():
            return target
    if Path("/Applications/Microsoft Word.app").exists():
        # Word is sandboxed: a script can open and save files only inside its own container
        # without a permission prompt, so the conversion runs there and the PDF is copied back.
        box = Path.home() / "Library/Containers/com.microsoft.Word/Data/research-export"
        box.mkdir(parents=True, exist_ok=True)
        inside, made = box / "document.docx", box / "document.pdf"
        made.unlink(missing_ok=True)
        shutil.copy2(docx, inside)
        script = f'''
            tell application "Microsoft Word"
                open file name (POSIX file "{inside}" as text) with read only
                delay 1
                set doc to active document
                save as doc file name (POSIX file "{made}" as text) file format format PDF
                close doc saving no
            end tell'''
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=300)
        if made.is_file():
            shutil.move(str(made), target)
        inside.unlink(missing_ok=True)
        if target.is_file():
            return target
    return None


def clean_text(text):
    """The master as the document's reader gets it: no evidence IDs, no notes, no anchors."""
    text = CITE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", NOTE_LINE.sub("", text))


def next_version(run, slug):
    base = Path(run) / "deliverable" / slug
    n = 1 + max([int(p.name[1:]) for p in base.glob("v*") if p.name[1:].isdigit()] or [0])
    vdir = base / f"v{n}"
    vdir.mkdir(parents=True)
    return n, vdir


def export(run, slug, formats, track=False, author="Revision", partial=False):
    run = Path(run)
    item = subjects.find(run, slug)
    master = master_of(run, slug)
    if not master.is_file():
        sys.exit(f"ERROR no master for {slug}: document.py start {run} {slug}")
    text = master.read_text()
    holes = [i for i, line in enumerate(text.splitlines(), 1) if UNVERIFIED.search(line)]
    if holes:
        sys.exit(f"ERROR {master.name} still carries [UNVERIFIED] at line(s) "
                 f"{', '.join(map(str, holes[:12]))}: source those claims or remove them before export")
    src = run / "external_data" / item["path"]
    fmt = subjects.officedoc.fmt_of(src)
    clean = clean_text(text)

    if fmt == "docx":
        plan_ = plans.plan_from_markdown(run, slug, clean, master.name)
        problems, _ = plans.validate(run, slug, quiet=True, data=plan_)
        if problems:
            for p in problems:
                print(f"PROBLEM {p}")
            sys.exit(f"ERROR {len(problems)} edit(s) in {master.name} cannot be carried into the "
                     f"Word file; fix them in the master and export again")
        editor = apply_changes.DocxEditor(src, track, author)
        results = []
        for ch in plan_["changes"]:
            try:
                editor.apply(ch)
                results.append({"id": ch["id"], "status": "applied"})
            except apply_changes.Refused as exc:
                results.append({"id": ch["id"], "status": "refused", "reason": str(exc)})
        refused = [r for r in results if r["status"] == "refused"]
        for r in refused:
            print(f"REFUSED {r['id']}: {r['reason']}")
        if refused and not partial:
            sys.exit(f"ERROR {len(refused)} edit(s) could not be applied; nothing was written. "
                     f"Fix them in the master, or rerun with --partial to write the rest.")
        n, vdir = next_version(run, slug)
        dest = vdir / src.name
        editor.save(dest)
        (vdir / "applied.json").write_text(json.dumps({
            "subject": item["path"], "file": src.name, "version": n, "format": fmt, "track": track,
            "from": master.name, "source_sha256": subjects.sha256(src),
            "applied": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "results": results, "notes": editor.notes_out, "changes": plan_["changes"],
        }, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {dest.relative_to(run)} · {len(results) - len(refused)} edit(s) carried"
              + (f", {len(refused)} refused" if refused else "") + (" · tracked" if track else ""))
        code = plans.check(run, slug, vdir.name)
    elif fmt == "pdf":
        n, vdir = next_version(run, slug)
        dest = vdir / (src.stem + ".docx")
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "body.md"
            body.write_text(ANCHOR_LINE.sub("", clean))
            done = subprocess.run(["pandoc", str(body), "-o", str(dest)], capture_output=True, text=True)
        if done.returncode:
            sys.exit(f"ERROR pandoc could not write the Word file: {done.stderr.strip()[:400]}")
        (vdir / "applied.json").write_text(json.dumps({
            "subject": item["path"], "file": dest.name, "version": n, "format": "pdf", "from": master.name,
            "source_sha256": subjects.sha256(src),
            "applied": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "results": [], "notes": ["a PDF cannot be edited in place: the Word file is in plain styles"],
            "changes": [],
        }, indent=2) + "\n")
        print(f"wrote {dest.relative_to(run)} · plain styles: supply the source .docx to keep the design")
        code = 0
    else:
        sys.exit(f"ERROR {src.name} is {fmt}: decks and spreadsheets are revised by a change plan "
                 f"(/changes, then /revise)")

    if "pdf" in formats:
        pdf = to_pdf(dest, vdir)
        if pdf:
            print(f"wrote {pdf.relative_to(run)}")
        else:
            print("PROBLEM no PDF: neither LibreOffice nor Microsoft Word could convert the file")
            code = 1
    return code


def main():
    argv = sys.argv[1:]
    opts = {}
    for key in ("--from", "--to", "--author"):
        if key in argv:
            i = argv.index(key)
            opts[key[2:]] = argv[i + 1]
            del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    if len(args) < 3:
        sys.exit(__doc__)
    cmd, run = args[0], Path(args[1])
    if not run.is_dir():
        sys.exit(f"ERROR no such run: {run}")
    slug = subjects.find(run, args[2])["slug"]
    if cmd == "start":
        return start(run, slug, opts.get("from"))
    if cmd == "diff":
        return diff(run, slug, "--write" in argv)
    if cmd == "export":
        formats = {f.strip() for f in opts.get("to", "docx").split(",")}
        return export(run, slug, formats, "--track" in argv, opts.get("author", "Revision"), "--partial" in argv)
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
