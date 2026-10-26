"""Measure and edit a deck master, for /slides.

    python3 .claude/scripts/slides.py inspect <run>/<slug>.md [--json]
    python3 .claude/scripts/slides.py edit <run>/<slug>.md <ops.json>

`inspect` reports what a script can measure about a deck's design: how many fonts and
sizes it uses, text too small to read, crowded slides, edges that nearly line up, titles
that wander from slide to slide, boxes off the slide, and text with too little contrast
against its own fill. It judges nothing a script cannot; the rest is the designer's eye.

`edit` applies a list of operations to the master and validates the result before it
writes. Slides are numbered from 1 in the master's current order; shapes by their id.

    {"op": "box", "slide": 3, "shape": "4", "box": {"x": 40, "y": 36}}      (partial)
    {"op": "style", "slide": 3, "shape": "4", "style": {"size": 32, "color": "0D2330"}}
    {"op": "text", "slide": 3, "shape": "4", "paragraphs": ["Revenue triples by 2028"]}
    {"op": "theme", "colors": {"accent1": "0E7490"}, "fonts": {"major": "Helvetica"}}
    {"op": "swap_color", "from": "5D6C74", "to": "2C3A40"}
    {"op": "swap_font", "from": "Helvetica Neue Light", "to": "Helvetica"}
    {"op": "order", "slides": [1, 2, 4, 3, 5]}
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import office_master

MIN_BODY_PT = 14  # below this, text is hard to read on a projected or shared slide
MAX_WORDS = 60  # beyond this a slide reads as a document
NEAR = (0.6, 6.0)  # edges this close, but not equal, look misaligned
MIN_CONTRAST = 4.5  # WCAG AA for normal text


def _load(master):
    master = Path(master).resolve()
    run, slug = master.parent, master.stem
    _, original, _ = office_master.baseline(run, slug)
    data = office_master.decode(master.read_text())
    if data["format"] != "pptx":
        raise SystemExit("slides.py works on presentation masters only.")
    return master, data, original


def _luminance(hex6):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def inspect(data, width_pt=960.0, height_pt=540.0):
    slides = data["slides"]
    fonts, sizes = Counter(), Counter()
    titles = []
    report = {"slides": [], "deck": []}
    for n, slide in enumerate(slides, 1):
        issues = []
        texts = [s for s in slide["shapes"] if s["kind"] == "text" and "".join(s["paragraphs"]).strip()]
        words = sum(len(" ".join(s["paragraphs"]).split()) for s in texts)
        for s in texts:
            style = s.get("style", {})
            if style.get("font"):
                fonts[style["font"]] += 1
            if style.get("size"):
                sizes[style["size"]] += 1
                if style["size"] < MIN_BODY_PT:
                    issues.append(f"shape {s['id']}: {style['size']} pt text (“{' '.join(s['paragraphs'])[:40]}”) is below {MIN_BODY_PT} pt (fine for a label or source note, too small for body text)")
            if style.get("color") and style.get("fill") and contrast(style["color"], style["fill"]) < MIN_CONTRAST:
                issues.append(f"shape {s['id']}: contrast {contrast(style['color'], style['fill']):.1f}:1 between text and fill, below {MIN_CONTRAST}:1")
        if words > MAX_WORDS:
            issues.append(f"{words} words on the slide (more than {MAX_WORDS})")
        boxed = [s for s in slide["shapes"] if s.get("box")]
        for s in boxed:
            b = s["box"]
            if b["x"] < -1 or b["y"] < -1 or b["x"] + b["w"] > width_pt + 1 or b["y"] + b["h"] > height_pt + 1:
                issues.append(f"shape {s['id']}: runs off the slide ({b})")
        for edge in ("x", "y"):
            values = sorted({round(s["box"][edge], 1) for s in boxed})
            for a, b in zip(values, values[1:]):
                if NEAR[0] <= b - a <= NEAR[1]:
                    issues.append(f"{'left' if edge == 'x' else 'top'} edges at {a} and {b} pt nearly line up")
        sized = [s for s in texts if s.get("style", {}).get("size") and s.get("box")]
        if sized:
            title = max(sized, key=lambda s: s["style"]["size"])
            titles.append((n, title["box"]["x"], title["box"]["y"], title["style"]["size"]))
        report["slides"].append({"slide": n, "words": words, "boxes": len(slide["shapes"]), "issues": issues})
    if len(fonts) > 2:
        report["deck"].append(f"{len(fonts)} typefaces set on text: {', '.join(f for f, _ in fonts.most_common())}")
    if len(sizes) > 7:
        report["deck"].append(f"{len(sizes)} different text sizes: {', '.join(str(s) for s in sorted(sizes))} pt; a type scale needs four to six")
    if len(titles) >= 3:
        # Where most slides put their largest text; slides that nearly match it look careless.
        (cx, cy), count = Counter((round(x / 4), round(y / 4)) for _, x, y, _ in titles).most_common(1)[0]
        near = [f"slide {n} ({x:.0f}, {y:.0f})" for n, x, y, _ in titles
                if (round(x / 4), round(y / 4)) != (cx, cy) and abs(x - cx * 4) <= 24 and abs(y - cy * 4) <= 24]
        if count >= 3 and near:
            report["deck"].append(f"{count} slides put their largest text at ({cx * 4}, {cy * 4}) pt; these sit just off it: " + ", ".join(near))
        elif count < 3:
            report["deck"].append(f"the largest text sits in {len({(round(x / 4), round(y / 4)) for _, x, y, _ in titles})} different places across {len(titles)} slides")
    report["fonts"] = dict(fonts.most_common())
    report["sizes"] = dict(sorted(sizes.items()))
    return report


def _slide(data, number):
    if not isinstance(number, int) or not 1 <= number <= len(data["slides"]):
        raise ValueError(f"There is no slide {number}.")
    return data["slides"][number - 1]


def _shape(data, op):
    slide = _slide(data, op.get("slide"))
    shape = next((s for s in slide["shapes"] if s["id"] == str(op.get("shape"))), None)
    if shape is None:
        raise ValueError(f"Slide {op['slide']} has no shape {op.get('shape')}.")
    return shape


def apply(data, ops):
    for op in ops:
        kind = op.get("op")
        if kind == "box":
            shape = _shape(data, op)
            if "box" not in shape:
                raise ValueError(f"Shape {shape['id']} sits in a group; move the group.")
            shape["box"] = {**shape["box"], **{k: round(float(v), 2) for k, v in op["box"].items()}}
        elif kind == "style":
            shape = _shape(data, op)
            if shape["kind"] != "text":
                raise ValueError(f"Shape {shape['id']} is not text; only text takes a style.")
            shape["style"] = {**shape.get("style", {}), **op["style"]}
        elif kind == "text":
            shape = _shape(data, op)
            if shape["kind"] != "text":
                raise ValueError(f"Shape {shape['id']} is not a text box.")
            shape["paragraphs"] = op["paragraphs"]
        elif kind == "theme":
            theme = data.setdefault("theme", {})
            for key in ("colors", "fonts"):
                if key in op:
                    theme[key] = {**theme.get(key, {}), **op[key]}
        elif kind in ("swap_color", "swap_font"):
            key = "swap_colors" if kind == "swap_color" else "swap_fonts"
            data.setdefault("theme", {}).setdefault(key, {})[op["from"]] = op["to"]
        elif kind == "order":
            order = op["slides"]
            if sorted(order) != list(range(1, len(data["slides"]) + 1)):
                raise ValueError("An order lists every slide number once.")
            data["slides"] = [data["slides"][n - 1] for n in order]
        else:
            raise ValueError(f"Unknown operation {kind!r}.")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("master")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("edit")
    p.add_argument("master")
    p.add_argument("ops")
    args = parser.parse_args()
    master, data, original = _load(args.master)
    if args.cmd == "inspect":
        from pptx import Presentation

        source, _, _ = office_master.baseline(master.parent, master.stem)
        deck = Presentation(str(source))
        report = inspect(data, deck.slide_width / 12700, deck.slide_height / 12700)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return
        print(f"Typefaces: {report['fonts']}\nSizes (pt): {report['sizes']}")
        for line in report["deck"]:
            print(f"DECK  {line}")
        for s in report["slides"]:
            for line in s["issues"]:
                print(f"S{s['slide']:<3} {line}")
        print(f"{sum(len(s['issues']) for s in report['slides']) + len(report['deck'])} findings")
        return
    ops = json.loads(Path(args.ops).read_text())
    try:
        data = apply(data, ops if isinstance(ops, list) else [ops])
        office_master.validate(data, original)
    except (ValueError, KeyError, TypeError) as exc:
        sys.exit(f"REFUSED {exc}; the master is unchanged.")
    master.write_text(office_master.encode(data))
    print(f"applied {len(ops) if isinstance(ops, list) else 1} operations to {master.name}")


if __name__ == "__main__":
    main()
