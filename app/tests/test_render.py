"""Reports as HTML, edits to the Markdown, and removing a project."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from conftest import RUN

from backend import render, workspace


def _report(root: Path) -> Path:
    doc = root / "outputs" / RUN / "report.md"
    doc.write_text("# Lithium costs\n\nBattery-grade lithium costs less each year.\n\n## Sources\n")
    return doc


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_preview_renders_and_caches(root: Path) -> None:
    doc = _report(root)
    first = render.preview(RUN, None, "meridian", False)
    html = Path(first["html"])
    assert not first["cached"] and html.is_file() and "Battery-grade lithium" in html.read_text()
    assert render.preview(RUN, None, "meridian", False)["cached"]
    time.sleep(0.01)
    doc.write_text(doc.read_text().replace("less", "much less"))
    again = render.preview(RUN, None, "meridian", False)
    assert not again["cached"] and "much less" in Path(again["html"]).read_text()
    assert not (
        root / "outputs" / RUN / "export" / "meridian" / "report.html"
    ).exists()  # previews stay in the app's cache
    with pytest.raises(ValueError):
        render.preview_file(RUN, "meridian", False, "../../../../etc/hosts")


def test_unknown_style(root: Path) -> None:
    _report(root)
    with pytest.raises(render.RenderError):
        render.build(RUN, None, "no-such-style", False, root / "o", root / "f")


def test_edit_refuses_a_stale_save(root: Path) -> None:
    doc = _report(root)
    loaded = doc.stat().st_mtime
    mtime = workspace.save_run_file(RUN, "report.md", "# Edited\n", loaded)
    assert doc.read_text() == "# Edited\n"
    with pytest.raises(workspace.Conflict):
        workspace.save_run_file(
            RUN, "report.md", "# Older tab\n", loaded - 5
        )  # someone saved since
    assert doc.read_text() == "# Edited\n"
    assert workspace.save_run_file(RUN, "report.md", "# Again\n", mtime)
    for bad in ("evidence.jsonl", "export/meridian/report.md", "../other/report.md"):
        with pytest.raises(ValueError):
            workspace.save_run_file(RUN, bad, "x", None)


def test_remove_moves_to_trash(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    where = Path(workspace.trash_run(RUN))
    assert where.parent == tmp_path / "home" / ".Trash" and (where / "prompt.md").is_file()
    assert not (root / "outputs" / RUN).exists()
    assert workspace.list_runs() == []
