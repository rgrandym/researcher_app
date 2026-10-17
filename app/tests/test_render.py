"""Reports as HTML, edits to the Markdown, and removing a project."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from conftest import RUN

from backend import appearance, render, workspace


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


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_report_appearance_changes_preview_and_resets(root: Path) -> None:
    _report(root)
    first = render.preview(RUN, None, "graphite", False)
    values = appearance.defaults("graphite")
    values["color"]["link"] = "#697783"
    values["series"][0] = "#233D52"
    values["fonts"]["base_pt"] = 11
    values["chart"]["line_style"] = "dashed"
    values["chart"]["bar_corner_radius_px"] = 6
    appearance.save(RUN, "graphite", values)
    changed = render.preview(RUN, None, "graphite", False)
    assert not changed["cached"]
    assert changed["built"] > first["built"]
    assert changed["html"] == first["html"]
    css = Path(changed["html"]).with_name("style.css").read_text()
    assert "#697783" in css and "11.0pt" in css
    assert appearance.effective(RUN, "graphite")["chart"]["line_style"] == "dashed"
    assert appearance.effective(RUN, "meridian") is None
    assert render.preview(RUN, None, "graphite", False)["cached"]
    appearance.reset(RUN)
    restored = render.preview(RUN, None, "graphite", False)
    assert not restored["cached"] and restored["built"] > changed["built"]


def test_report_appearance_rejects_invalid_values(root: Path) -> None:
    values = appearance.defaults("graphite")
    values["color"]["link"] = "red; background: orange"
    with pytest.raises(ValueError):
        appearance.save(RUN, "graphite", values)
    assert not (root / "outputs" / RUN / appearance.FILE).exists()


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_individual_figure_and_table_appearance(root: Path) -> None:
    doc = _report(root)
    doc.write_text('''# Lithium costs

```figure
{"id":"F1","type":"bar","title":"Price trend","source":"[E1]","categories":["2024","2025"],"values":[12,9]}
```

**Table:** Prices by year {#T1}

| Year | Price |
|---|---:|
| 2024 | 12 |
| 2025 | 9 |
''')
    found = appearance.available(RUN)
    assert found["figures"][0]["id"] == "F1" and found["tables"][0]["id"] == "T1"
    values = appearance.defaults("graphite")
    values["items"]["figures"]["F1"] = {
        "series": ["#123ABC", *values["series"][1:]],
        "grid": "#B9C3CE", "axis": "#506070", "background": "#FFFFFF",
        "line_width": 3, "line_style": "dashed", "bar_width": 0.4, "bar_corner_radius_px": 5,
        "marker_size": 5, "font_scale": 1.1, "value_labels": False,
        "heading_font": "Inter", "body_font": "Georgia",
    }
    values["items"]["tables"]["T1"] = {
        "header_bg": "#E7EDF2", "header_fg": "#123456", "border": "#536477",
        "font_size_pt": 8.5, "cell_padding_em": 0.3, "rule_weight_pt": 1,
        "font_family": "Georgia", "width_percent": 75,
    }
    appearance.save(RUN, "graphite", values)
    result = render.preview(RUN, None, "graphite", False)
    html = Path(result["html"]).read_text()
    css = Path(result["html"]).with_name("style.css").read_text()
    svg = (Path(result["html"]).parent.parent / "figures" / "F1.svg").read_text()
    assert 'id="report-table-T1"' in html
    assert "#report-table-T1" in css and "#E7EDF2" in css and "width: 75.0%" in css
    assert "#123abc" in svg.lower()


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
