"""Reports as HTML, edits to the Markdown, and removing a project."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from conftest import RUN

from backend import appearance, edit_state, render, workspace


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
    mirror = doc.parent / ".voice-mirror-report.md"
    mirror.write_text(doc.read_text())
    loaded = doc.stat().st_mtime
    mtime = workspace.save_run_file(RUN, "report.md", "# Edited\n", loaded)
    assert doc.read_text() == "# Edited\n"
    assert edit_state.pending(doc)
    assert edit_state.base_path(doc).read_text() == mirror.read_text()
    with pytest.raises(workspace.Conflict):
        workspace.save_run_file(
            RUN, "report.md", "# Older tab\n", loaded - 5
        )  # someone saved since
    assert doc.read_text() == "# Edited\n"
    assert workspace.save_run_file(RUN, "report.md", "# Again\n", mtime)
    assert edit_state.base_path(doc).read_text() == mirror.read_text()
    # A later agent mirror must not erase the author's saved edit record.
    mirror.write_text(doc.read_text())
    assert edit_state.pending(doc)
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


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_tables_charts_and_page_are_styled_apart(root: Path) -> None:
    doc = _report(root)
    doc.write_text('''# Lithium costs

**Table:** Costs {#T9}

| Year | Cost |
|---|---:|
| 2024 | 12 |

**Table:** Prices by year {#T1}

| Year | Price |
|---|---:|
| 2024 | 12 |
''')
    # Numbers follow document order, as the rendered captions give them, not the ids.
    found = appearance.available(RUN)["tables"]
    assert [(t["id"], t["number"]) for t in found] == [("T9", 1), ("T1", 2)]
    values = appearance.defaults("meridian")
    before = dict(values["table"])
    values["color"]["ink"] = "#FFFFFF"  # the page's headings, white
    values["table"]["header_font_size_pt"] = 12
    values["items"]["tables"]["T1"] = {**{k: v for k, v in before.items() if k != "header_font"},
                                        "caption_fg": "#123456", "header_font_size_pt": 13}
    appearance.save(RUN, "meridian", values)
    result = render.preview(RUN, None, "meridian", False)
    html = Path(result["html"]).read_text()
    css = Path(result["html"]).with_name("style.css").read_text()
    tables = css[css.index("/* Tables and captions"):]
    assert f"color: {before['caption_fg']}" in tables and f"color: {before['header_fg']}" in tables
    assert "font-size: 12.0pt" in tables and "#report-caption-T1, #report-caption-T1 strong" in tables
    assert 'class="table-caption" id="report-caption-T1"' in html
    assert appearance.effective(RUN, "meridian")["chart"]["title_color"] == before["caption_fg"]


def test_saves_from_before_keep_their_look(root: Path) -> None:
    _report(root)
    values = appearance.defaults("graphite")
    values["color"]["body"] = "#333333"
    values["table"] = {"border": "#AAAAAA", "rule_weight_pt": 0.8}
    values["chart"] = {k: v for k, v in values["chart"].items() if k not in appearance.CHART_TEXT and k not in appearance.CHART_FONTS}
    values["items"]["tables"]["T1"] = {
        "header_bg": "#E7EDF2", "header_fg": "#123456", "border": "#536477",
        "font_size_pt": 8.5, "cell_padding_em": 0.3, "rule_weight_pt": 1,
        "font_family": "Georgia", "width_percent": 75,
    }
    clean = appearance.validate("graphite", values)
    assert clean["table"]["body_fg"] == "#333333" and clean["chart"]["text_color"] == "#333333"
    assert clean["items"]["tables"]["T1"]["header_font_size_pt"] == 8.5


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_every_table_is_numbered_and_each_document_has_its_own(root: Path) -> None:
    _report(root)
    plan = root / "outputs" / RUN / "plan.md"
    plan.write_text('''# Plan

Royalties are set out below.

| Medium | Royalty |
|---|---:|
| E8 | £27 |

<!-- T1 -->
| Cost | Total |
|---|---:|
| Salary | £140k |
''')
    found = appearance.view(RUN, "graphite", "plan.md")["available"]["tables"]
    assert [(t["number"], t["captioned"]) for t in found] == [(1, False), (2, False)]
    first = found[0]["id"]
    values = appearance.view(RUN, "graphite", "plan.md")["values"]
    values["items"]["tables"][first] = {"header_bg": "#B45309", "header_fg": "#FFFFFF", "header_font_size_pt": 12}
    appearance.save(RUN, "graphite", values, False, "plan.md")
    assert appearance.view(RUN, "graphite")["values"]["items"]["tables"] == {}  # the primary's are apart
    result = render.build(RUN, "plan.md", "graphite", False, root / "o", root / "f")
    html = result["html"].read_text()
    assert "<strong>Table 1.</strong>" in html and "<strong>Table 2.</strong>" in html
    assert f'id="report-table-{first}"' in html and "**Table:**" not in plan.read_text()
    new_id = appearance.add_caption(RUN, "plan.md", first, "Royalty per litre")
    assert new_id == "T2"  # T1 is the revised document's own table marker
    assert "**Table:** Royalty per litre {#T2}\n\n| Medium" in plan.read_text()
    after = appearance.view(RUN, "graphite", "plan.md")
    assert after["available"]["tables"][0] == {"id": "T2", "number": 1, "label": "Royalty per litre", "captioned": True}
    assert after["values"]["items"]["tables"]["T2"]["header_bg"] == "#B45309"


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_captions_sit_below_in_small_type_and_charts_fit_the_text(root: Path) -> None:
    doc = _report(root)
    doc.write_text('''# Lithium costs

```figure
{"id":"F1","type":"bar","title":"Price trend","source":"[E1]","categories":["2024","2025"],"values":[12,9]}
```

**Table:** Prices by year {#T1}

| Year | Price |
|---|---:|
| 2024 | 12 |

Text after.
''')
    result = render.build(RUN, None, "meridian", False, root / "o", root / "f")
    html = result["html"].read_text()
    assert html.index('id="report-table-T1"') < html.index('id="report-caption-T1"') < html.index("Text after")
    assert result["table_sides"] == {"T1": "below"}
    css = (root / "o" / "style.css").read_text()
    assert "p.table-caption, p.table-caption strong { font-size: 6.0pt; }" in css
    assert "figure img { display: block; width: 100%;" in css
    assert "{width=100%}" in (root / "o" / "_styled.md").read_text()
    assert "**Table:** Prices by year {#T1}\n\n| Year" in doc.read_text()  # the document keeps its layout


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_documents_render_apart_even_with_one_name(root: Path) -> None:
    run = root / "outputs" / RUN
    (run / "templates").mkdir()
    (run / "templates/note.md").write_text("# Note template\n\n[FILL] the result.\n")
    (run / "note.md").write_text("# Note\n\nThe finished note.\n")
    template = Path(render.preview(RUN, "templates/note.md", "meridian", False)["html"]).read_text()
    assert "[FILL] the result." in template
    finished = render.preview(RUN, "note.md", "meridian", False)
    assert not finished["cached"] and "The finished note." in Path(finished["html"]).read_text()
    # Each document keeps its own page: showing one does not rebuild or overwrite the other.
    again = render.preview(RUN, "templates/note.md", "meridian", False)
    assert again["cached"] and "[FILL] the result." in Path(again["html"]).read_text()
