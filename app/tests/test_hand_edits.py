"""Hand edits in the Edit tab: what is pending, Keep as written (no model call), and the
automatic /user-edits switch that is now off by default."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import APP, RUN

from backend import autoedits, config, edit_state

REPORT = """# Lithium costs

## Prices

Battery-grade lithium costs less each year, and spot prices fell in 2025.

```figure
{"id":"F1","type":"bar","title":"Price trend","source":"[E1]","categories":["2024","2025"],"values":[12,9]}
```

## Outlook

Producers expect the decline to slow.
"""


def _agent_wrote(root: Path) -> Path:
    """The report as an agent left it: its mirror recorded by voice.py mark."""
    doc = root / "outputs" / RUN / "report.md"
    doc.write_text(REPORT)
    # voice.py reads the app's edit records through app/backend/edit_state.py.
    backend = root / "app" / "backend"
    backend.mkdir(parents=True, exist_ok=True)
    (backend / "__init__.py").write_text("")
    (backend / "edit_state.py").write_text((APP / "backend" / "edit_state.py").read_text())
    script = root / ".claude" / "scripts" / "voice.py"
    subprocess.run(
        [sys.executable, str(script), "mark", str(doc)], check=True, capture_output=True, cwd=root
    )
    return doc


def _author_saves(doc: Path, text: str) -> None:
    edit_state.record(doc, text)  # as the app's save does
    doc.write_text(text)


def test_nothing_pending_after_an_agent_write(root: Path) -> None:
    _agent_wrote(root)
    assert autoedits.status(RUN, "report.md")["pending"] is False
    with pytest.raises(ValueError):
        autoedits.keep(RUN, "report.md")


def test_a_precise_edit_is_kept_as_written_without_an_agent(root: Path) -> None:
    doc = _agent_wrote(root)
    edited = REPORT.replace(
        "expect the decline to slow", "expect the decline to slow sharply in 2027"
    )
    _author_saves(doc, edited)
    seen = autoedits.status(RUN, "report.md")
    assert seen["pending"] and seen["sections"] == ["Outlook"] and seen["added"] >= 3
    assert seen["notes"] is False and seen["auto"] is False
    autoedits.keep(RUN, "report.md")
    assert doc.read_text() == edited  # the author's text stands, untouched
    assert autoedits.status(RUN, "report.md")["pending"] is False
    assert not edit_state.active(doc)
    assert (doc.parent / ".voice-mirror-report.md").read_text() == edited


def test_notes_for_the_agent_are_recognised(root: Path) -> None:
    doc = _agent_wrote(root)
    _author_saves(
        doc,
        REPORT.replace(
            "## Outlook\n", "## Outlook\n\nTODO: say something about core facilities here\n"
        ),
    )
    assert autoedits.status(RUN, "report.md")["notes"] is True


def test_an_edit_that_breaks_a_check_is_not_kept(root: Path) -> None:
    doc = _agent_wrote(root)
    _author_saves(doc, REPORT.replace('"values":[12,9]', '"values":[12,9,4]'))
    with pytest.raises(autoedits.KeepRefused, match="figures"):
        autoedits.keep(RUN, "report.md")
    assert autoedits.status(RUN, "report.md")["pending"]  # still waiting, nothing lost
    assert edit_state.active(doc)


def test_automatic_user_edits_is_off_by_default(root: Path) -> None:
    assert config.load_settings()["auto_user_edits"]["enabled"] is False
    assert autoedits.Watcher.enabled() is False
