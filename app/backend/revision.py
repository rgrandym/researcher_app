"""Revision runs: the documents a run improves, their change plans, and the author's decisions.

The workspace owns the logic (`.claude/scripts/subject.py` and `changes.py`); this module
loads those scripts the way `workspace.runmeta()` loads `runmeta.py`, so the app and the
agents read the same plan and write the same decisions file. The app writes only
`subjects/<slug>/decisions.json` (the author's decisions) and the request file that starts
`/revise` or `/rebuild`.

A Word or PDF document revised in Markdown has a master instead of a plan (`<slug>.md`,
declared by `document.py start`). The app shows what changed against the original and
exports the master to Word and PDF with `document.py`, a script, so no agent turn runs.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import time
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from backend import workspace

_modules: dict[str, ModuleType] = {}
_office_lock = threading.RLock()


def script(name: str) -> ModuleType:
    """A workspace script as a module (`changes`, `subject`)."""
    if name not in _modules:
        folder = workspace.root() / ".claude/scripts"
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
        spec = importlib.util.spec_from_file_location(name, folder / f"{name}.py")
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"{name}.py is missing from .claude/scripts")
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault(name, module)
        spec.loader.exec_module(module)
        _modules[name] = module
    return _modules[name]


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def subjects(name: str) -> list[dict[str, Any]]:
    """Declared documents with their plan counts and latest deliverable."""
    run = workspace.run_dir(name)
    changes = script("changes")
    out = []
    for item in script("subject").declared(run):
        slug = item["slug"]
        source = _json(run / "subjects" / slug / "source.json", {})
        counts: dict[str, int] = {}
        for _, status, _ in changes.states(run, slug):
            counts[status] = counts.get(status, 0) + 1
        version = changes.latest_version(run, slug)
        check = _json(version / "check.json", {}) if version else {}
        applied = _json(version / "applied.json", {}) if version else {}
        master = next((d["master"] for d in workspace.run_meta(run).get("documents", [])
                       if d.get("slug") == slug and (run / d["master"]).is_file()), None)
        out.append({
            "slug": slug,
            "master": master,
            "path": item["path"],
            # The file an Office master was started from, which may be a later deliverable.
            "office_file": Path(_json(run / "subjects" / slug / "office-source.json", {}).get("filename") or item["path"]).name,
            "role": item["role"],
            "format": source.get("format") or Path(item["path"]).suffix.lstrip(".").lower(),
            "editable": bool(source.get("editable", True)),
            "extracted": bool(source),
            "counts": counts,
            "deliverable": {
                "version": version.name,
                "file": str((version / (applied.get("file") or "")).relative_to(run)) if applied.get("file") else None,
                "ok": check.get("ok"),
                "problems": len(check.get("problems", [])),
            } if version else None,
        })
    return out


def plan(name: str, slug: str) -> dict[str, Any]:
    """The plan as the Changes view shows it: each change with its status and evidence."""
    run = workspace.run_dir(name)
    changes = script("changes")
    item = _find(run, slug)
    model = _json(run / "subjects" / slug / "model.json", {"parts": []})
    parts = {p["id"]: p for p in model.get("parts", [])}
    evidence = changes.evidence_rows(run)
    data = changes.plan(run, slug)
    rows = []
    for ch, status, decision in changes.states(run, slug):
        target = parts.get(ch.get("target"), {})
        rows.append({
            "id": ch.get("id"),
            "op": ch.get("op"),
            "kind": ch.get("kind"),
            "target": ch.get("target"),
            "where": target.get("section") or "",
            "context": target.get("text", "")[:600] if ch.get("op") in ("insert_after", "insert_before") else "",
            "before": ch.get("before"),
            "after": ch.get("after"),
            "rows": ch.get("rows"),
            "fill": ch.get("fill"),
            "summary": ch.get("summary") or "",
            "rationale": ch.get("rationale") or "",
            "basis": ch.get("basis", "evidence"),
            "pairs_with": ch.get("pairs_with") or [],
            "evidence": [
                {"id": eid, "title": evidence.get(eid, {}).get("title", ""),
                 "publisher": evidence.get(eid, {}).get("publisher", ""),
                 "url": evidence.get(eid, {}).get("url", "")}
                for eid in ch.get("evidence") or []
            ],
            "status": status,
            "decision": decision or None,
        })
    review = run / "subjects" / slug / "review.md"
    plan_file = run / "subjects" / slug / "changes.json"
    revised = run / "subjects" / slug / "revised.md"
    return {
        "revised": f"subjects/{slug}/revised.md" if revised.is_file() else None,
        "slug": slug,
        "path": item["path"],
        "format": model.get("format", ""),
        "changes": rows,
        "open": data.get("open") or [],
        "reviewed": review.is_file() and plan_file.is_file() and review.stat().st_mtime >= plan_file.stat().st_mtime,
    }


def _find(run: Path, slug: str) -> dict[str, Any]:
    for item in script("subject").declared(run):
        if item["slug"] == slug:
            return dict(item)
    raise FileNotFoundError(f"no document '{slug}' in this project")


def decide(name: str, slug: str, decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Record the author's decisions. `status` is accepted, rejected, or empty to clear;
    `after` is the author's own wording of the change."""
    run = workspace.run_dir(name)
    changes = script("changes")
    _find(run, slug)
    known = {c["id"]: c for c in changes.plan(run, slug).get("changes", [])}
    path = run / "subjects" / slug / "decisions.json"
    data = _json(path, {"decisions": {}})
    data.setdefault("decisions", {})
    for cid, d in decisions.items():
        if cid not in known:
            raise ValueError(f"no change {cid} in the plan")
        status = (d.get("status") or "").strip()
        if not status:
            data["decisions"].pop(cid, None)
            continue
        if status not in ("accepted", "rejected"):
            raise ValueError("a decision is accepted or rejected")
        entry: dict[str, Any] = {
            "status": status,
            "hash": changes.change_hash(known[cid]),
            "by": "author",
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        after = d.get("after")
        if isinstance(after, str) and after.strip() and after != known[cid].get("after"):
            if len(after) > 20_000:
                raise ValueError(f"{cid}: the rewritten text is too long")
            entry["after"] = after
        note = d.get("note")
        if isinstance(note, str) and note.strip():
            entry["note"] = note.strip()[:2000]
        data["decisions"][cid] = entry
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return plan(name, slug)


def from_markdown(name: str, slug: str) -> dict[str, Any]:
    """Rebuild the plan from revised.md after the author edited it. Decisions on changes
    their edit did not touch stand, because a decision binds to its change's content."""
    run = workspace.run_dir(name)
    _find(run, slug)
    changes = script("changes")
    try:
        changes.from_markdown(run, slug)
        changes.render(run, slug)
    except SystemExit as exc:
        raise ValueError(str(exc.code).removeprefix("ERROR ")) from exc
    return plan(name, slug)


def apply_request(name: str, slug: str, mode: str, author: str, notes: str) -> tuple[str, str]:
    """Write the request file and return (command, prompt) for the agent turn."""
    run = workspace.run_dir(name)
    item = _find(run, slug)
    source = _json(run / "subjects" / slug / "source.json", {})
    accepted = [c for c, status, _ in script("changes").states(run, slug) if status == "accepted"]
    if not accepted:
        raise ValueError("Accept at least one change first.")
    command = "revise" if source.get("editable", True) else "rebuild"
    folder = run / "deliverable" / slug
    folder.mkdir(parents=True, exist_ok=True)
    request = folder / f"request-{time.time_ns()}.json"
    request.write_text(json.dumps({
        "subject": item["path"],
        "mode": mode if source.get("format") == "docx" else "clean",
        "author": author.strip()[:120],
        "notes": notes.strip()[:10_000],
        "accepted": [c["id"] for c in accepted],
    }, indent=2) + "\n")
    prompt = (
        f"/{command} outputs/{name} {slug} Read outputs/{name}/deliverable/{slug}/{request.name} first "
        "and follow the author's choices. Apply only the accepted changes."
    )
    return command, prompt


def _document(run: Path, args: list[str], timeout: int) -> tuple[int, str]:
    """Run document.py on the backend's own interpreter, which has the Office libraries."""
    done = subprocess.run(
        [sys.executable, str(workspace.root() / ".claude/scripts/document.py"), *args],
        cwd=workspace.root(), capture_output=True, text=True, timeout=timeout,
    )
    return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()


def document_diff(name: str, slug: str) -> dict[str, Any]:
    """Write subjects/<slug>/diff.md: what the master changed against the original."""
    run = workspace.run_dir(name)
    _find(run, slug)
    code, out = _document(run, ["diff", str(run), slug, "--write"], 60)
    if code:
        raise ValueError(out.removeprefix("ERROR ") or "the comparison failed")
    return {"path": f"subjects/{slug}/diff.md", "summary": out.split("·")[-1].strip()}


def document_export(name: str, slug: str, formats: list[str], track: bool, author: str, design: str | None = None) -> dict[str, Any]:
    """Export the master to Word (in the original's design) and, if asked, PDF."""
    run = workspace.run_dir(name)
    item = _find(run, slug)
    fmt = Path(item["path"]).suffix[1:].lower()
    if fmt in ("xlsx", "pptx"):
        if formats != [fmt] or track:
            raise ValueError(f"Export this document as .{fmt}, without tracked changes.")
        with _office_lock:
            path = script("office_master").export(run, slug, design)
        return {"ok": True, "files": [path], "problems": [], "output": "Native content round-trip passed."}
    if design not in (None, "preserve"):
        raise ValueError("The design choice is available for spreadsheets and presentations.")
    wanted = [f for f in formats if f in ("docx", "pdf")] or ["docx"]
    args = ["export", str(run), slug, "--to", ",".join(wanted)]
    if track:
        args += ["--track", "--author", author.strip()[:120] or "Revision"]
    code, out = _document(run, args, 600)
    files = [m.group(1).split(" · ")[0].strip() for m in re.finditer(r"^wrote (.+)$", out, re.M)]
    problems = [line for line in out.splitlines() if line.startswith(("PROBLEM", "REFUSED", "ERROR"))]
    return {"ok": code == 0, "files": files, "problems": problems, "output": out[-4000:]}


def office_start(name: str, slug: str, source: str | None = None) -> dict[str, Any]:
    """Create once from the original or an explicitly selected existing deliverable."""
    run = workspace.run_dir(name)
    item = _find(run, slug)
    fmt = Path(item["path"]).suffix[1:].lower()
    if item["role"] != "subject" or fmt not in ("xlsx", "pptx"):
        raise ValueError("Choose a spreadsheet or presentation subject.")
    rel = source or f"external_data/{item['path']}"
    path = workspace.run_file(name, rel)
    original = (run / "external_data" / item["path"]).resolve()
    delivered = (run / "deliverable" / slug).resolve()
    if path.suffix.lower() != f".{fmt}" or (path.resolve() != original and not path.resolve().is_relative_to(delivered)):
        raise ValueError("Start from this document's supplied file or one of its deliverables.")
    with _office_lock:
        master = script("office_master").start(run, slug, path)
    return {"master": master.name, "slug": slug}


def office_content(name: str, slug: str) -> dict[str, Any]:
    run = workspace.run_dir(name)
    _find(run, slug)
    office = script("office_master")
    _, master = office.paths(run, slug)
    _, original, meta = office.baseline(run, slug)
    text = master.read_text()
    data = office.decode(text)
    office.validate(data, original)
    return {"data": data, "text": text, "master": master.name, "mtime": master.stat().st_mtime, "source": meta["source"]}


def _stem_key(name: str) -> str:
    """A file's name without version marks: "v4 - Cash flow forecast-2" → "cash-flow-forecast"."""
    key = script("subject").slug_of(name)
    return re.sub(r"^v\d+-|-(?:v?\d+)$", "", key)


def _original_of(run: Path, slug: str, path: Path) -> str | None:
    """The supplied file a deliverable folder revises, by declared slug or by name."""
    subject = script("subject")
    item = next((s for s in subject.declared(run) if s["slug"] == slug and s["role"] == "subject"), None)
    if item:
        return str(item["path"])
    ext = run / "external_data"
    keys = {slug, _stem_key(path.stem)}
    found = [f for f in sorted(ext.rglob(f"*{path.suffix}")) if f.is_file() and not f.name.startswith(".")
             and f.suffix.lower() == path.suffix.lower() and _stem_key(f.stem) in keys
             and "ai_reports" not in f.relative_to(ext).parts] if ext.is_dir() else []
    return str(found[0].relative_to(ext)) if len(found) == 1 else None


def _open_deliverable(name: str, run: Path, path: Path) -> dict[str, Any]:
    """Start an editable copy from a delivered file; the delivered file is never changed."""
    slug = path.relative_to(run / "deliverable").parts[0]
    original = _original_of(run, slug, path)
    if not original:
        raise ValueError(f"{path.name} can be viewed, but its supplied original is not in external_data, "
                         "so there is no baseline to edit against. Add the original there, then open it again.")
    with _office_lock:
        subject = script("subject")
        items = subject.declared(run)
        if not any(s["slug"] == slug for s in items):
            if any(s["path"] == original for s in items):
                raise ValueError(f"{original} is already declared under another name. Open it from its own entry.")
            meta = subject.run_json(run)
            meta["subjects"] = [*meta.get("subjects", []), {"path": original, "role": "subject", "slug": slug}]
            (run / ".run.json").write_text(json.dumps(meta, indent=2) + "\n")
        return office_start(name, slug, str(path.relative_to(run)))


def office_open(name: str, rel: str) -> dict[str, Any]:
    """Open an uploaded or delivered Office file without requiring a prior audit or change plan."""
    run = workspace.run_dir(name).resolve()
    path = workspace.run_file(name, rel).resolve()
    ext = (run / "external_data").resolve()
    if path.suffix.lower() not in (".xlsx", ".pptx"):
        raise ValueError("Choose a .xlsx or .pptx file.")
    if path.is_relative_to(run / "deliverable"):
        return _open_deliverable(name, run, path)
    if not path.is_relative_to(ext):
        raise ValueError("Choose an uploaded file in external_data or a delivered file.")
    relative = str(path.relative_to(ext))
    with _office_lock:
        subject = script("subject")
        items = subject.declared(run)
        item = next((s for s in items if s["path"] == relative and s["role"] == "subject"), None)
        if not item:
            # Read before registering, so malformed uploads cannot leave broken entries.
            script("office_master").read_native(path)
            slug = subject.slug_of(relative)
            used = {s["slug"] for s in items}
            stem, number = slug, 2
            while slug in used:
                slug = f"{stem}-{number}"
                number += 1
            item = {"path": relative, "role": "subject", "slug": slug}
            meta = subject.run_json(run)
            # Keep template declarations intact: edits use a separate master and copy.
            meta["subjects"] = [*meta.get("subjects", []), item]
            (run / ".run.json").write_text(json.dumps(meta, indent=2) + "\n")
        return office_start(name, item["slug"], rel)
