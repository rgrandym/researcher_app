"""Proposals to write files outside the workspace: prepared here, never carried out here.

An agent prepares `<run>/publications/<id>.json` and the files it points to. This module reads
them, validates them and returns a snapshot (the bytes to write, with hashes). It performs no
external write and has no approval path. Only the desktop app's native code, after the author
has reviewed the exact changes and approved them, writes outside the workspace. Browser-only
mode can show a proposal but cannot publish it.

Which proposals have been published is read from the app's own audit log, the record the
app writes when it publishes. Reading it is what puts a published proposal below the ones
still waiting. Nothing here writes that log, so the backend cannot make a proposal look
published, or unpublished, or carry one out.

Proposal file:
    {"title": "...", "destination_root": "/abs/path",
     "operations": [{"path": "docs/A.md", "action": "write", "source": "consolidated/A.md",
                     "expect": "sha256:<hex>" | "absent"},
                    {"path": "docs/B.md", "action": "delete", "expect": "sha256:<hex>"}]}
`source` is relative to the run folder. `path` is relative to `destination_root`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Any

from backend import workspace

# The app's own record of what it published, read to order the list. Written only by the
# desktop app, in its own support folder, and never by this module.
AUDIT = Path.home() / "Library" / "Application Support" / "Research" / "publication-audit.jsonl"
MAX_OPERATIONS = 32
MAX_FILE_BYTES = 2_000_000
TTL_SECONDS = 600
ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SEGMENT = re.compile(r"^[^\x00-\x1f/\\]+$")


class ProposalError(ValueError):
    pass


def _folder(run: str) -> Path:
    return workspace.run_dir(run) / "publications"


def _target_path(raw: object) -> str:
    if not isinstance(raw, str) or not raw or raw.startswith("/") or len(raw) > 512:
        raise ProposalError(f"not a relative path: {raw!r}")
    parts = raw.split("/")
    if any(p in ("", ".", "..") or not SEGMENT.match(p) for p in parts):
        raise ProposalError(f"path not allowed: {raw!r}")
    return "/".join(parts)


def _source(run_dir: Path, raw: object) -> bytes:
    if not isinstance(raw, str) or not raw:
        raise ProposalError("an operation needs a source file")
    path = (run_dir / raw)
    if ".." in Path(raw).parts or Path(raw).is_absolute():
        raise ProposalError(f"source leaves the project: {raw}")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ProposalError(f"source is not a plain file: {raw}")
    if not path.resolve().is_relative_to(run_dir.resolve()):
        raise ProposalError(f"source leaves the project: {raw}")
    if info.st_size > MAX_FILE_BYTES:
        raise ProposalError(f"source too large: {raw}")
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProposalError(f"source is not UTF-8 text: {raw}") from exc
    if "\x00" in text:
        raise ProposalError(f"source contains NUL: {raw}")
    return data


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _audit_lines() -> list[dict[str, Any]]:
    """The desktop app's audit log, or [] when there is none (no app, nothing published)."""
    try:
        text = AUDIT.read_text("utf-8")
    except (OSError, ValueError):
        return []
    out = []
    for line in text.splitlines():
        if line.strip():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def published_times(run: str) -> dict[str, str]:
    """{proposal id: when it was published} for this run, from the app's audit log.

    The log holds an `approved` record naming the run and proposal, then a `published`
    record carrying the same request id once the files are written. A proposal that was
    approved but whose write failed is not published and is not listed here.
    """
    approved: dict[str, str] = {}
    for row in _audit_lines():
        if row.get("event") == "approved" and row.get("run") == run:
            request, proposal = row.get("request"), row.get("proposal")
            if isinstance(request, str) and isinstance(proposal, str) and ID.match(proposal):
                approved[request] = proposal
    out: dict[str, str] = {}
    for row in _audit_lines():
        if row.get("event") == "published":
            proposal = approved.get(str(row.get("request")))
            if proposal:
                out[proposal] = str(row.get("time", ""))
    return out


def list_proposals(run: str) -> list[dict[str, Any]]:
    """Every proposal, those still waiting first and the published ones after them."""
    folder = _folder(run)
    if not folder.is_dir():
        return []
    found = []
    done = published_times(run)
    for path in sorted(folder.glob("*.json")):
        if not ID.match(path.stem):
            continue
        published = done.get(path.stem, "")
        try:
            raw = json.loads(path.read_text("utf-8"))
            found.append(
                {
                    "id": path.stem,
                    "title": str(raw.get("title", path.stem))[:200],
                    "destination_root": str(raw.get("destination_root", "")),
                    "operations": len(raw.get("operations", [])),
                    "published": published,
                }
            )
        except (OSError, ValueError, AttributeError):
            found.append({"id": path.stem, "title": path.stem, "destination_root": "",
                          "operations": 0, "invalid": True, "published": published})
    # Waiting proposals first, newest published last: the list a reader works down.
    found.sort(key=lambda p: (bool(p["published"]), p["published"], p["id"]))
    return found


def snapshot(run: str, proposal_id: str) -> dict[str, Any]:
    """Validate a proposal and return the bytes it would write. Reads only."""
    if not ID.match(proposal_id):
        raise ProposalError("not a proposal id")
    run_dir = workspace.run_dir(run)
    path = _folder(run) / f"{proposal_id}.json"
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise ProposalError(f"cannot read proposal {proposal_id}") from exc
    root = raw.get("destination_root")
    if not isinstance(root, str) or not os.path.isabs(root) or ".." in Path(root).parts:
        raise ProposalError("destination_root must be an absolute path")
    ops_in = raw.get("operations")
    if not isinstance(ops_in, list) or not 1 <= len(ops_in) <= MAX_OPERATIONS:
        raise ProposalError(f"a proposal has 1 to {MAX_OPERATIONS} operations")
    seen: set[str] = set()
    ops: list[dict[str, Any]] = []
    for item in ops_in:
        if not isinstance(item, dict):
            raise ProposalError("operation is not an object")
        rel = _target_path(item.get("path"))
        if rel.lower() in seen:
            raise ProposalError(f"duplicate target: {rel}")
        seen.add(rel.lower())
        action = item.get("action")
        expect = item.get("expect")
        if expect != "absent" and not (isinstance(expect, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", expect)):
            raise ProposalError(f"{rel}: expect must be 'absent' or a sha256 digest")
        if action == "write":
            data = _source(run_dir, item.get("source"))
            ops.append(
                {"path": rel, "action": "write", "expect": expect, "sha256": _digest(data),
                 "content": base64.b64encode(data).decode("ascii")}
            )
        elif action == "delete":
            if expect == "absent":
                raise ProposalError(f"{rel}: cannot delete a file expected to be absent")
            ops.append({"path": rel, "action": "delete", "expect": expect})
        else:
            raise ProposalError(f"{rel}: action must be write or delete")
    now = int(time.time())
    body = {
        "version": 1,
        "run": run,
        "proposal": proposal_id,
        "title": str(raw.get("title", proposal_id))[:200],
        "destination_root": root,
        "operations": ops,
        "issued": now,
        "expires": now + TTL_SECONDS,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    body["request_id"] = hashlib.sha256(canonical).hexdigest()[:32]
    return body
