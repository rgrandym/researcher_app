"""Durable provenance for report edits saved through the Research app.

The agent mirror can be updated after a save. Keep the last agent text from
before the first author save, and the exact latest author save, separately.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def state_path(doc: Path) -> Path:
    return doc.parent / f".user-edit-{doc.stem}.json"


def base_path(doc: Path) -> Path:
    return doc.parent / f".user-edit-{doc.stem}-base.md"


def saved_path(doc: Path) -> Path:
    return doc.parent / f".user-edit-{doc.stem}-saved.md"


def active(doc: Path) -> bool:
    """A complete author save is awaiting explicit editorial closeout."""
    try:
        state = json.loads(state_path(doc).read_text())
        return (state.get("active", True) and base_path(doc).is_file()
                and saved_path(doc).is_file()
                and _hash(base_path(doc).read_text()) == state["base_sha256"]
                and _hash(saved_path(doc).read_text()) == state["saved_sha256"]
                and state["base_sha256"] != state["saved_sha256"])
    except (OSError, ValueError, KeyError):
        return False


def pending(doc: Path) -> bool:
    """The master still contains the exact author save awaiting integration."""
    return active(doc) and doc.is_file() and _hash(doc.read_text()) == json.loads(
        state_path(doc).read_text())["saved_sha256"]


def record(doc: Path, content: str) -> None:
    """Record an author save without replacing the first agent baseline."""
    mirror = doc.parent / f".voice-mirror-{doc.stem}.md"
    if not doc.is_file() or doc.read_text() == content:
        return
    if not active(doc):
        baseline = mirror.read_text() if mirror.is_file() else doc.read_text()
        base_path(doc).write_text(baseline)
    saved_path(doc).write_text(content)
    state_path(doc).write_text(json.dumps({
        "active": True,
        "base_sha256": _hash(base_path(doc).read_text()),
        "saved_sha256": _hash(content),
    }) + "\n")


def capture_existing(doc: Path) -> None:
    """Freeze a save made in an external editor before the agent touches it."""
    if active(doc):
        return
    mirror = doc.parent / f".voice-mirror-{doc.stem}.md"
    if not doc.is_file() or not mirror.is_file():
        raise ValueError(f"no document or agent baseline for {doc}")
    baseline, saved = mirror.read_text(), doc.read_text()
    if baseline == saved:
        raise ValueError(f"no text changes since the agent baseline for {doc}")
    base_path(doc).write_text(baseline)
    saved_path(doc).write_text(saved)
    state_path(doc).write_text(json.dumps({
        "active": True,
        "base_sha256": _hash(baseline),
        "saved_sha256": _hash(saved),
    }) + "\n")


def acknowledge(doc: Path) -> None:
    """Close a checked /user-edits round; retain its saved copies for audit."""
    if not active(doc) or not doc.is_file():
        raise ValueError(f"no active author edit for {doc}")
    state = json.loads(state_path(doc).read_text())
    state["active"] = False
    state["integrated_sha256"] = _hash(doc.read_text())
    state_path(doc).write_text(json.dumps(state) + "\n")


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"inspect", "capture", "acknowledge"}:
        print("usage: edit_state.py inspect|capture|acknowledge <run>/report.md", file=sys.stderr)
        return 2
    doc = Path(sys.argv[2])
    if sys.argv[1] in {"capture", "acknowledge"}:
        try:
            if sys.argv[1] == "capture":
                capture_existing(doc)
            else:
                acknowledge(doc)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(f"{sys.argv[1]}d author edit for {doc}")
        return 0
    print(json.dumps({"active": active(doc), "pending": pending(doc),
                      "baseline": str(base_path(doc)), "saved": str(saved_path(doc)),
                      "master": str(doc)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
