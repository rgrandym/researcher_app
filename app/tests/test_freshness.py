"""Exports and delivered files made again when their document changes, as they were last made."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

import pytest
from conftest import RUN

from backend import freshness, render, sessions
from backend.turns import TurnManager


def _age(path: Path, seconds: float = 60) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_an_edited_document_is_exported_again_the_same_way(root: Path) -> None:
    run = root / "outputs" / RUN
    (run / "templates").mkdir()
    doc = run / "templates/note.md"
    doc.write_text("# Note\n\nThe market is USD 868 million.\n")
    render.export(RUN, "templates/note.md", "meridian", False, ["docx"], False)
    record = json.loads((run / "export/meridian/.note.export.json").read_text())
    assert record == {"doc": "templates/note.md", "cite": False, "comments": False, "formats": ["docx"]}
    assert freshness.stale(RUN) == []
    for f in (run / "export/meridian").glob("note.*"):
        _age(f)
    doc.write_text("# Note\n\nThe market is USD 765 million.\n")
    [item] = freshness.stale(RUN)
    assert item["doc"] == "templates/note.md" and item["kind"] == "export" and not item["blocked"]
    [result] = freshness.refresh(RUN, {"templates/note.md"})
    assert result["problem"] is None and any(f.endswith("note.docx") for f in result["files"])
    assert "765" in (run / "export/meridian/note.html").read_text()
    assert freshness.stale(RUN) == []


def _deck(run: Path, applied: bool) -> Path:
    (run / ".run.json").write_text(json.dumps({"documents": [{"slug": "deck", "master": "deck.md"}]}))
    version = run / "deliverable/deck/v3"
    version.mkdir(parents=True)
    native = version / "Deck V19.pptx"
    native.write_bytes(b"not opened here")
    if applied:
        (version / "applied.json").write_text(json.dumps({"from": "deck.md", "design": "preserve"}))
    _age(native)
    (run / "deck.md").write_text("# Deck\n")
    return native


def test_a_delivered_file_made_outside_the_editor_is_reported_not_replaced(root: Path) -> None:
    run = root / "outputs" / RUN
    native = _deck(run, applied=False)
    [item] = freshness.stale(RUN)
    assert item["files"] == ["deliverable/deck/v3/Deck V19.pptx"] and "outside the editor" in item["blocked"]
    [result] = freshness.refresh(RUN)
    assert result["files"] == [] and "outside the editor" in result["problem"]
    assert sorted(p.name for p in native.parent.parent.iterdir()) == ["v3"]  # no new version


def test_a_delivered_file_the_editor_made_repeats_its_design(root: Path) -> None:
    _deck(root / "outputs" / RUN, applied=True)
    [item] = freshness.stale(RUN)
    assert item["blocked"] is None and item["settings"]["design"] == "preserve" and item["settings"]["formats"] == ["pptx"]


def test_the_turn_reports_what_it_could_not_update(root: Path) -> None:
    run = root / "outputs" / RUN
    started = time.time() - 1
    _deck(run, applied=False)
    m = TurnManager({})
    session = sessions.create()
    session.runs = [RUN]
    sessions.save(session)
    asyncio.run(m._refresh_exports(session.id, started))
    notices = [e for e in sessions.transcript(session.id) if e.type == "notice" and e.data.get("kind") == "exports"]
    assert len(notices) == 1
    assert "Your edits to deck.md are saved and show in the HTML tab" in notices[0].data["text"]
