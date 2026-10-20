"""An app save remains attributable through an editorial round."""

import json
import sys
import subprocess
from pathlib import Path

from backend import edit_state

SCRIPTS = Path(__file__).resolve().parents[2] / ".claude" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import section_guard  # noqa: E402
import saved_check  # noqa: E402
import voice  # noqa: E402


def test_author_edit_survives_agent_writes_and_closes(tmp_path, monkeypatch):
    doc = tmp_path / "report.md"
    baseline = "# Report\n\n## Findings\nThe old framing.\n"
    author = "# Report\n\n## Introduction\nI want this report to begin with the people affected.\n\n## Findings\nThe old framing.\n"
    doc.write_text(baseline)
    mirror = tmp_path / ".voice-mirror-report.md"
    mirror.write_text(baseline)

    edit_state.record(doc, author)
    doc.write_text(author)
    mirror.write_text(author)  # the failure that previously hid the Introduction
    assert edit_state.pending(doc)
    assert saved_check.check(tmp_path, doc=doc) == 0
    assert edit_state.base_path(doc).read_text() == baseline

    doc.write_text(author.replace("The old framing.", "The integrated framing."))
    assert edit_state.active(doc) and not edit_state.pending(doc)
    assert "## Introduction" not in section_guard.snapshot_of(
        edit_state.base_path(doc).read_text())
    checked = subprocess.run(
        [sys.executable, str(SCRIPTS / "section_guard.py"), "check", str(doc),
         "--allow", "Introduction", "--allow", "Findings"],
        capture_output=True, text=True,
    )
    assert checked.returncode == 0 and "ADDED    ## Introduction" in checked.stdout

    monkeypatch.setattr(voice, "CORPUS", tmp_path / "corpus")
    assert voice.learn(doc, slug="test") == 0
    corpus = next(voice.CORPUS.glob("*.md"))
    assert "I want this report to begin with the people affected." in corpus.read_text()
    assert "The integrated framing." not in corpus.read_text()
    first = corpus.read_text()
    assert voice.learn(doc, slug="test") == 0
    assert corpus.read_text() == first

    (tmp_path / ".guard-report.json").write_text(
        json.dumps(section_guard.snapshot_of(doc.read_text()))
    )
    edit_state.acknowledge(doc)
    assert not edit_state.active(doc) and not edit_state.pending(doc)
    assert subprocess.run(
        [sys.executable, str(SCRIPTS / "section_guard.py"), "check", str(doc)],
        capture_output=True,
    ).returncode == 0


def test_repeated_author_save_keeps_first_baseline(tmp_path):
    doc = tmp_path / "report.md"
    doc.write_text("# Original\n")
    (tmp_path / ".voice-mirror-report.md").write_text(doc.read_text())
    edit_state.record(doc, "# Revised\n")
    doc.write_text("# Revised\n")
    edit_state.record(doc, "# Revised again\n")
    doc.write_text("# Revised again\n")
    assert edit_state.base_path(doc).read_text() == "# Original\n"
    assert edit_state.saved_path(doc).read_text() == "# Revised again\n"


def test_external_editor_save_is_frozen_before_agent_write(tmp_path):
    doc = tmp_path / "report.md"
    mirror = tmp_path / ".voice-mirror-report.md"
    mirror.write_text("# Original\n")
    doc.write_text("# Author's revision\n")
    edit_state.capture_existing(doc)
    mirror.write_text(doc.read_text())
    doc.write_text("# Integrated revision\n")
    assert edit_state.active(doc) and not edit_state.pending(doc)
    assert edit_state.base_path(doc).read_text() == "# Original\n"
    assert edit_state.saved_path(doc).read_text() == "# Author's revision\n"
