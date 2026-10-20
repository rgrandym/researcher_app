"""Validated, report-specific overrides for the shared rendering styles."""

from __future__ import annotations

import copy
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
TABLE_CAP = re.compile(r"^\*\*(?:Table|Exhibit):\*\*[ \t]*(.+?)[ \t]*\{#(T\w+)\}[ \t]*$", re.M)
CHART_COLORS = ("grid", "axis")
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
            **{key: chart.get(key, CHART_DEFAULTS[key]) for key in CHART_NUMBERS},
            "line_style": chart.get("line_style", "solid"),
            "value_labels": chart.get("value_labels", True),
            "bar_fill": chart.get("bar_fill", "solid"),
            "label_position": chart.get("label_position", "auto"),
            "label_color": chart.get("label_color", "auto"),
        },
        "table": {
            "border": table["border"],
            "rule_weight_pt": table.get("rule_weight_pt", 0.6),
        },
        "items": {"figures": {}, "tables": {}},
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


def available(run: str) -> dict[str, list[dict[str, Any]]]:
    folder = workspace.run_dir(run)
    primary = workspace.run_meta(folder).get("primary") or "report.md"
    try:
        md = workspace.run_file(run, primary).read_text()
    except FileNotFoundError:
        md = ""
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
            figures.append({"id": spec["id"], "label": str(spec.get("title") or spec["id"])[:120],
                            "type": str(kind or ""), "value_labels": labels[:200]})
    tables = [{"id": match.group(2), "label": match.group(1)[:120]} for match in TABLE_CAP.finditer(md)]
    return {"figures": figures, "tables": tables}


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
    chart_keys = set(CHART_COLORS) | set(CHART_NUMBERS) | {"line_style", "value_labels", "label_color"} | set(CHART_OPTIONS)
    if not isinstance(supplied_chart, dict) or not set(supplied_chart) <= chart_keys:
        raise ValueError("Chart settings are incomplete")
    chart = {**preset["chart"], **supplied_chart}
    if chart["line_style"] not in ("solid", "dashed", "dotted", "dashdot"):
        raise ValueError("Choose a listed line style")
    if not isinstance(chart["value_labels"], bool):
        raise ValueError("Value labels must be on or off")
    for key, choices in CHART_OPTIONS.items():
        if chart[key] not in choices:
            raise ValueError(f"Choose a listed {key.replace('_', ' ')}")
    label_color = _label_color(chart["label_color"])
    table = values["table"]
    if not isinstance(table, dict) or set(table) != {"border", "rule_weight_pt"}:
        raise ValueError("Table settings are incomplete")
    items = values.get("items", {"figures": {}, "tables": {}})
    if not isinstance(items, dict) or set(items) != {"figures", "tables"} or not all(isinstance(items[k], dict) for k in items):
        raise ValueError("Individual appearance settings are invalid")
    clean_items: dict[str, dict[str, Any]] = {"figures": {}, "tables": {}}
    for key, item in items["figures"].items():
        if not isinstance(key, str) or not key.startswith("F") or not ITEM_ID.fullmatch(key) or not isinstance(item, dict):
            raise ValueError("Figure appearance settings are invalid")
        figure_keys = {"series", "grid", "axis", "background", "line_width", "line_style", "bar_width", "bar_corner_radius_px", "marker_size", "font_scale", "value_labels", "heading_font", "body_font", "bar_opacity", "line_opacity", "area_fill_opacity", "stacked_fill_opacity", "label_font_scale", "bar_fill", "label_position", "label_color", "label_text"}
        if not set(item) <= figure_keys:
            raise ValueError("Figure appearance settings are incomplete")
        item = {**{
            "series": series, "grid": chart["grid"], "axis": chart["axis"], "background": color["surface"],
            **{k: chart[k] for k in CHART_NUMBERS},
            "line_style": chart["line_style"], "value_labels": chart["value_labels"],
            "heading_font": fonts["heading"], "body_font": fonts["body"],
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
            "grid": _hex(item["grid"]), "axis": _hex(item["axis"]), "background": _hex(item["background"]),
            **{k: _number(item[k], *CHART_NUMBERS[k]) for k in CHART_NUMBERS},
            "line_style": item["line_style"], "value_labels": item["value_labels"],
            "heading_font": item["heading_font"], "body_font": item["body_font"],
            **{k: item[k] for k in CHART_OPTIONS},
            "label_color": _label_color(item["label_color"]), "label_text": _label_text(item["label_text"]),
        }
    for key, item in items["tables"].items():
        if not isinstance(key, str) or not key.startswith("T") or not ITEM_ID.fullmatch(key) or not isinstance(item, dict):
            raise ValueError("Table appearance settings are invalid")
        if not set(item) <= {"header_bg", "header_fg", "border", "font_size_pt", "cell_padding_em", "rule_weight_pt", "font_family", "width_percent", "body_bg", "body_fg", "stripe_bg"}:
            raise ValueError("Table appearance settings are incomplete")
        item = {"body_bg": color["surface"], "body_fg": color["body"], "stripe_bg": color["surface_alt"], **item}
        if item["font_family"] not in FONT_STACKS:
            raise ValueError("Choose a listed table font")
        clean_items["tables"][key] = {
            **{k: _hex(item[k]) for k in ("header_bg", "header_fg", "border", "body_bg", "body_fg", "stripe_bg")},
            "font_size_pt": _number(item["font_size_pt"], 6, 14),
            "cell_padding_em": _number(item["cell_padding_em"], 0.15, 1.2),
            "rule_weight_pt": _number(item["rule_weight_pt"], 0.2, 2.0),
            "font_family": item["font_family"], "width_percent": _number(item["width_percent"], 50, 100),
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
            **{key: _hex(chart[key]) for key in CHART_COLORS},
            **{key: _number(chart[key], *bounds) for key, bounds in CHART_NUMBERS.items()},
            "line_style": chart["line_style"],
            "value_labels": chart["value_labels"],
            **{k: chart[k] for k in CHART_OPTIONS},
            "label_color": label_color,
        },
        "table": {
            "border": _hex(table["border"]),
            "rule_weight_pt": _number(table["rule_weight_pt"], 0.2, 2.0),
        },
        "items": clean_items,
    }


def view(run: str, style: str) -> dict[str, Any]:
    data = saved(run)
    active = bool(data and data.get("style") == style)
    return {
        "saved_style": data.get("style") if data else None,
        "style": style,
        "values": validate(style, data["values"]) if active else defaults(style),
        "custom": active,
        "available": available(run),
    }


def save(run: str, style: str, values: Any, remember_default: bool = False) -> dict[str, Any]:
    cleaned = validate(style, values)
    path = _path(run)
    fd, temp = tempfile.mkstemp(prefix=f"{FILE}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"style": style, "values": cleaned}, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
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
    return view(run, style)


def reset(run: str) -> None:
    _path(run).unlink(missing_ok=True)


def effective(run: str, style: str) -> dict[str, Any] | None:
    data = saved(run)
    if data and data.get("style") == style:
        values = validate(style, data["values"])
    else:
        values = defaults(style)
        if values == _preset_defaults(style):
            return None
    result = copy.deepcopy(_base(style))
    result["color"].update(values["color"])
    result["series"] = values["series"]
    result["fonts"]["heading"] = FONT_STACKS[values["fonts"]["heading"]]
    result["fonts"]["body"] = FONT_STACKS[values["fonts"]["body"]]
    result["fonts"]["base_pt"] = values["fonts"]["base_pt"]
    result["fonts"]["heading_weight"] = values["fonts"]["heading_weight"]
    result["chart"].update(values["chart"])
    result["table"].update(values["table"])
    result["item_overrides"] = values["items"]
    return result
