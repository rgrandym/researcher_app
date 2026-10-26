"""Validated, report-specific overrides for the shared rendering styles."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from backend import config, workspace

FILE = ".report-style.json"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
FONT_STACKS = {
    "Avenir Next": ["Avenir Next", "Helvetica Neue", "Arial", "sans-serif"],
    "Charter": ["Charter", "Georgia", "Times New Roman", "serif"],
    "Inter": ["Inter", "Helvetica Neue", "Arial", "sans-serif"],
    "Helvetica Neue": ["Helvetica Neue", "Arial", "sans-serif"],
    "Arial": ["Arial", "sans-serif"],
    "Georgia": ["Georgia", "Times New Roman", "serif"],
    "Times New Roman": ["Times New Roman", "Georgia", "serif"],
    "Source Sans 3": ["Source Sans 3", "Arial", "sans-serif"],
}
COLOR_KEYS = ("ink", "body", "muted", "accent", "accent_soft", "rule",
              "mute_fill", "surface", "surface_alt", "link")
ITEM_ID = re.compile(r"^[FT][A-Za-z0-9_]+$")
FIGURE_BLOCK = re.compile(r"^```figure[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)
# A caption line may carry no title: the render gives an uncaptioned table one, so it is
# numbered with the rest ("Table 3.") and found in the palette's list.
TABLE_CAP = re.compile(r"^\*\*(?:Table|Exhibit):\*\*[ \t]*(.*?)[ \t]*\{#(T\w+)\}[ \t]*$", re.M)
AUTO_TABLE = re.compile(r"^Tx[0-9a-f]{6}(?:_\d+)?$")
EMPTY_ITEMS: dict[str, dict[str, Any]] = {"figures": {}, "tables": {}}
CHART_COLORS = ("grid", "axis")
# The colours charts once took from the page palette (text, background, highlight, muted
# marks, captions) and their fonts are their own settings, so a change to the page leaves
# the charts as they are. A save made before these existed takes them from its own page
# palette, so it renders as it did.
CHART_TEXT = {"title_color": "ink", "text_color": "body", "note_color": "muted",
              "background": "surface", "highlight_color": "accent", "muted_mark_color": "mute_fill",
              "caption_label_color": "ink", "caption_color": "muted"}
CHART_FONTS = {"title_font": "heading", "label_font": "body"}
FIGURE_TEXT = ("title_color", "text_color", "note_color", "highlight_color", "muted_mark_color")
# Every table's own colours, fonts and sizes, independent of the page and of the charts.
TABLE_COLORS = ("border", "header_bg", "header_fg", "body_bg", "body_fg", "stripe_bg", "caption_fg")
TABLE_SIZES = {"font_size_pt": (6, 14), "header_font_size_pt": (6, 16), "caption_font_size_pt": (5, 16)}
CAPTION_PT = 6.0  # captions sit directly below their table or figure, in small type
TABLE_FONTS = ("font_family", "header_font")
CHART_NUMBERS = {
    "line_width": (0.7, 5.0),
    "bar_width": (0.25, 0.9),
    "bar_corner_radius_px": (0, 12),
    "marker_size": (0, 9),
    "font_scale": (0.75, 1.6),
    "bar_opacity": (0.1, 1.0),
    "line_opacity": (0.1, 1.0),
    "area_fill_opacity": (0, 0.8),
    "stacked_fill_opacity": (0.1, 1.0),
    "label_font_scale": (0.6, 1.8),
}
CHART_DEFAULTS = {
    "line_width": 2.0, "bar_width": 0.62, "bar_corner_radius_px": 0,
    "marker_size": 4.5, "font_scale": 1.0,
    "bar_opacity": 1.0, "line_opacity": 1.0,
    "area_fill_opacity": 0.13, "label_font_scale": 1.0,
    "stacked_fill_opacity": 1.0,
}
CHART_OPTIONS = {
    "bar_fill": ("solid", "outline", "hatched"),
    "label_position": ("auto", "inside", "outside"),
}
TABLE_OPTIONS = {
    "rule_style": ("solid", "dashed", "dotted", "double"),
    "borders": ("horizontal", "grid", "minimal", "boxed", "header"),
}


def _base(style: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", style):
        raise ValueError("Unknown style")
    path = config.ROOT / ".claude" / "styles" / f"{style}.json"
    if not path.is_file():
        raise ValueError("Unknown style")
    return json.loads(path.read_text())


def _path(run: str) -> Path:
    return workspace.run_dir(run) / FILE


def saved(run: str) -> dict[str, Any] | None:
    try:
        data = json.loads(_path(run).read_text())
    except FileNotFoundError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("values"), dict):
        raise ValueError("The saved report appearance is invalid")
    return data


def _preset_defaults(style: str) -> dict[str, Any]:
    base = _base(style)
    fonts, chart, table = base["fonts"], base["chart"], base["table"]
    return {
        "color": {key: base["color"].get(key, base["color"]["rule"]) for key in COLOR_KEYS},
        "series": base["series"][:8],
        "fonts": {
            "heading": fonts["heading"][0],
            "body": fonts["body"][0],
            "base_pt": fonts.get("base_pt", 10.5),
            "heading_weight": fonts.get("heading_weight", 600),
        },
        "chart": {
            **{key: chart[key] for key in CHART_COLORS},
            **_chart_text_defaults(base["color"], {"heading": fonts["heading"][0], "body": fonts["body"][0]}),
            **{key: chart.get(key, CHART_DEFAULTS[key]) for key in CHART_NUMBERS},
            "line_style": chart.get("line_style", "solid"),
            "value_labels": chart.get("value_labels", True),
            "bar_fill": chart.get("bar_fill", "solid"),
            "label_position": chart.get("label_position", "auto"),
            "label_color": chart.get("label_color", "auto"),
        },
        "table": _table_defaults(
            table, base["color"], {"heading": fonts["heading"][0], "body": fonts["body"][0], "base_pt": fonts.get("base_pt", 10.5)}
        ),
        "items": {"figures": {}, "tables": {}},
    }


def _chart_text_defaults(color: dict[str, Any], fonts: dict[str, Any]) -> dict[str, Any]:
    return {**{key: color.get(role, color.get("rule")) for key, role in CHART_TEXT.items()},
            **{key: fonts[role] for key, role in CHART_FONTS.items()}, "caption_font_size_pt": CAPTION_PT}


def _table_defaults(table: dict[str, Any], color: dict[str, Any], fonts: dict[str, Any]) -> dict[str, Any]:
    """Every table's settings as the preset draws them, from its table block and palette."""
    rules = table.get("style") == "rules"
    zebra = table.get("zebra", "none")
    size = round(float(fonts.get("base_pt", 10.5)) * 0.86, 1)
    return {
        "border": table["border"], "rule_weight_pt": table.get("rule_weight_pt", 0.6),
        "header_bg": color["surface"] if rules else table.get("header_bg", color["surface_alt"]),
        "header_fg": table.get("header_fg", color["ink"]),
        "body_bg": color["surface"], "body_fg": color["body"],
        "stripe_bg": zebra if isinstance(zebra, str) and HEX.fullmatch(zebra) else color["surface"],
        "caption_fg": color["ink"],
        "font_family": fonts["body"], "header_font": fonts["heading"],
        "font_size_pt": size, "header_font_size_pt": size, "caption_font_size_pt": CAPTION_PT,
    }


def _defaults_file() -> Path:
    return config.DATA / "appearance-defaults.json"


def defaults(style: str) -> dict[str, Any]:
    preset = _preset_defaults(style)
    try:
        stored = json.loads(_defaults_file().read_text()).get(style)
    except (FileNotFoundError, ValueError, AttributeError):
        stored = None
    if not isinstance(stored, dict):
        return preset
    candidate = {**preset, **stored, "items": {"figures": {}, "tables": {}}}
    return validate(style, candidate)


def _primary(run: str) -> str:
    return str(workspace.run_meta(workspace.run_dir(run)).get("primary") or "report.md")


def _doc_key(run: str, doc: str | None) -> str | None:
    """Where a document's own figure and table settings are kept: None for the run's
    primary document (the file's `values.items`, as before), else its name under
    `documents`, so two documents' T1 never share settings."""
    return None if not doc or doc == _primary(run) else doc


def _is_rule_row(line: str) -> bool:
    text = line.strip()
    return "---" in text and "|" in text and re.fullmatch(r"[\s|:\-]+", text) is not None


def _caption_line(lines: list[str], at: int, step: int) -> bool:
    """Whether the nearest line from `at` (going by `step`), past blank lines and
    one-line HTML comments, is a table caption."""
    while 0 <= at < len(lines):
        text = lines[at].strip()
        if text and not (text.startswith("<!--") and text.endswith("-->")):
            return TABLE_CAP.fullmatch(text) is not None
        at += step
    return False


def pipe_tables(md: str) -> list[dict[str, Any]]:
    """Every pipe table outside code fences: where it starts and ends, its header row,
    whether a caption line sits next to it, and, when none does, the id it is known by
    until it gets one (from its header row, so it survives edits elsewhere)."""
    lines = md.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    found: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    fence = False
    i = 0
    while i < len(lines):
        text = lines[i].lstrip()
        if text.startswith(("```", "~~~")):
            fence = not fence
        elif (not fence and text.startswith("|") and i + 1 < len(lines) and _is_rule_row(lines[i + 1])
              and not (i and lines[i - 1].lstrip().startswith("|"))):
            end = i + 2
            while end < len(lines) and lines[end].lstrip().startswith("|"):
                end += 1
            header = lines[i].strip()
            cells = [re.sub(r"[*_`]", "", cell).strip() for cell in header.strip("|").split("|")]
            key = "Tx" + hashlib.sha1(" ".join(cells).lower().encode()).hexdigest()[:6]
            seen[key] = seen.get(key, 0) + 1
            found.append({
                "start": starts[i], "end": starts[end], "first": i, "last": end,
                "columns": [c for c in cells if c],
                "captioned": _caption_line(lines, i - 1, -1) or _caption_line(lines, end, 1),
                "auto_id": key if seen[key] == 1 else f"{key}_{seen[key]}",
            })
            i = end
            continue
        i += 1
    return found


def with_captions(md: str) -> str:
    """The document with a caption line, carrying no title, above each table that has
    none: the render then numbers every table, and the palette can name and style it."""
    for table in reversed(pipe_tables(md)):
        if table["captioned"]:
            continue
        md = _insert_caption(md, table["start"], f"{{#{table['auto_id']}}}")
    return md


def captions_below(md: str) -> str:
    """Each table's caption line moved from above its table to directly below it, where
    the house layout puts every caption."""
    lines = md.splitlines(keepends=True)
    for table in reversed(pipe_tables(md)):
        k = table["first"] - 1
        while k >= 0 and (not lines[k].strip() or (lines[k].strip().startswith("<!--") and lines[k].strip().endswith("-->"))):
            k -= 1
        if k < 0 or not TABLE_CAP.fullmatch(lines[k].strip()):
            continue
        end = table["last"]
        if not lines[end - 1].endswith("\n"):
            lines[end - 1] += "\n"
        after = ["\n", lines[k].strip() + "\n"] + ([] if end < len(lines) and not lines[end].strip() else ["\n"])
        lines[end:end] = after
        del lines[k]
    return "".join(lines)


def _insert_caption(md: str, at: int, caption: str) -> str:
    """A caption line inserted at `at`, the start of a table, as its own paragraph."""
    lead = "" if at == 0 or md[:at].endswith("\n\n") else ("\n" if md[:at].endswith("\n") else "\n\n")
    return md[:at] + f"{lead}**Table:** {caption}\n\n" + md[at:]


def add_caption(run: str, doc: str, table_id: str, title: str) -> str:
    """Write a caption line into the document above an uncaptioned table, as the author
    asked from the palette; the table's own settings move to its new id. The new id."""
    title = " ".join(title.split())
    if not title or len(title) > 300 or "{#" in title:
        raise ValueError("A caption is one line of text, up to 300 characters")
    path = workspace.run_file(run, doc)
    md = path.read_text()
    table = next((t for t in pipe_tables(md) if not t["captioned"] and t["auto_id"] == table_id), None)
    if table is None:
        raise ValueError("That table is no longer in the document, or already has a caption")
    # The next free numbered id, past every one the document defines, cites or marks
    # (a revised document marks its original tables <!-- T1 -->).
    taken = {int(n) for m in re.finditer(r"\{#T(\d+)\}|\[\[T(\d+)\]\]|<!--\s*T(\d+)\s*-->", md) for n in m.groups() if n}
    new_id = f"T{max(taken, default=0) + 1}"
    workspace.save_run_file(run, doc, _insert_caption(md, table["start"], f"{title} {{#{new_id}}}"), path.stat().st_mtime)
    data = saved(run)
    if data:
        key = _doc_key(run, doc)
        items = data.setdefault("documents", {}).setdefault(key, copy.deepcopy(EMPTY_ITEMS)) if key else data["values"].setdefault("items", copy.deepcopy(EMPTY_ITEMS))
        if table_id in items.get("tables", {}):
            items["tables"][new_id] = items["tables"].pop(table_id)
            _write(run, data)
    return new_id


def available(run: str, doc: str | None = None) -> dict[str, list[dict[str, Any]]]:
    try:
        raw = workspace.run_file(run, doc or _primary(run)).read_text()
    except FileNotFoundError:
        raw = ""
    auto = {t["auto_id"]: t for t in pipe_tables(raw) if not t["captioned"]}
    md = with_captions(raw)
    numbers = numbering(md)
    figures = []
    for match in FIGURE_BLOCK.finditer(md):
        try:
            spec = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(spec, dict) and isinstance(spec.get("id"), str) and ITEM_ID.fullmatch(spec["id"]):
            labels = []
            kind = spec.get("type")
            if kind in ("bar", "hbar", "stacked_bar", "stacked_hbar"):
                series = spec.get("series") or [{"name": spec.get("name", "Value"), "values": spec.get("values", [])}]
                categories = spec.get("categories", [])
                for si, row in enumerate(series):
                    for ci, value in enumerate(row.get("values", [])):
                        if value is not None:
                            labels.append({"key": f"s{si}c{ci}", "name": f"{row.get('name') or 'Value'} · {categories[ci] if ci < len(categories) else ci + 1}", "default": str(value)})
            elif kind == "heatmap":
                for ri, row in enumerate(spec.get("values", [])):
                    for ci, value in enumerate(row):
                        if value is not None:
                            labels.append({"key": f"r{ri}c{ci}", "name": f"{spec['rows'][ri]} · {spec['columns'][ci]}", "default": str(value)})
            figures.append({"id": spec["id"], "number": numbers.get(spec["id"]), "label": str(spec.get("title") or spec["id"])[:120],
                            "type": str(kind or ""), "value_labels": labels[:200]})
    tables = [{"id": match.group(2), "number": numbers.get(match.group(2)),
               "label": (match.group(1) or ("Columns: " + ", ".join(auto[match.group(2)]["columns"]) if match.group(2) in auto else ""))[:120],
               "captioned": match.group(2) not in auto}
              for match in TABLE_CAP.finditer(md)]
    return {"figures": figures, "tables": tables}


def numbering(md: str) -> dict[str, int]:
    """The number each figure and table is given in the rendered document: separate
    sequences in document order, as figures.py numbers them."""
    order: list[tuple[int, str, str]] = []
    for match in FIGURE_BLOCK.finditer(md):
        found = re.search(r'"id"\s*:\s*"([^"]+)"', match.group(1))
        order.append((match.start(), "F", found.group(1) if found else ""))
    order += [(match.start(), "T", match.group(2)) for match in TABLE_CAP.finditer(md)]
    counts = {"F": 0, "T": 0}
    numbers: dict[str, int] = {}
    for _, kind, item_id in sorted(order):
        counts[kind] += 1
        if item_id:
            numbers.setdefault(item_id, counts[kind])
    return numbers


def table_sides(md: str) -> dict[str, str]:
    """Whether each table's caption line sits above it (the convention) or below it."""
    sides = {}
    for m in TABLE_CAP.finditer(md):
        before = md[: m.start()].rstrip("\n")
        # A caption right after a table is that table's: the render moves every caption
        # below its table, so one between two tables belongs to the first.
        below = before.rsplit("\n", 1)[-1].lstrip().startswith("|")
        sides[m.group(2)] = "below" if below else "above"
    return sides


def _hex(value: Any) -> str:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError("Colours must be six-digit hex values")
    return value.upper()


def _number(value: Any, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"A size must be between {low:g} and {high:g}")
    return float(value)


def _label_color(value: Any) -> str:
    return "auto" if value == "auto" else _hex(value)


def _label_text(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 200:
        raise ValueError("Too many edited chart labels")
    out = {}
    for key, label in value.items():
        if not isinstance(key, str) or not re.fullmatch(r"(?:s|r)\d+c\d+", key):
            raise ValueError("A chart label key is invalid")
        if not isinstance(label, str) or len(label) > 120 or any(ord(char) < 32 for char in label):
            raise ValueError("Chart labels must be short, plain text")
        out[key] = label
    return out


def validate(style: str, values: Any) -> dict[str, Any]:
    preset = _preset_defaults(style)
    if not isinstance(values, dict) or set(values) not in ({"color", "series", "fonts", "chart", "table"}, {"color", "series", "fonts", "chart", "table", "items"}):
        raise ValueError("Appearance settings are incomplete")
    color = values["color"]
    if not isinstance(color, dict) or set(color) != set(COLOR_KEYS):
        raise ValueError("The colour palette is incomplete")
    series = values["series"]
    if not isinstance(series, list) or not 4 <= len(series) <= 8:
        raise ValueError("Choose four to eight chart colours")
    fonts = values["fonts"]
    if not isinstance(fonts, dict) or set(fonts) != {"heading", "body", "base_pt", "heading_weight"}:
        raise ValueError("Font settings are incomplete")
    if not isinstance(fonts["heading"], str) or not isinstance(fonts["body"], str) or fonts["heading"] not in FONT_STACKS or fonts["body"] not in FONT_STACKS:
        raise ValueError("Choose a listed font")
    if fonts["heading_weight"] not in (400, 500, 600, 700):
        raise ValueError("Choose a listed heading weight")
    supplied_chart = values["chart"]
    chart_keys = set(CHART_COLORS) | set(CHART_TEXT) | set(CHART_FONTS) | set(CHART_NUMBERS) | {"line_style", "value_labels", "label_color", "caption_font_size_pt"} | set(CHART_OPTIONS)
    if not isinstance(supplied_chart, dict) or not set(supplied_chart) <= chart_keys:
        raise ValueError("Chart settings are incomplete")
    chart = {**preset["chart"], **_chart_text_defaults(color, fonts), **supplied_chart}
    if any(chart[key] not in FONT_STACKS for key in CHART_FONTS):
        raise ValueError("Choose a listed chart font")
    if chart["line_style"] not in ("solid", "dashed", "dotted", "dashdot"):
        raise ValueError("Choose a listed line style")
    if not isinstance(chart["value_labels"], bool):
        raise ValueError("Value labels must be on or off")
    for key, choices in CHART_OPTIONS.items():
        if chart[key] not in choices:
            raise ValueError(f"Choose a listed {key.replace('_', ' ')}")
    label_color = _label_color(chart["label_color"])
    supplied_table = values["table"]
    table_keys = {"rule_weight_pt", *TABLE_COLORS, *TABLE_SIZES, *TABLE_FONTS}
    if not isinstance(supplied_table, dict) or not {"border", "rule_weight_pt"} <= set(supplied_table) <= table_keys:
        raise ValueError("Table settings are incomplete")
    table = {**_table_defaults(_base(style)["table"], color, fonts), **supplied_table}
    if any(table[key] not in FONT_STACKS for key in TABLE_FONTS):
        raise ValueError("Choose a listed table font")
    items = values.get("items", {"figures": {}, "tables": {}})
    if not isinstance(items, dict) or set(items) != {"figures", "tables"} or not all(isinstance(items[k], dict) for k in items):
        raise ValueError("Individual appearance settings are invalid")
    clean_items: dict[str, dict[str, Any]] = {"figures": {}, "tables": {}}
    for key, item in items["figures"].items():
        if not isinstance(key, str) or not key.startswith("F") or not ITEM_ID.fullmatch(key) or not isinstance(item, dict):
            raise ValueError("Figure appearance settings are invalid")
        figure_keys = {"series", "grid", "axis", "background", *FIGURE_TEXT, "line_width", "line_style", "bar_width", "bar_corner_radius_px", "marker_size", "font_scale", "value_labels", "heading_font", "body_font", "bar_opacity", "line_opacity", "area_fill_opacity", "stacked_fill_opacity", "label_font_scale", "bar_fill", "label_position", "label_color", "label_text"}
        if not set(item) <= figure_keys:
            raise ValueError("Figure appearance settings are incomplete")
        item = {**{
            "series": series, "grid": chart["grid"], "axis": chart["axis"], "background": chart["background"],
            **{k: chart[k] for k in FIGURE_TEXT},
            **{k: chart[k] for k in CHART_NUMBERS},
            "line_style": chart["line_style"], "value_labels": chart["value_labels"],
            "heading_font": chart["title_font"], "body_font": chart["label_font"],
            **{k: chart[k] for k in CHART_OPTIONS}, "label_color": label_color, "label_text": {},
        }, **item}
        if not isinstance(item["series"], list) or not 4 <= len(item["series"]) <= 8:
            raise ValueError("Choose four to eight figure colours")
        if item["line_style"] not in ("solid", "dashed", "dotted", "dashdot") or not isinstance(item["value_labels"], bool):
            raise ValueError("Figure line style or labels are invalid")
        if any(item[k] not in choices for k, choices in CHART_OPTIONS.items()):
            raise ValueError("Figure fill or label position is invalid")
        if item["heading_font"] not in FONT_STACKS or item["body_font"] not in FONT_STACKS:
            raise ValueError("Choose a listed figure font")
        clean_items["figures"][key] = {
            "series": [_hex(v) for v in item["series"]],
            **{k: _hex(item[k]) for k in ("grid", "axis", "background", *FIGURE_TEXT)},
            **{k: _number(item[k], *CHART_NUMBERS[k]) for k in CHART_NUMBERS},
            "line_style": item["line_style"], "value_labels": item["value_labels"],
            "heading_font": item["heading_font"], "body_font": item["body_font"],
            **{k: item[k] for k in CHART_OPTIONS},
            "label_color": _label_color(item["label_color"]), "label_text": _label_text(item["label_text"]),
        }
    for key, item in items["tables"].items():
        if not isinstance(key, str) or not key.startswith("T") or not ITEM_ID.fullmatch(key) or not isinstance(item, dict):
            raise ValueError("Table appearance settings are invalid")
        if not set(item) <= {*TABLE_COLORS, *TABLE_SIZES, "cell_padding_em", "rule_weight_pt", "font_family", "width_percent", *TABLE_OPTIONS}:
            raise ValueError("Table appearance settings are incomplete")
        # A table's own settings start from the report's table settings, so a table saved
        # before a setting existed keeps the look it had.
        item = {**{k: table[k] for k in (*TABLE_COLORS, *TABLE_SIZES, "rule_weight_pt", "font_family")},
                "cell_padding_em": 0.45, "width_percent": 100,
                "rule_style": "solid", "borders": "horizontal", **item}
        if "font_size_pt" in items["tables"][key] and "header_font_size_pt" not in items["tables"][key]:
            item["header_font_size_pt"] = item["font_size_pt"]
        if item["font_family"] not in FONT_STACKS:
            raise ValueError("Choose a listed table font")
        if any(item[k] not in choices for k, choices in TABLE_OPTIONS.items()):
            raise ValueError("Choose a listed table line type and layout")
        clean_items["tables"][key] = {
            **{k: _hex(item[k]) for k in TABLE_COLORS},
            **{k: _number(item[k], *TABLE_SIZES[k]) for k in TABLE_SIZES},
            "cell_padding_em": _number(item["cell_padding_em"], 0.15, 1.2),
            "rule_weight_pt": _number(item["rule_weight_pt"], 0.2, 2.0),
            "font_family": item["font_family"], "width_percent": _number(item["width_percent"], 50, 100),
            **{k: item[k] for k in TABLE_OPTIONS},
        }
    return {
        "color": {key: _hex(color[key]) for key in COLOR_KEYS},
        "series": [_hex(item) for item in series],
        "fonts": {
            "heading": fonts["heading"], "body": fonts["body"],
            "base_pt": _number(fonts["base_pt"], 8, 14),
            "heading_weight": fonts["heading_weight"],
        },
        "chart": {
            **{key: _hex(chart[key]) for key in (*CHART_COLORS, *CHART_TEXT)},
            **{key: chart[key] for key in CHART_FONTS},
            "caption_font_size_pt": _number(chart["caption_font_size_pt"], 5, 16),
            **{key: _number(chart[key], *bounds) for key, bounds in CHART_NUMBERS.items()},
            "line_style": chart["line_style"],
            "value_labels": chart["value_labels"],
            **{k: chart[k] for k in CHART_OPTIONS},
            "label_color": label_color,
        },
        "table": {
            **{key: _hex(table[key]) for key in TABLE_COLORS},
            "rule_weight_pt": _number(table["rule_weight_pt"], 0.2, 2.0),
            **{key: _number(table[key], *bounds) for key, bounds in TABLE_SIZES.items()},
            **{key: table[key] for key in TABLE_FONTS},
        },
        "items": clean_items,
    }


def _write(run: str, data: dict[str, Any]) -> None:
    path = _path(run)
    fd, temp = tempfile.mkstemp(prefix=f"{FILE}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _values(run: str, style: str, doc: str | None) -> tuple[dict[str, Any], bool]:
    """The report's settings with this document's own figure and table settings."""
    data = saved(run)
    active = bool(data and data.get("style") == style)
    values = dict(data["values"]) if data and active else defaults(style)
    key = _doc_key(run, doc)
    if key:
        values["items"] = (data or {}).get("documents", {}).get(key, EMPTY_ITEMS)
    return validate(style, values), active


def view(run: str, style: str, doc: str | None = None) -> dict[str, Any]:
    data = saved(run)
    values, active = _values(run, style, doc)
    return {
        "saved_style": data.get("style") if data else None,
        "style": style,
        "values": values,
        "custom": active,
        "available": available(run, doc),
    }


def save(run: str, style: str, values: Any, remember_default: bool = False, doc: str | None = None) -> dict[str, Any]:
    cleaned = validate(style, values)
    data = saved(run) or {}
    key = _doc_key(run, doc)
    documents = dict(data.get("documents", {}))
    if key:
        documents[key] = cleaned["items"]
        same = data.get("style") == style and isinstance(data.get("values"), dict)
        cleaned = {**cleaned, "items": data["values"].get("items", EMPTY_ITEMS) if same else EMPTY_ITEMS}
    _write(run, {"style": style, "values": cleaned, **({"documents": documents} if documents else {})})
    if remember_default:
        destination = _defaults_file()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            all_defaults = json.loads(destination.read_text())
        except (FileNotFoundError, ValueError):
            all_defaults = {}
        if not isinstance(all_defaults, dict):
            all_defaults = {}
        all_defaults[style] = {key: cleaned[key] for key in ("color", "series", "fonts", "chart", "table")}
        fd, temp = tempfile.mkstemp(prefix="appearance-defaults.", dir=destination.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(all_defaults, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, destination)
        finally:
            Path(temp).unlink(missing_ok=True)
    return view(run, style, doc)


def reset(run: str) -> None:
    _path(run).unlink(missing_ok=True)


def effective(run: str, style: str, doc: str | None = None) -> dict[str, Any] | None:
    values, active = _values(run, style, doc)
    if not active and values == _preset_defaults(style):
        return None
    result = copy.deepcopy(_base(style))
    result["color"].update(values["color"])
    result["series"] = values["series"]
    result["fonts"]["heading"] = FONT_STACKS[values["fonts"]["heading"]]
    result["fonts"]["body"] = FONT_STACKS[values["fonts"]["body"]]
    result["fonts"]["base_pt"] = values["fonts"]["base_pt"]
    result["fonts"]["heading_weight"] = values["fonts"]["heading_weight"]
    result["chart"].update(values["chart"])
    for key in CHART_FONTS:
        result["chart"][key] = FONT_STACKS[values["chart"][key]]
    table = values["table"]
    result["table"].update(table)
    # The Word table style reads banding and header shading from the style's table block.
    result["table"]["zebra"] = table["stripe_bg"] if table["stripe_bg"] != table["body_bg"] else "none"
    if table["header_bg"] != table["body_bg"]:
        result["table"]["style"] = "banded"
    result["table_settings"] = table
    result["table_custom"] = table != _preset_defaults(style)["table"]
    result["item_overrides"] = values["items"]
    return result
