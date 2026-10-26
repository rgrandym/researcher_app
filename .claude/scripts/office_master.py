"""Editable Office masters shared by the app and document.py.

The Markdown contains a fenced office JSON model: typed Excel cells or PowerPoint
text frames and tables. Native objects and design live in an immutable source copy.
Only changed values are applied to that copy; exports never overwrite the source.
"""

import hashlib
import json
import math
import re
import shutil
import tempfile
import warnings
from zipfile import BadZipFile, is_zipfile
from copy import copy
from datetime import date, datetime, time
from difflib import SequenceMatcher
from pathlib import Path

MARKER = "<!-- office-master:1 -->"
FORMATS = {"xlsx", "pptx"}
MAX_CELLS = 100_000


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encode(data):
    return f"{MARKER}\n\n# {data['format'].upper()} document\n\n```office\n" + json.dumps(
        data, ensure_ascii=False, indent=2, allow_nan=False
    ) + "\n```\n"


def decode(text):
    match = re.fullmatch(
        r"<!-- office-master:1 -->\s*# [^\n]+\s+```office\n(.*)\n```\s*", text, re.S
    )
    if not match:
        raise ValueError("Keep the Office master header and its single office block.")
    try:
        data = json.loads(match[1])
    except ValueError as exc:
        raise ValueError(f"The Office content is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("format") not in FORMATS:
        raise ValueError("Unsupported Office master version or format.")
    if data.get("design") not in ("preserve", "new"):
        raise ValueError("Choose preserve or new for the design.")
    return data


def cell_value(cell):
    value = cell.value
    if value is None:
        return None
    if isinstance(value, (datetime, date, time)):
        return {"kind": type(value).__name__, "value": value.isoformat()}
    if not isinstance(value, (str, int, float, bool)):
        # Array/data-table formulas are retained natively and cannot be flattened.
        return {"kind": "readonly", "value": str(getattr(value, "text", "Special formula"))}
    kind = {"f": "formula", "e": "error", "b": "boolean", "n": "number"}.get(cell.data_type, "text")
    return {"kind": kind, "value": value}


def walk_shapes(shapes, prefix=""):
    for shape in shapes:
        key = f"{prefix}{shape.shape_id}"
        yield key, shape
        if shape.shape_type == 6:  # group
            yield from walk_shapes(shape.shapes, key + "/")


def read_native(path):
    if not is_zipfile(path):
        raise ValueError("The supplied file is not a readable Office archive.")
    try:
        return _read_native(path)
    except (BadZipFile, KeyError, TypeError) as exc:
        raise ValueError(f"The supplied Office file could not be read: {exc}") from exc


def _workbook(path):
    from openpyxl import load_workbook

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        book = load_workbook(path, rich_text=True)
    unsupported = [str(w.message) for w in caught if "not supported" in str(w.message) or "will be removed" in str(w.message)]
    if unsupported:
        book.close()
        raise ValueError("This workbook uses features that cannot be retained by this editor: " + "; ".join(unsupported))
    return book


def _read_native(path):
    fmt = Path(path).suffix[1:]
    data = {"version": 1, "format": fmt, "design": "preserve"}
    if fmt == "xlsx":
        book = _workbook(path)
        sheets = []
        count = 0
        for sheet in book:
            cells = {}
            # Sparse iteration avoids materialising a million empty formatted rows.
            for cell in sheet._cells.values():
                value = cell_value(cell)
                if value is not None:
                    cells[cell.coordinate] = value
            count += len(cells)
            if count > MAX_CELLS:
                raise ValueError(f"The browser editor supports up to {MAX_CELLS:,} populated cells.")
            sheets.append({"id": sheet.title, "name": sheet.title, "cells": cells})
        data["sheets"] = sheets
        book.close()
    elif fmt == "pptx":
        from pptx import Presentation

        deck = Presentation(path)
        slides = []
        for slide in deck.slides:
            shapes = []
            for key, shape in walk_shapes(slide.shapes):
                item = {"id": key}
                if shape.has_text_frame:
                    item.update(kind="text", paragraphs=[p.text for p in shape.text_frame.paragraphs])
                elif shape.has_table:
                    item.update(kind="table", rows=[[c.text for c in row.cells] for row in shape.table.rows])
                else:
                    continue
                shapes.append(item)
            slides.append({"id": str(slide.slide_id), "shapes": shapes})
        data["slides"] = slides
    else:
        raise ValueError("Choose an .xlsx workbook or .pptx presentation.")
    return data


def paths(run, slug):
    run = Path(run).resolve()
    if not re.fullmatch(r"[\w-]+", slug):
        raise ValueError("Invalid document name.")
    folder = run / "subjects" / slug
    if not folder.resolve().is_relative_to(run):
        raise ValueError("Document folder is outside the project.")
    master = run / f"{slug}.md"
    if not master.resolve().is_relative_to(run):
        raise ValueError("Document master is outside the project.")
    return folder, master


def baseline(run, slug):
    folder, _ = paths(run, slug)
    meta = json.loads((folder / "office-source.json").read_text())
    if meta.get("format") not in FORMATS:
        raise ValueError("Invalid Office source format.")
    source = folder / f"office-original.{meta['format']}"
    if not source.resolve().is_relative_to(Path(run).resolve()) or digest(source) != meta["sha256"]:
        raise ValueError("The saved Office source changed. Restore it before editing or exporting.")
    original = folder / "document.md"
    if not original.resolve().is_relative_to(Path(run).resolve()) or digest(original) != meta["model_sha256"]:
        raise ValueError("The saved original content changed. Restore it before editing or exporting.")
    return source, decode(original.read_text()), meta


def start(run, slug, source):
    import document

    folder, master = paths(run, slug)
    if master.exists():
        baseline(run, slug)
        validate(decode(master.read_text()), baseline(run, slug)[1])
        return master  # Retry opens the same master, never a second copy.
    source = Path(source).resolve()
    if not source.is_relative_to(Path(run).resolve()):
        raise ValueError("The supplied document must be inside this project.")
    data = read_native(source)
    folder.mkdir(parents=True, exist_ok=True)
    original = folder / f"office-original.{data['format']}"
    if original.exists() or (folder / "office-source.json").exists():
        raise ValueError("An Office source already exists without its master; restore the master first.")
    shutil.copy2(source, original)
    # Preserve the older extraction/change-plan files, if present.
    previous = folder / "document.md"
    if previous.exists():
        shutil.copy2(previous, folder / "document-before-office.md")
    previous.write_text(encode(data))
    (folder / "office-source.json").write_text(json.dumps({
        "format": data["format"], "sha256": digest(original), "model_sha256": digest(previous),
        "source": str(source.relative_to(Path(run).resolve())), "filename": source.name,
    }, indent=2) + "\n")
    master.write_text(encode(data))
    document.register(run, slug, master)
    return master


def _text(value, soft_breaks=False):
    pattern = r"[\x00-\x08\x0c\x0e-\x1f]" if soft_breaks else r"[\x00-\x08\x0b\x0c\x0e-\x1f]"
    if not isinstance(value, str) or len(value) > 32767 or re.search(pattern, value):
        raise ValueError("Text must be at most 32,767 characters and contain no control characters.")


def _cell(value):
    if not isinstance(value, dict) or set(value) != {"kind", "value"}:
        raise ValueError("Each cell needs a kind and value.")
    kind, v = value["kind"], value["value"]
    if kind == "number":
        if type(v) not in (int, float) or not (-1.7976931348623157e308 <= v <= 1.7976931348623157e308) or not math.isfinite(v):
            raise ValueError("A number cell needs a finite number.")
    elif kind == "boolean":
        if type(v) is not bool:
            raise ValueError("A boolean cell needs true or false.")
    elif kind in ("text", "formula", "error", "readonly"):
        _text(v)
        if kind == "formula" and not v.startswith("="):
            raise ValueError("A formula must start with =.")
        if kind == "error" and v not in {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A"}:
            raise ValueError("Invalid Excel error value.")
    elif kind in ("datetime", "date", "time"):
        _text(v)
        parsed = {"datetime": datetime, "date": date, "time": time}[kind].fromisoformat(v)
        if getattr(parsed, "tzinfo", None):
            raise ValueError("Excel dates and times must have no timezone.")
    else:
        raise ValueError("Unknown cell type.")


def validate(data, original):
    """Reject ambiguous or unsupported edits before a save or native export."""
    if data.get("format") != original["format"] or data.get("version") != 1:
        raise ValueError("The document format and version cannot change.")
    if data.get("design") not in ("preserve", "new"):
        raise ValueError("Choose preserve or new for the design.")
    group = "sheets" if data["format"] == "xlsx" else "slides"
    if set(data) != {"version", "format", "design", group}:
        raise ValueError("Unexpected Office document fields.")
    items = data.get(group)
    if not isinstance(items, list) or not items or len(items) > 1000:
        raise ValueError("Keep between 1 and 1,000 sheets or slides.")
    known = {i["id"]: i for i in original[group]}
    seen = set()
    total = 0
    names = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Each sheet or slide needs an ID.")
        key = item["id"]
        if key in seen or (key not in known and not re.fullmatch(r"new-[\w-]+", key)):
            raise ValueError("Use unique IDs; new items start with new-.")
        seen.add(key)
        old = known.get(key)
        if group == "sheets":
            from openpyxl.utils.cell import coordinate_to_tuple

            if set(item) != {"id", "name", "cells"}:
                raise ValueError("A sheet needs id, name, and cells.")
            name = item["name"]
            if not isinstance(name, str) or not name or len(name) > 31 or re.search(r"[\\/*?:\[\]]", name):
                raise ValueError("Use an Excel sheet name of 1–31 characters without \\ / * ? : [ ].")
            if name.lower() in names or (old and name != old["name"]):
                raise ValueError("Sheet names must be unique. Existing names stay fixed to preserve formula references.")
            names.add(name.lower())
            if not isinstance(item["cells"], dict):
                raise ValueError("Cells must be keyed by their Excel address.")
            total += len(item["cells"])
            if total > MAX_CELLS:
                raise ValueError("Too many populated cells for the browser editor.")
            for address, value in item["cells"].items():
                if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", address):
                    raise ValueError(f"Invalid cell address: {address}")
                row, col = coordinate_to_tuple(address)
                if row > 1048576 or col > 16384:
                    raise ValueError(f"Cell {address} is outside Excel's limits.")
                _cell(value)
                previous = old and old["cells"].get(address)
                if value["kind"] == "readonly" and value != previous:
                    raise ValueError("Special formulas and rich text are read-only.")
            for address, value in (old or {}).get("cells", {}).items():
                if value["kind"] == "readonly" and item["cells"].get(address) != value:
                    raise ValueError("Special formulas and rich text must remain intact.")
        else:
            if set(item) != {"id", "shapes"} or not isinstance(item["shapes"], list):
                raise ValueError("A slide needs id and shapes.")
            old_shapes = {s["id"]: s for s in (old or {}).get("shapes", [])}
            ids = set()
            for shape in item["shapes"]:
                if not isinstance(shape, dict) or not isinstance(shape.get("id"), str):
                    raise ValueError("Each shape needs an ID.")
                sid = shape["id"]
                if sid in ids or (sid not in old_shapes and not re.fullmatch(r"new-[\w-]+", sid)):
                    raise ValueError("Use unique shape IDs; new shapes start with new-.")
                ids.add(sid)
                prior = old_shapes.get(sid)
                if prior and shape.get("kind") != prior["kind"]:
                    raise ValueError("An existing shape cannot change type.")
                if shape.get("kind") == "text":
                    if set(shape) != {"id", "kind", "paragraphs"} or not isinstance(shape["paragraphs"], list) or not shape["paragraphs"]:
                        raise ValueError("A text shape needs at least one paragraph.")
                    for value in shape["paragraphs"]:
                        _text(value, soft_breaks=True)
                elif shape.get("kind") == "table":
                    rows = shape.get("rows")
                    if set(shape) != {"id", "kind", "rows"} or not isinstance(rows, list) or not rows:
                        raise ValueError("A table needs rows.")
                    if not isinstance(rows[0], list):
                        raise ValueError("Each table row must be a list of cells.")
                    width = len(rows[0])
                    if not width or any(not isinstance(r, list) or len(r) != width for r in rows):
                        raise ValueError("Each table row needs the same number of cells.")
                    if prior and (len(rows) != len(prior["rows"]) or width != len(prior["rows"][0])):
                        raise ValueError("Keep an existing table's dimensions to preserve its merges and design.")
                    for row in rows:
                        for value in row:
                            _text(value, soft_breaks=True)
                else:
                    raise ValueError("Editable shapes must be text or table.")
            if not set(old_shapes).issubset(ids):
                raise ValueError("Keep existing text shapes and tables; clear their text to leave them blank.")
    if group == "sheets" and not set(known).issubset(seen):
        raise ValueError("Keep existing sheets to preserve formula references.")


def _set_paragraph(paragraph, text):
    """Keep existing run styles and hyperlinks around edits, including mixed runs."""
    if paragraph.text == text:
        return
    runs = paragraph.runs
    if not runs or paragraph.text != "".join(r.text for r in runs):
        # Soft breaks/fields need a whole-paragraph replacement, retaining pPr.
        style = copy(runs[0]._r.rPr) if runs and runs[0]._r.rPr is not None else None
        paragraph.text = text
        run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
        if style is not None and run._r.rPr is None:
            run._r.insert(0, style)
        return
    old = "".join(r.text for r in runs)
    owners = [i for i, r in enumerate(runs) for _ in r.text]
    values = [""] * len(runs)
    for tag, a, b, c, d in SequenceMatcher(None, old, text, autojunk=False).get_opcodes():
        if tag == "equal":
            for index in range(a, b):
                values[owners[index]] += old[index]
        elif tag in ("insert", "replace"):
            owner = owners[min(a, len(owners) - 1)] if owners else 0
            values[owner] += text[c:d]
    for run, value in zip(runs, values):
        run.text = value


def _set_frame(frame, paragraphs):
    for index, value in enumerate(paragraphs):
        paragraph = frame.paragraphs[index] if index < len(frame.paragraphs) else frame.add_paragraph()
        _set_paragraph(paragraph, value)
    for paragraph in list(frame.paragraphs)[len(paragraphs):]:
        frame._txBody.remove(paragraph._p)


def build_native(source, data, original, target):
    validate(data, original)
    if data["format"] == "xlsx":
        from openpyxl.cell.cell import MergedCell
        from openpyxl.styles import Font, PatternFill
        from openpyxl.workbook.properties import CalcProperties

        book = _workbook(source)
        known = {s["id"]: s for s in original["sheets"]}
        for item in data["sheets"]:
            old = known.get(item["id"])
            sheet = book[old["name"]] if old else book.create_sheet(item["name"])
            previous = old["cells"] if old else {}
            for address in previous.keys() | item["cells"].keys():
                value = item["cells"].get(address)
                if value == previous.get(address):
                    continue
                cell = sheet[address]
                if isinstance(cell, MergedCell):
                    raise ValueError(f"{sheet.title}!{address} belongs to a merged cell; edit its top-left cell.")
                if sheet.protection.sheet and cell.protection.locked:
                    raise ValueError(f"{sheet.title}!{address} is protected in the supplied workbook.")
                v = value["value"] if value else None
                kind = value["kind"] if value else "text"
                if kind in ("date", "datetime", "time"):
                    v = {"date": date, "datetime": datetime, "time": time}[kind].fromisoformat(v)
                cell.value = v
                if kind == "text" and v is not None:
                    cell.data_type = "s"  # A literal =… stays text, never an injected formula.
            if data["design"] == "new":
                for cell in sheet._cells.values():
                    if isinstance(cell, MergedCell):
                        continue
                    cell.font = Font(name="Aptos", size=11, bold=cell.row == 1,
                                     color="FFFFFF" if cell.row == 1 else "172B4D")
                    cell.fill = PatternFill("solid", fgColor="17365D" if cell.row == 1 else
                                            ("EFF4FA" if cell.row % 2 == 0 else "FFFFFF"))
                sheet.sheet_view.showGridLines = False
                sheet.freeze_panes = "A2"
                for column in sheet.column_dimensions.values():
                    column.width = 20
                sheet.sheet_properties.pageSetUpPr.fitToPage = True
                sheet.page_setup.fitToWidth = 1
                sheet.page_setup.fitToHeight = 0
        book._sheets = [book[s["name"]] for s in data["sheets"]]
        book.calculation = CalcProperties(calcId=0, fullCalcOnLoad=True, forceFullCalc=True)
        book.save(target)
        book.close()
    else:
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.util import Inches, Pt

        deck = Presentation(source)
        existing = {str(s.slide_id): s for s in deck.slides}
        order = []
        for item in data["slides"]:
            slide = existing.get(item["id"])
            if slide is None:
                layout = min(deck.slide_layouts, key=lambda x: len(x.placeholders))
                slide = deck.slides.add_slide(layout)
                for placeholder in list(slide.placeholders):
                    placeholder._element.getparent().remove(placeholder._element)
            order.append(slide.slide_id)
            shapes = dict(walk_shapes(slide.shapes))
            for index, item_shape in enumerate(item["shapes"]):
                shape = shapes.get(item_shape["id"])
                if shape is None:
                    height = (deck.slide_height - Inches(1)) // max(1, len(item["shapes"]))
                    left, top = Inches(.6), Inches(.5) + index * height
                    width = deck.slide_width - Inches(1.2)
                    if item_shape["kind"] == "text":
                        shape = slide.shapes.add_textbox(left, top, width, height)
                    else:
                        rows = item_shape["rows"]
                        shape = slide.shapes.add_table(len(rows), len(rows[0]), left, top, width, height)
                if item_shape["kind"] == "text":
                    _set_frame(shape.text_frame, item_shape["paragraphs"])
                else:
                    for r, row in enumerate(item_shape["rows"]):
                        for c, value in enumerate(row):
                            cell = shape.table.cell(r, c)
                            if cell.is_spanned and value != cell.text:
                                raise ValueError("Edit the top-left cell of a merged presentation table.")
                            _set_frame(cell.text_frame, value.split("\n"))
            if data["design"] == "new":
                slide._element.set("showMasterSp", "0")
                slide.background.fill.solid()
                slide.background.fill.fore_color.rgb = RGBColor.from_string("FFFFFF")
                for _, shape in walk_shapes(slide.shapes):
                    if shape.shape_type in (1, 17):  # auto-shape or text box
                        shape.fill.solid()
                        shape.fill.fore_color.rgb = RGBColor.from_string("FFFFFF")
                    frames = [shape.text_frame] if shape.has_text_frame else []
                    if shape.has_table:
                        for r, row in enumerate(shape.table.rows):
                            for cell in row.cells:
                                cell.fill.solid()
                                cell.fill.fore_color.rgb = RGBColor.from_string("E8EFF7" if r == 0 else "FFFFFF")
                                frames.append(cell.text_frame)
                    for frame in frames:
                        for paragraph in frame.paragraphs:
                            for run in paragraph.runs:
                                run.font.name = "Aptos"
                                run.font.size = Pt(28 if shape == slide.shapes.title else 18)
                                run.font.color.rgb = RGBColor.from_string("17365D")
            # Retained images, charts, notes, groups, and relationships stay native.
        slide_ids = deck.slides._sldIdLst
        entries = {entry.id: entry for entry in slide_ids}
        for entry in list(slide_ids):
            slide_ids.remove(entry)
            if entry.id not in order:
                deck.part.drop_rel(entry.rId)
        for sid in order:
            slide_ids.append(entries[sid])
        deck.save(target)


def export(run, slug, design=None):
    import document

    folder, master = paths(run, slug)
    source, original, meta = baseline(run, slug)
    data = decode(master.read_text())
    master_digest = digest(master)
    if design is not None:
        data["design"] = design
    validate(data, original)
    if "[UNVERIFIED]" in master.read_text():
        raise ValueError("Resolve [UNVERIFIED] claims before exporting.")
    # Build and reopen before allocating a version; a failure leaves no empty round.
    with tempfile.TemporaryDirectory(prefix="office-export-") as temp:
        target = Path(temp) / f"document.{data['format']}"
        build_native(source, data, original, target)
        actual = read_native(target)
        group = "sheets" if data["format"] == "xlsx" else "slides"
        expected = json.loads(json.dumps(data))
        # Native IDs are assigned on creation; contents and order must round-trip.
        for model in (actual, expected):
            model.pop("design", None)
            for item in model[group]:
                item.pop("id", None)
                if group == "sheets":
                    for key, cell in list(item["cells"].items()):
                        if cell["kind"] == "text" and cell["value"] == "":
                            del item["cells"][key]
                        elif cell["kind"] == "date":
                            cell.update(kind="datetime", value=cell["value"] + "T00:00:00")
                for shape in item.get("shapes", []):
                    shape.pop("id", None)
        if actual != expected:
            raise ValueError("The native export did not retain all edited content; no export was published.")
        if digest(master) != master_digest:
            raise ValueError("The document changed during export. Export the saved version again.")
        version, out = document.next_version(run, slug)
        # A file named for its version ("v5 - Forecast.xlsx") is renamed for the new one.
        filename = re.sub(r"^v\d+(?=\s*-\s)", f"v{version}", Path(meta["filename"]).name)
        destination = out / filename
        shutil.copy2(target, destination)
        (out / "applied.json").write_text(json.dumps({
            "file": filename, "version": version, "format": data["format"],
            "from": master.name, "design": data["design"], "source_sha256": meta["sha256"],
            "master_sha256": master_digest,
        }, indent=2) + "\n")
        (out / "check.json").write_text(json.dumps({"ok": True, "problems": [], "check": "native content round-trip"}) + "\n")
    return str(destination.relative_to(run))
