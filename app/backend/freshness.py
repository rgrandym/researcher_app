"""Copies kept current with the documents they were made from.

An export (HTML, Word or PDF in `export/<style>/`) and a delivered file (Word, PowerPoint
or Excel in `deliverable/<slug>/vN/`) are copies of a document. Once the document changes,
the copy no longer shows it. `stale` lists such copies for the run view; `refresh` makes
them again with the settings the last copy was made with (style, formats, citations,
comments, tracked changes, design), so a file the author sends is never older than the
document they see.

A delivered file the app did not write (no `applied.json` beside it), such as a deck an
agent saved as a new file, is folded back into its document so the document stays one: a
deck or workbook is merged into the editable master (office_master.rebase, three-way, by
slide and shape), then exported as the next version. A merge that would have to choose
between two edits of the same thing, and a Word file, are reported for the author instead.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from backend import render, revision, workspace

STYLE_FORMATS = ("html", "docx", "pdf")
NATIVE = (".docx", ".pptx", ".xlsx")
VERSION = re.compile(r"^v(\d+)$")


def _json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _exports(run: Path, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """One entry per document and style that has export files older than the document."""
    out = []
    root = run / "export"
    if not root.is_dir():
        return out
    masters = [m for m in meta.get("masters", []) if (run / m).is_file()]
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "src"):
        stems = sorted({p.stem for p in folder.iterdir() if p.suffix[1:] in STYLE_FORMATS})
        for stem in stems:
            record = _json(render.record_path(folder, stem))
            doc = record.get("doc")
            if not doc:  # exported before exports recorded their document
                named = ("report.md", "draft.md") if stem == "report" else tuple(m for m in masters if Path(m).stem == stem)
                doc = next((m for m in named if m in masters), None)
            source = run / str(doc) if doc else None
            if source is None or not source.is_file():
                continue
            files = [folder / f"{stem}.{f}" for f in STYLE_FORMATS if (folder / f"{stem}.{f}").is_file()]
            old = [f for f in files if f.stat().st_mtime < source.stat().st_mtime]
            if not old:
                continue
            out.append({
                "doc": doc, "kind": "export", "style": folder.name,
                "files": [str(f.relative_to(run)) for f in old], "blocked": None,
                "settings": {
                    "formats": record.get("formats") or [f.suffix[1:] for f in files],
                    "cite": record.get("cite", True),
                    "comments": record.get("comments"),  # None: not recorded, see refresh
                },
            })
    return out


def _deliverables(run: Path, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """The newest delivered file of each revised document, when it is older than the document."""
    out = []
    for entry in meta.get("documents", []):
        slug, master = entry.get("slug"), run / str(entry.get("master"))
        folder = run / "deliverable" / str(slug)
        if not master.is_file() or not folder.is_dir():
            continue
        versions = sorted((p for p in folder.iterdir() if p.is_dir() and VERSION.match(p.name)), key=lambda p: int(p.name[1:]))
        for version in reversed(versions):
            natives = sorted((f for f in version.iterdir() if f.suffix.lower() in NATIVE and not f.name.startswith(("~$", "."))), key=lambda f: f.stat().st_mtime)
            if natives:
                break
        else:
            continue
        native = natives[-1]
        rel = str(native.relative_to(run))
        applied = _json(version / "applied.json")
        office = _json(run / "subjects" / str(slug) / "office-source.json")
        if not applied and office.get("source") != rel:
            # Made outside the editor, whatever its date. A deck or workbook is merged into the
            # editable document so it stays one document; a Word file cannot be, and waits.
            merge = native.suffix.lower() in (".pptx", ".xlsx") and bool(office)
            out.append({
                "doc": master.name, "kind": "merge" if merge else "deliverable", "slug": slug, "files": [rel],
                "blocked": None if merge else (
                    f"{native.name} ({version.name}) was made outside the editor and may hold content "
                    f"{master.name} does not have. Open both and keep one before exporting again."),
                "settings": {},
            })
            continue
        if native.stat().st_mtime >= master.stat().st_mtime:
            continue
        out.append({
            "doc": master.name, "kind": "deliverable", "slug": slug,
            "files": [rel], "blocked": None,
            "settings": {
                "formats": [native.suffix[1:].lower()] + (["pdf"] if native.suffix.lower() == ".docx" and (version / f"{native.stem}.pdf").is_file() else []),
                "track": bool(applied.get("track")),
                "author": str(applied.get("author") or ""),
                "design": applied.get("design"),
            },
        })
    return out


def stale(name: str) -> list[dict[str, Any]]:
    """Every copy of a document in this run that is older than the document."""
    run = workspace.run_dir(name)
    meta = workspace.run_meta(run)
    return _exports(run, meta) + _deliverables(run, meta)


def refresh(name: str, docs: set[str] | None = None, since: float | None = None) -> list[dict[str, Any]]:
    """Make stale copies again, for `docs` only when given, and only of documents changed at
    or after `since` when given. One result per copy: the files written, or why not."""
    with _locks.setdefault(name, threading.Lock()):  # the refresh after a turn and the button never overlap
        return _refresh(name, docs, since)


_locks: dict[str, threading.Lock] = {}


def _refresh(name: str, docs: set[str] | None, since: float | None) -> list[dict[str, Any]]:
    run = workspace.run_dir(name)
    results = []
    office = revision.script("office_master")
    for item in stale(name):
        if item["kind"] != "merge" or (docs is not None and item["doc"] not in docs):
            continue
        result = {"doc": item["doc"], "kind": "merge", "files": item["files"], "problem": None}
        try:
            with revision._office_lock:
                office.rebase(run, item["slug"], run / item["files"][0])
            workspace.snapshot(run, item["doc"])
        except (ValueError, FileNotFoundError) as exc:
            result["problem"] = f"{Path(item['files'][0]).name} could not be merged into {item['doc']}: {exc}"
        results.append(result)
    for item in stale(name):  # again: a merge leaves the master newer than its copies
        if item["kind"] == "merge" or (docs is not None and item["doc"] not in docs):
            continue
        if since is not None and (run / item["doc"]).stat().st_mtime < since:
            continue
        result: dict[str, Any] = {"doc": item["doc"], "kind": item["kind"], "files": [], "problem": item["blocked"]}
        if not item["blocked"]:
            s = item["settings"]
            try:
                if item["kind"] == "export":
                    comments = s["comments"]
                    if comments is None:  # unrecorded: keep comments only if the last copy carried them
                        html = run / "export" / item["style"] / f"{Path(item['files'][0]).stem}.html"
                        comments = html.is_file() and 'class="comment-start"' in html.read_text(errors="replace")
                    done = render.export(name, item["doc"], item["style"], s["cite"], s["formats"], comments)
                    result["files"] = done["files"]
                    if "found losses" in done["check"]:
                        result["problem"] = done["check"][:600]
                else:
                    done = revision.document_export(name, item["slug"], s["formats"], s["track"], s["author"], s["design"])
                    result["files"] = done["files"]
                    if not done.get("ok", True) or done.get("problems"):
                        result["problem"] = "\n".join(done.get("problems") or [done.get("output", "")[-600:]])
            except (render.RenderError, FileNotFoundError, ValueError) as exc:
                result["problem"] = str(exc)
        results.append(result)
    return results
