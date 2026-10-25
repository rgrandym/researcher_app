"""Comments on a report: anchored from the HTML, found again after edits, carried into
HTML, PDF and Word; and tables styled individually in Word."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

import pytest
from conftest import RUN

from backend import appearance, comments, render

REPORT = """# Lithium costs

## Prices

Battery-grade lithium costs **less each year** [E1], and spot prices fell in 2025 [E2].
Producers expect the decline to slow.

```figure
{"id":"F1","type":"bar","title":"Price trend","source":"[E1]","categories":["2024","2025"],"values":[12,9]}
```

**Table:** Prices by year [E1] {#T1}

| Year | Price |
|---|---:|
| 2024 | 12 |
| 2025 | 9 |

## Outlook

Spot prices fell in 2025 again, by a smaller margin.

## Sources
"""


def _report(root: Path) -> Path:
    doc = root / "outputs" / RUN / "report.md"
    doc.write_text(REPORT)
    return doc


def test_selection_from_the_html_anchors_to_the_markdown(root: Path) -> None:
    _report(root)
    # The rendered page shows no ** and an author-year citation where [E1] stands.
    made = comments.create(
        RUN,
        "report.md",
        "Say by how much.",
        "R G",
        selection={
            "text": "costs less each year (Smith 2025), and spot",
            "prefix": "Battery-grade lithium ",
            "suffix": " prices",
            "heading": "Prices",
        },
    )
    assert made["quote"] == "costs **less each year** [E1], and spot"
    # The same words twice: the heading decides which.
    later = comments.create(
        RUN,
        "report.md",
        "Check the date.",
        "R G",
        selection={"text": "Spot prices fell in 2025", "heading": "Outlook"},
    )
    md = REPORT
    start = md.index(later["quote"], md.index("## Outlook"))
    assert later["prefix"].endswith(md[start - 10 : start])


def test_figures_and_tables_by_number(root: Path) -> None:
    _report(root)
    fig = comments.create(
        RUN, "report.md", "Use a line chart.", "", element={"kind": "figure", "number": 1}
    )
    table = comments.create(
        RUN, "report.md", "Add 2026.", "", element={"kind": "table", "number": 1}
    )
    assert fig["target"] == "F1" and fig["author"] == "Author"
    assert table["target"] == "T1" and table["quote"] == "Prices by year [E1]"
    with pytest.raises(comments.AnchorError):
        comments.create(RUN, "report.md", "x", "", element={"kind": "table", "number": 4})


def test_a_comment_follows_its_passage_and_reports_a_lost_one(root: Path) -> None:
    doc = _report(root)
    kept = comments.create(
        RUN, "report.md", "Source?", "", selection={"text": "Producers expect the decline to slow"}
    )
    lost = comments.create(RUN, "report.md", "Why?", "", selection={"text": "by a smaller margin"})
    doc.write_text(
        REPORT.replace(
            "Producers expect the decline to slow.",
            "Most producers now expect the decline to slow sharply.",
        ).replace("Spot prices fell in 2025 again, by a smaller margin.", "No outlook yet.")
    )
    listed = {c["id"]: c for c in comments.listing(RUN, "report.md")}
    assert (
        listed[kept["id"]]["found"] and "expect the decline to slow" in listed[kept["id"]]["quote"]
    )
    assert not listed[lost["id"]]["found"]  # shown as lost, never deleted
    stored = json.loads((root / "outputs" / RUN / comments.FILE).read_text())["comments"]
    assert len(stored) == 2


def test_selection_across_table_rows_is_refused(root: Path) -> None:
    _report(root)
    with pytest.raises(comments.AnchorError):
        comments.create(RUN, "report.md", "x", "", selection={"text": "2024 12 2025"})


def test_inject_strip_and_heading_ids() -> None:
    md = "## Prices now\n\nSome [text] here.\n"
    items = [
        {
            "id": "a1",
            "kind": "text",
            "quote": "Prices",
            "text": "Rename [it]",
            "author": "R",
            "created": "2026-10-25T10:00:00Z",
        },
        {
            "id": "b2",
            "kind": "text",
            "quote": "[text] here",
            "text": "Fine | ok",
            "author": "R",
            "created": "2026-10-25T10:00:00Z",
        },
    ]
    out, placed = comments.inject(md, items)
    assert set(placed) == {"0", "1"}
    assert out.startswith(
        '## <span class="comment-start" id="0" author="R" date="2026-10-25T10:00:00Z">Rename \\[it\\]</span>'
        'Prices<span class="comment-end" id="0"></span> now {#prices-now}'
    )
    assert "Fine \\| ok" in out
    assert comments.strip(out) == md.replace("## Prices now", "## Prices now {#prices-now}")


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_comments_render_as_highlights_and_word_comments(root: Path) -> None:
    _report(root)
    note = comments.create(
        RUN, "report.md", "Say by how much.", "R G", selection={"text": "costs less each year"}
    )
    comments.create(
        RUN, "report.md", "Use a line chart.", "R G", element={"kind": "figure", "number": 1}
    )
    comments.create(RUN, "report.md", "Add 2026.", "R G", element={"kind": "table", "number": 1})
    preview = render.preview(RUN, None, "meridian", False)
    html = Path(preview["html"]).read_text()
    assert f'<mark class="cmt" data-c="{note["id"]}">' in html
    assert html.count('class="cmt-note"') == 3 and "comment-start" not in html
    toc = html[html.index('<nav id="TOC"') : html.index("</nav>")]
    assert "Say by how much" not in toc
    # A new comment changes the preview.
    comments.update(RUN, note["id"], resolved=True)
    assert not render.preview(RUN, None, "meridian", False)["cached"]
    comments.update(RUN, note["id"], resolved=False)

    result = render.export(RUN, None, "meridian", False, ["docx", "html"])
    docx = root / next(f for f in result["files"] if f.endswith(".docx"))
    with zipfile.ZipFile(docx) as z:
        notes = z.read("word/comments.xml").decode()
        body = z.read("word/document.xml").decode()
    assert "Say by how much." in notes and "Use a line chart." in notes and "Add 2026." in notes
    assert 'w:author="R G"' in notes and body.count("<w:commentRangeStart") == 3
    assert result["comments"] == 3
    # Without comments, nothing of them reaches the files, and the loss check counts the same.
    clean = render.export(RUN, None, "meridian", False, ["docx", "html"], with_comments=False)
    counted = re.compile(r"report\.docx: .*?(\d+) words")
    assert counted.findall(result["check"]) == counted.findall(clean["check"])
    with zipfile.ZipFile(root / next(f for f in clean["files"] if f.endswith(".docx"))) as z:
        assert (
            "word/comments.xml" not in z.namelist()
            or "Say by how much" not in z.read("word/comments.xml").decode()
        )
    assert (
        "cmt-note"
        not in (root / next(f for f in clean["files"] if f.endswith(".html"))).read_text()
    )


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_table_line_type_and_layout_reach_html_and_word(root: Path) -> None:
    _report(root)
    values = appearance.defaults("meridian")
    values["items"]["tables"]["T1"] = {
        "header_bg": "#1F3A5F",
        "header_fg": "#FFFFFF",
        "border": "#8899AA",
        "font_size_pt": 9,
        "cell_padding_em": 0.4,
        "rule_weight_pt": 0.75,
        "font_family": "Georgia",
        "width_percent": 80,
        "rule_style": "dashed",
        "borders": "grid",
    }
    appearance.save(RUN, "meridian", values)
    css = (
        Path(render.preview(RUN, None, "meridian", False)["html"])
        .with_name("style.css")
        .read_text()
    )
    assert "#report-table-T1 th, #report-table-T1 td { border: 0.75pt dashed #8899AA; }" in css
    result = render.export(RUN, None, "meridian", False, ["docx"])
    with zipfile.ZipFile(root / result["files"][0]) as z:
        body = z.read("word/document.xml").decode()
    assert 'w:insideV w:val="dashed" w:sz="6"' in body and 'w:fill="1F3A5F"' in body
    assert 'w:ascii="Georgia"' in body
    bad = dict(values["items"]["tables"]["T1"], rule_style="wavy")
    values["items"]["tables"]["T1"] = bad
    with pytest.raises(ValueError):
        appearance.validate("meridian", values)


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_live_render_shows_unsaved_text_and_leaves_the_run_alone(root: Path) -> None:
    doc = _report(root)
    before = doc.read_text()
    result = render.live(
        RUN, None, "meridian", False, REPORT.replace("Producers expect", "Analysts expect")
    )
    assert "Analysts expect" in Path(result["html"]).read_text()
    assert doc.read_text() == before
    assert Path(result["html"]).is_relative_to(render.cache_dir(RUN, "meridian", False))


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_a_caption_below_its_table_still_names_and_styles_it(root: Path) -> None:
    doc = _report(root)
    doc.write_text(
        "# Lithium\n\n| Year | Price |\n|---|---:|\n| 2024 | 12 |\n\n**Table:** Prices below [E1] {#T1}\n\n"
        "**Table:** Volumes above {#T2}\n\n| Year | Tonnes |\n|---|---:|\n| 2024 | 5 |\n"
    )
    assert appearance.table_sides(doc.read_text()) == {"T1": "below", "T2": "above"}
    html = Path(render.preview(RUN, None, "meridian", False)["html"]).read_text()
    assert html.count('id="report-table-T1"') == 1 and html.count('id="report-table-T2"') == 1
    assert html.index('id="report-table-T1"') < html.index("Prices below")
    made = comments.create(
        RUN, "report.md", "Merge them.", "", element={"kind": "table", "id": "T1"}
    )
    assert made["target"] == "T1"
    values = appearance.defaults("meridian")
    look = {
        "header_bg": "#0F4C81",
        "header_fg": "#FFFFFF",
        "border": "#9FB3C8",
        "font_size_pt": 9,
        "cell_padding_em": 0.4,
        "rule_weight_pt": 0.5,
        "font_family": "Georgia",
        "width_percent": 100,
    }
    values["items"]["tables"]["T1"] = look
    appearance.save(RUN, "meridian", values)
    result = render.export(RUN, None, "meridian", False, ["docx"])
    with zipfile.ZipFile(root / result["files"][0]) as z:
        body = z.read("word/document.xml").decode()
    first_table = body[body.index("<w:tbl>") : body.index("</w:tbl>")]
    assert 'w:fill="0F4C81"' in first_table


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_highlights_show_in_the_app_and_stay_out_of_exports(root: Path) -> None:
    _report(root)
    mark = comments.create(
        RUN,
        "report.md",
        "",
        "R G",
        selection={"text": "Producers expect the decline"},
        highlight=True,
        color="green",
    )
    assert mark["type"] == "highlight" and mark["text"] == ""
    with pytest.raises(ValueError):
        comments.create(
            RUN,
            "report.md",
            "",
            "",
            selection={"text": "spot prices"},
            highlight=True,
            color="purple",
        )
    note = comments.create(RUN, "report.md", "Why?", "", selection={"text": "costs less each year"})
    html = Path(render.preview(RUN, None, "meridian", False)["html"]).read_text()
    assert f'<mark class="hl hl-green" data-c="{mark["id"]}">' in html
    assert html.count('class="cmt-note"') == 1 and "hl-start" not in html
    result = render.export(RUN, None, "meridian", False, ["docx", "html"])
    assert result["comments"] == 1
    exported = (root / next(f for f in result["files"] if f.endswith(".html"))).read_text()
    assert mark["id"] not in exported and note["id"] in exported
    # Words turn a highlight into a comment.
    assert comments.update(RUN, mark["id"], text="Check this")["type"] == "comment"
