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
from pathlib import Path
from types import ModuleType
from typing import Any

from backend import workspace

_modules: dict[str, ModuleType] = {}


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


def document_export(name: str, slug: str, formats: list[str], track: bool, author: str) -> dict[str, Any]:
    """Export the master to Word (in the original's design) and, if asked, PDF."""
    run = workspace.run_dir(name)
    _find(run, slug)
    wanted = [f for f in formats if f in ("docx", "pdf")] or ["docx"]
    args = ["export", str(run), slug, "--to", ",".join(wanted)]
    if track:
        args += ["--track", "--author", author.strip()[:120] or "Revision"]
    code, out = _document(run, args, 600)
    files = [m.group(1).split(" · ")[0].strip() for m in re.finditer(r"^wrote (.+)$", out, re.M)]
    problems = [line for line in out.splitlines() if line.startswith(("PROBLEM", "REFUSED", "ERROR"))]
    return {"ok": code == 0, "files": files, "problems": problems, "output": out[-4000:]}
