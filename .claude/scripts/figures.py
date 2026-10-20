#!/usr/bin/env python3
"""Render the ```figure blocks in a report into styled charts.

A report carries its charts as data, not as images: each is a fenced ```figure
block holding a JSON spec with its numbers, its evidence IDs, and its message.
That keeps a chart auditable the same way a sentence is — the figures are part
of the reviewable source, and re-rendering in another style changes nothing but
the pixels.

    python3 .claude/scripts/figures.py check  report.md
    python3 .claude/scripts/figures.py build  report.md --style meridian \\
            --outdir outputs/<slug>/figures -o outputs/<slug>/export/report-styled.md
    python3 .claude/scripts/figures.py types
    python3 .claude/scripts/figures.py demo --style helix -o /tmp/demo

`build` writes one PNG (and SVG) per figure and emits a copy of the markdown
with each block replaced by an image + numbered caption. The original report.md
is never modified. Cross-references written `[[F3]]` resolve to "Exhibit 5".

Adding a chart type: write a `_draw_<type>(ax, spec, ctx)` function and list it
in TYPES. Adding a style: drop a JSON in .claude/styles/. Neither needs changes
anywhere else.
"""

import argparse
import copy
import json
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as stylelib  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, to_rgb  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

BLOCK = re.compile(r"^```figure[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)
# A markdown image the author placed by hand, as opposed to one this script
# renders from a ```figure block. Its path is written relative to report.md,
# which is the wrong base once the styled copy is written into export/<style>/.
MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")

TABLE_CAP = re.compile(r"^\*\*(?:Table|Exhibit):\*\*[ \t]*(.+?)[ \t]*\{#(T\w+)\}[ \t]*$", re.M)
XREF = re.compile(r"\[\[([FT]\w+)\]\]")
CITE = re.compile(r"\[E\d+\]")

TYPES = ("bar", "hbar", "stacked_bar", "stacked_hbar", "line", "area",
         "scatter", "dot", "dumbbell", "slope", "waterfall", "heatmap",
         "donut", "stat", "band_line_bar", "coverage_bubbles")

NEEDS_SERIES = ("bar", "hbar", "stacked_bar", "stacked_hbar", "line", "area",
                "scatter", "dot", "dumbbell", "slope", "band_line_bar")


# ---------------------------------------------------------------- helpers

def resolve_font(candidates):
    """First font in the stack that is actually installed, else a safe default."""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            return name
    for fallback in ("Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"):
        if fallback in installed:
            return fallback
    return "DejaVu Sans"


class Ctx:
    """Everything a draw function needs that isn't in the spec."""

    def __init__(self, st):
        self.st = st
        c, f, ch = st["color"], st["fonts"], st["chart"]
        self.c, self.ch = c, ch
        self.head = resolve_font(f["heading"])
        self.body = resolve_font(f["body"])
        self.series = st["series"]
        self.seq = st["sequential"]
        self.div = st["diverging"]
        self.assigned = {}          # series name -> colour, stable across the document
        self.base = f.get("base_pt", 10.5) * ch.get("font_scale", 1.0)

    def color_for(self, name, index):
        """One colour per series *name*, consistent across every figure."""
        if name not in self.assigned:
            used = set(self.assigned.values())
            pick = next((s for s in self.series if s not in used), None)
            self.assigned[name] = pick or self.series[index % len(self.series)]
        return self.assigned[name]

    def cmap(self, kind="sequential"):
        cols = self.seq if kind == "sequential" else self.div
        return LinearSegmentedColormap.from_list(kind, cols)


def fmt(v, spec):
    """Format a data value for a label, honouring unit/decimals/prefix."""
    if v is None:
        return ""
    dec = spec.get("decimals")
    if dec is None:
        av = abs(v)
        dec = 0 if float(v).is_integer() else (1 if av >= 1 else 2)
    s = f"{v:,.{dec}f}"
    if spec.get("thousands") is False:
        s = s.replace(",", "")
    return f"{spec.get('prefix', '')}{s}{spec.get('unit', '')}"


def wrap(text, width):
    return "\n".join(textwrap.wrap(text, width)) if text else ""


def series_of(spec):
    ser = spec.get("series") or []
    if not ser and "values" in spec:
        ser = [{"name": spec.get("name", ""), "values": spec["values"]}]
    return ser


def apply_sort(spec):
    """sort: 'desc' | 'asc' | 'none' — only meaningful for single-series category charts."""
    order = spec.get("sort", "none")
    ser = series_of(spec)
    cats = spec.get("categories")
    if order in ("desc", "asc") and cats and len(ser) == 1:
        # unobtained values always sort last, whichever direction the rest goes
        desc = order == "desc"
        pairs = sorted(zip(cats, ser[0]["values"], range(len(cats))),
                       key=lambda p: (p[1] is not None if desc else p[1] is None,
                                      p[1] if p[1] is not None else 0),
                       reverse=desc)
        spec["categories"] = [p[0] for p in pairs]
        ser[0]["values"] = [p[1] for p in pairs]
        spec["_label_indices"] = [p[2] for p in pairs]
    return spec


def bar_colors(spec, ctx, cats, base):
    """Highlight named categories in the accent, mute everything else."""
    hi = spec.get("highlight")
    if not hi:
        return [base] * len(cats)
    hi = [hi] if isinstance(hi, str) else hi
    dim = ctx.c.get("mute_fill", ctx.c["rule"])
    return [ctx.c["accent"] if c in hi else dim for c in cats]


def frame(ax, ctx, spec, axis="y"):
    """Gridlines and spines, per the style's chart block."""
    ch = ctx.ch
    ax.set_axisbelow(True)
    if axis in ("y", "both"):
        ax.yaxis.grid(True, color=ch["grid"], linewidth=0.6)
    if axis in ("x", "both"):
        ax.xaxis.grid(True, color=ch["grid"], linewidth=0.6)
    if axis == "none":
        ax.grid(False)
    keep = {"left_bottom": ("left", "bottom"), "bottom": ("bottom",),
            "left": ("left",), "none": ()}.get(ch.get("spines", "left_bottom"), ())
    for side, sp in ax.spines.items():
        sp.set_visible(side in keep)
        sp.set_color(ch["axis"])
        sp.set_linewidth(0.7)
    ax.tick_params(colors=ctx.c["muted"], length=0, labelsize=ctx.base * 0.78)
    from matplotlib.ticker import FuncFormatter
    def _thousands(v, _pos):
        return f"{v:,.0f}" if abs(v) >= 1000 else (f"{v:g}")
    # Thousands separators only where the axis reaches 1,000; elsewhere matplotlib's
    # default keeps one consistent number of decimals across the ticks.
    if axis in ("y", "both") and max(abs(v) for v in ax.get_ylim()) >= 1000:
        ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    if axis in ("x", "both") and max(abs(v) for v in ax.get_xlim()) >= 1000:
        ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_fontname(ctx.body)
    if spec.get("x_label"):
        ax.set_xlabel(spec["x_label"], fontsize=ctx.base * 0.78, color=ctx.c["muted"],
                      fontname=ctx.head, labelpad=6)
    if spec.get("y_label"):
        ax.set_ylabel(spec["y_label"], fontsize=ctx.base * 0.78, color=ctx.c["muted"],
                      fontname=ctx.head, labelpad=6)


def legend(ax, ctx, spec, handles=None, labels=None, n=None):
    if spec.get("legend") is False:
        return
    kw = dict(frameon=False, fontsize=ctx.base * 0.78, loc="lower left",
              bbox_to_anchor=(0, 1.0), ncol=n or 4, handlelength=1.1,
              columnspacing=1.4, handletextpad=0.5, borderaxespad=0.4)
    leg = ax.legend(handles, labels, **kw) if handles else ax.legend(**kw)
    if leg:
        for t in leg.get_texts():
            t.set_color(ctx.c["body"])
            t.set_fontname(ctx.body)


def missing_idx(spec):
    """Indices where a value is `null` — data the research could not obtain."""
    out = set()
    for s in series_of(spec):
        out |= {i for i, v in enumerate(s.get("values", [])) if v is None}
    return sorted(out)


def draw_placeholders(ax, spec, ctx, idx, horizontal=False):
    """Missing data is drawn, not omitted.

    A category the research could not source gets a hatched slot labelled
    'to obtain' rather than a silent gap — so the reader sees the hole, and so
    whoever finishes the table by hand knows exactly which cell is theirs.
    """
    if not idx:
        return
    lo, hi = (ax.get_xlim() if horizontal else ax.get_ylim())
    extent = (hi - lo) * 0.055
    w = ctx.ch.get("bar_width", 0.62)
    for j in idx:
        if horizontal:
            ax.barh(j, extent, height=w, color="none", edgecolor=ctx.c["muted"],
                    hatch="////", linewidth=0.7, zorder=3)
            ax.annotate("to obtain", (extent, j), xytext=(6, 0), va="center",
                        textcoords="offset points", fontsize=ctx.base * 0.68,
                        fontname=ctx.body, color=ctx.c["muted"], style="italic")
        else:
            ax.bar(j, extent, width=w, color="none", edgecolor=ctx.c["muted"],
                   hatch="////", linewidth=0.7, zorder=3)
            ax.annotate("to obtain", (j, extent), xytext=(0, 4), ha="center",
                        textcoords="offset points", fontsize=ctx.base * 0.68,
                        fontname=ctx.body, color=ctx.c["muted"], style="italic")


def label_text(ctx, key, value, spec):
    return ctx.ch.get("label_text", {}).get(key, fmt(value, spec))


def contrast_color(fill, background, alpha=1.0):
    rgb = tuple(alpha * c + (1 - alpha) * bg for c, bg in zip(to_rgb(fill), to_rgb(background)))
    linear = tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
    luminance = sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))
    return "#111418" if luminance > 0.179 else "#FFFFFF"


def label_color(ctx, fill=None, inside=False):
    chosen = ctx.ch.get("label_color", "auto")
    if chosen != "auto":
        return chosen
    if not inside or fill is None:
        return ctx.c["body"]
    if ctx.ch.get("bar_fill", "solid") in ("outline", "hatched"):
        fill = ctx.c["surface"]
    return contrast_color(fill, ctx.c["surface"], ctx.ch.get("bar_opacity", 1.0))


def bar_fill_kwargs(ctx, colors):
    fill = ctx.ch.get("bar_fill", "solid")
    alpha = ctx.ch.get("bar_opacity", 1.0)
    if fill == "outline":
        return {"color": "none", "edgecolor": colors, "linewidth": 1.2, "alpha": alpha}
    if fill == "hatched":
        return {"color": ctx.c["surface"], "edgecolor": colors, "hatch": "////", "linewidth": 0.8, "alpha": alpha}
    return {"color": colors, "alpha": alpha}


def value_label(ax, x, y, v, ctx, spec, key, fill=None, horizontal=False):
    if not spec.get("value_labels", ctx.ch.get("value_labels", True)):
        return
    inside = ctx.ch.get("label_position", "auto") == "inside"
    if horizontal:
        off, ha, va = ((-5, 0), "right", "center") if inside else ((5, 0), "left", "center")
    else:
        off, ha, va = ((0, -5), "center", "top") if inside else ((0, 3), "center", "bottom")
    ax.annotate(label_text(ctx, key, v, spec), (x, y), textcoords="offset points",
                xytext=off, ha=ha, va=va,
                fontsize=ctx.base * 0.72 * ctx.ch.get("label_font_scale", 1.0), fontname=ctx.body,
                color=label_color(ctx, fill, inside))


def soften_bars(ax, bars, radius_px):
    """Give ordinary bars subtle rounded corners without moving their exact ends."""
    if not radius_px:
        return
    origin = ax.transData.transform((0, 0))
    px_x = abs(ax.transData.transform((1, 0))[0] - origin[0])
    px_y = abs(ax.transData.transform((0, 1))[1] - origin[1])
    if not px_x or not px_y:
        return
    for bar in bars:
        width, height = abs(bar.get_width()), abs(bar.get_height())
        if not width or not height:
            continue
        radius = min(radius_px, width * px_x / 4, height * px_y / 4) / px_x
        rounded = FancyBboxPatch(
            (min(bar.get_x(), bar.get_x() + bar.get_width()),
             min(bar.get_y(), bar.get_y() + bar.get_height())),
            width, height, boxstyle=f"round,pad=0,rounding_size={radius}",
            mutation_aspect=px_x / px_y, transform=ax.transData,
        )
        bar.set_clip_path(rounded)


# ---------------------------------------------------------------- draw functions

def _draw_bar(ax, spec, ctx, horizontal=False):
    cats, ser = spec["categories"], series_of(spec)
    n, w = len(ser), ctx.ch.get("bar_width", 0.62)
    idx = range(len(cats))
    label_indices = spec.get("_label_indices") or list(idx)
    bars = []
    for i, s in enumerate(ser):
        col = ctx.color_for(s.get("name", f"s{i}"), i)
        cols = bar_colors(spec, ctx, cats, col) if n == 1 else col
        off = (i - (n - 1) / 2) * (w / n)
        pos = [x + off for x in idx]
        vals = s["values"]
        plot = [0 if v is None else v for v in vals]
        paint = bar_fill_kwargs(ctx, cols)
        if horizontal:
            bars.extend(ax.barh(pos, plot, height=w / n, label=s.get("name"), zorder=3, **paint))
            for j, (p, v) in enumerate(zip(pos, vals)):
                if v is not None:
                    value_label(ax, v, p, v, ctx, spec, f"s{i}c{label_indices[j]}", cols[j] if isinstance(cols, list) else cols, True)
        else:
            bars.extend(ax.bar(pos, plot, width=w / n, label=s.get("name"), zorder=3, **paint))
            for j, (p, v) in enumerate(zip(pos, vals)):
                if v is not None:
                    value_label(ax, p, v, v, ctx, spec, f"s{i}c{label_indices[j]}", cols[j] if isinstance(cols, list) else cols)
    if horizontal:
        ax.set_yticks(list(idx), [wrap(c, 26) for c in cats])
        ax.invert_yaxis()
        frame(ax, ctx, spec, axis="x")
        ax.margins(x=0.14)
    else:
        ax.set_xticks(list(idx), [wrap(c, 14) for c in cats])
        frame(ax, ctx, spec, axis="y")
        ax.margins(y=0.16)
    soften_bars(ax, bars, ctx.ch.get("bar_corner_radius_px", 0))
    draw_placeholders(ax, spec, ctx, missing_idx(spec), horizontal)
    if n > 1:
        legend(ax, ctx, spec, n=min(n, 4))
    elif spec.get("highlight_legend") and spec.get("highlight"):
        from matplotlib.patches import Patch
        on, off = spec["highlight_legend"][:2]
        col = ctx.color_for(ser[0].get("name", "s0"), 0)
        legend(ax, ctx, spec, handles=[Patch(color=ctx.c.get("accent", col)), Patch(color=ctx.c.get("mute_fill", ctx.c["rule"]))],
               labels=[on, off], n=2)


def _draw_hbar(ax, spec, ctx):
    _draw_bar(ax, spec, ctx, horizontal=True)


def _draw_stacked_bar(ax, spec, ctx, horizontal=False):
    cats, ser = spec["categories"], series_of(spec)
    idx = list(range(len(cats)))
    w = ctx.ch.get("bar_width", 0.62)
    base = [0.0] * len(cats)
    for i, s in enumerate(ser):
        col = ctx.color_for(s.get("name", f"s{i}"), i)
        vals = [v or 0 for v in s["values"]]
        if horizontal:
            ax.barh(idx, vals, left=base, height=w, label=s.get("name"), zorder=3,
                    **bar_fill_kwargs(ctx, col))
        else:
            ax.bar(idx, vals, bottom=base, width=w, label=s.get("name"), zorder=3,
                   **bar_fill_kwargs(ctx, col))
        if spec.get("segment_labels", True) and ctx.ch.get("value_labels", True):
            for j, v in enumerate(vals):
                if v and v / max(sum(x) for x in [[sum(c) for c in zip(*[[y or 0 for y in t["values"]] for t in ser])]]) > 0.05:
                    pos, mid = (v / 2 + base[j], idx[j])
                    outside = ctx.ch.get("label_position", "auto") == "outside"
                    label = label_text(ctx, f"s{i}c{j}", v, spec)
                    size = ctx.base * 0.68 * ctx.ch.get("label_font_scale", 1.0)
                    if outside:
                        end = base[j] + v
                        ax.annotate(label, (end, idx[j]) if horizontal else (idx[j], end),
                                    xytext=(5, 0) if horizontal else (0, 3), textcoords="offset points",
                                    ha="left" if horizontal else "center", va="center" if horizontal else "bottom",
                                    fontsize=size, fontname=ctx.body, color=label_color(ctx))
                    else:
                        ax.text(*(pos, mid) if horizontal else (mid, pos), label,
                                ha="center", va="center", fontsize=size,
                                fontname=ctx.body, color=label_color(ctx, col, True))
        base = [b + v for b, v in zip(base, vals)]
    empty = [j for j in idx if all(t["values"][j] is None for t in ser)]
    if spec.get("total_labels", ctx.ch.get("label_position", "auto") != "outside"):
        for j, tot in enumerate(base):
            if j in empty:
                continue
            if horizontal:
                ax.annotate(fmt(tot, spec), (tot, idx[j]), xytext=(4, 0),
                            textcoords="offset points", va="center",
                            fontsize=ctx.base * 0.72, fontname=ctx.body, color=ctx.c["ink"])
            else:
                ax.annotate(fmt(tot, spec), (idx[j], tot), xytext=(0, 3),
                            textcoords="offset points", ha="center",
                            fontsize=ctx.base * 0.72, fontname=ctx.body, color=ctx.c["ink"])
    if horizontal:
        ax.set_yticks(idx, [wrap(c, 26) for c in cats]); ax.invert_yaxis()
        frame(ax, ctx, spec, axis="x"); ax.margins(x=0.12)
    else:
        ax.set_xticks(idx, [wrap(c, 14) for c in cats])
        frame(ax, ctx, spec, axis="y"); ax.margins(y=0.14)
    draw_placeholders(ax, spec, ctx, empty, horizontal)
    legend(ax, ctx, spec, n=min(len(ser), 4))


def _draw_stacked_hbar(ax, spec, ctx):
    _draw_stacked_bar(ax, spec, ctx, horizontal=True)


def _draw_line(ax, spec, ctx, fill=False, stack=False):
    cats, ser = spec["categories"], series_of(spec)
    xs = spec.get("x") or list(range(len(cats)))
    lw = ctx.ch.get("line_width", 2.0)
    hi = spec.get("highlight")
    hi = [hi] if isinstance(hi, str) else (hi or [])
    base = [0.0] * len(xs)
    for i, s in enumerate(ser):
        name = s.get("name", f"s{i}")
        col = ctx.color_for(name, i)
        if hi and name not in hi:
            col = ctx.c.get("mute_fill", ctx.c["rule"])
        vals = s["values"]
        if stack:
            top = [b + (v or 0) for b, v in zip(base, vals)]
            ax.fill_between(xs, base, top, color=col, label=name, zorder=3, linewidth=0,
                            alpha=ctx.ch.get("stacked_fill_opacity", 1.0))
            base = top
            continue
        ax.plot(xs, vals, color=col, linewidth=lw,
                linestyle=ctx.ch.get("line_style", "solid"), label=name, zorder=3,
                alpha=ctx.ch.get("line_opacity", 1.0),
                marker="o" if spec.get("markers", len(xs) <= 12) else None,
                markersize=ctx.ch.get("marker_size", 4.5), markeredgewidth=0,
                solid_capstyle="round")
        if fill:
            ax.fill_between(xs, vals, color=col, alpha=ctx.ch.get("area_fill_opacity", 0.13), zorder=2, linewidth=0)
        if spec.get("direct_labels", len(ser) <= 5):
            last = next((k for k in range(len(vals) - 1, -1, -1) if vals[k] is not None), None)
            if last is not None:
                ax.annotate(f" {name}", (xs[last], vals[last]), xytext=(5, 0),
                            textcoords="offset points", va="center",
                            fontsize=ctx.base * 0.76, fontname=ctx.head,
                            color=col, fontweight="bold")
    step = spec.get("tick_every") or max(1, -(-len(cats) // 10))
    keep = [k for k in range(len(cats)) if k % step == 0]
    if step > 1 and (len(cats) - 1) - keep[-1] >= step:
        keep.append(len(cats) - 1)               # label the final period when it sits clear of the last tick
    ax.set_xticks([xs[k] for k in keep], [wrap(str(cats[k]), 12) for k in keep])
    frame(ax, ctx, spec, axis="y")
    ax.margins(x=0.02 if spec.get("direct_labels", len(ser) <= 5) else 0.02, y=0.16)
    allv = [v for s in ser for v in s["values"] if v is not None]
    if allv and min(allv) >= 0 and spec.get("y_min") is None:
        ax.set_ylim(bottom=0)                     # spending cannot be negative; no dead band below zero
    elif spec.get("y_min") is not None:
        ax.set_ylim(bottom=spec["y_min"])
    if spec.get("direct_labels", len(ser) <= 5) and not stack:
        ax.set_xlim(right=max(xs) + (max(xs) - min(xs)) * 0.22 if len(xs) > 1 else None)
    else:
        legend(ax, ctx, spec, n=min(len(ser), 4))
    for a in spec.get("annotate", []):
        _annotate(ax, a, ctx, xs, cats)


def _draw_area(ax, spec, ctx):
    _draw_line(ax, spec, ctx, stack=bool(spec.get("stacked", True)),
               fill=not spec.get("stacked", True))


def _draw_scatter(ax, spec, ctx):
    for i, s in enumerate(series_of(spec)):
        col = ctx.color_for(s.get("name", f"s{i}"), i)
        pts = s.get("points", [])
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=48, color=col,
                   label=s.get("name"), zorder=3, edgecolors="none", alpha=ctx.ch.get("line_opacity", 0.85))
        for p, lab in zip(pts, s.get("labels", [])):
            ax.annotate(lab, (p[0], p[1]), xytext=(6, 3), textcoords="offset points",
                        fontsize=ctx.base * 0.7, fontname=ctx.body, color=ctx.c["muted"])
    frame(ax, ctx, spec, axis="both")
    if len(series_of(spec)) > 1:
        legend(ax, ctx, spec)


def _draw_dot(ax, spec, ctx):
    """Ranked dot / lollipop — the honest alternative to a long bar chart."""
    spec = apply_sort(spec)
    cats, ser = spec["categories"], series_of(spec)
    idx = list(range(len(cats)))
    for i, s in enumerate(ser):
        col = ctx.color_for(s.get("name", f"s{i}"), i)
        cols = bar_colors(spec, ctx, cats, col) if len(ser) == 1 else [col] * len(cats)
        vals = s["values"]
        have = [j for j, v in enumerate(vals) if v is not None]
        if len(ser) == 1:
            ax.hlines([idx[j] for j in have], 0, [vals[j] for j in have],
                      color=[cols[j] for j in have], linewidth=1.4, zorder=2)
        ax.scatter([vals[j] for j in have], [idx[j] for j in have], s=70,
                   color=[cols[j] for j in have], zorder=3, label=s.get("name"),
                   edgecolors="none")
        for j in have:
            ax.annotate(fmt(vals[j], spec), (vals[j], idx[j]), xytext=(9, 0),
                        textcoords="offset points", va="center",
                        fontsize=ctx.base * 0.72, fontname=ctx.body, color=ctx.c["body"])
    ax.set_yticks(idx, [wrap(c, 30) for c in cats])
    ax.invert_yaxis()
    frame(ax, ctx, spec, axis="x")
    ax.margins(x=0.16, y=0.06)
    draw_placeholders(ax, spec, ctx, missing_idx(spec), horizontal=True)
    if len(ser) > 1:
        legend(ax, ctx, spec)


def _draw_dumbbell(ax, spec, ctx):
    """Two states per category — before/after, us/them, min/max."""
    cats, ser = spec["categories"], series_of(spec)
    if len(ser) != 2:
        raise ValueError("dumbbell needs exactly two series")
    idx = list(range(len(cats)))
    a, b = ser[0]["values"], ser[1]["values"]
    ca = ctx.color_for(ser[0].get("name", "a"), 0)
    cb = ctx.color_for(ser[1].get("name", "b"), 1)
    for j in idx:
        ax.plot([a[j], b[j]], [j, j], color=ctx.c["rule"], linewidth=2.2, zorder=2)
    ax.scatter(a, idx, s=70, color=ca, zorder=3, label=ser[0].get("name"), edgecolors="none")
    ax.scatter(b, idx, s=70, color=cb, zorder=3, label=ser[1].get("name"), edgecolors="none")
    for j in idx:
        far, near = (b[j], a[j]) if b[j] >= a[j] else (a[j], b[j])
        ax.annotate(fmt(far, spec), (far, j), xytext=(9, 0), textcoords="offset points",
                    va="center", fontsize=ctx.base * 0.72, fontname=ctx.body, color=ctx.c["body"])
        ax.annotate(fmt(near, spec), (near, j), xytext=(-9, 0), textcoords="offset points",
                    va="center", ha="right", fontsize=ctx.base * 0.72,
                    fontname=ctx.body, color=ctx.c["muted"])
    ax.set_yticks(idx, [wrap(c, 28) for c in cats])
    ax.invert_yaxis()
    frame(ax, ctx, spec, axis="x")
    ax.margins(x=0.2, y=0.06)
    legend(ax, ctx, spec, n=2)


def _draw_slope(ax, spec, ctx):
    """Two periods, one line per entity — reads rank change at a glance."""
    cats, ser = spec["categories"], series_of(spec)
    if len(cats) != 2:
        raise ValueError("slope needs exactly two categories (the two periods)")
    hi = spec.get("highlight")
    hi = [hi] if isinstance(hi, str) else (hi or [])
    for i, s in enumerate(ser):
        name = s.get("name", f"s{i}")
        col = ctx.color_for(name, i)
        if hi and name not in hi:
            col = ctx.c.get("mute_fill", ctx.c["rule"])
        v0, v1 = s["values"]
        ax.plot([0, 1], [v0, v1], color=col, linewidth=ctx.ch.get("line_width", 2.0),
                marker="o", markersize=ctx.ch.get("marker_size", 4.5), markeredgewidth=0, zorder=3,
                alpha=ctx.ch.get("line_opacity", 1.0))
        ax.annotate(f"{name}  {fmt(v0, spec)}", (0, v0), xytext=(-8, 0),
                    textcoords="offset points", ha="right", va="center",
                    fontsize=ctx.base * 0.74, fontname=ctx.body, color=col)
        ax.annotate(f"{fmt(v1, spec)}  {name}", (1, v1), xytext=(8, 0),
                    textcoords="offset points", ha="left", va="center",
                    fontsize=ctx.base * 0.74, fontname=ctx.body, color=col)
    ax.set_xticks([0, 1], cats)
    ax.set_xlim(-0.55, 1.55)
    ax.get_yaxis().set_visible(False)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(colors=ctx.c["ink"], length=0, labelsize=ctx.base * 0.82)
    for lbl in ax.get_xticklabels():
        lbl.set_fontname(ctx.head)
    ax.margins(y=0.12)


def _draw_waterfall(ax, spec, ctx):
    """Bridge chart: how a total got from one number to another."""
    steps = spec["steps"]
    pos, run, bottoms, heights, cols = [], 0.0, [], [], []
    for i, s in enumerate(steps):
        kind = s.get("type", "delta")
        v = s["value"]
        if kind in ("start", "total"):
            bottoms.append(0.0); heights.append(v); cols.append(ctx.c["ink"])
            run = v
        else:
            bottoms.append(run if v >= 0 else run + v)
            heights.append(abs(v))
            cols.append(ctx.c["accent"] if v >= 0 else spec.get("negative_color", ctx.series[1]))
            run += v
        pos.append(i)
    ax.bar(pos, heights, bottom=bottoms, width=ctx.ch.get("bar_width", 0.62),
           zorder=3, **bar_fill_kwargs(ctx, cols))
    for i, s in enumerate(steps):
        top = bottoms[i] + heights[i]
        v = s["value"]
        label = fmt(v, spec) if s.get("type", "delta") in ("start", "total") else \
            ("+" if v >= 0 else "−") + fmt(abs(v), spec)
        ax.annotate(label, (i, top), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=ctx.base * 0.72, fontname=ctx.body,
                    color=ctx.c["body"])
        if i < len(steps) - 1 and s.get("type", "delta") != "total":
            ax.plot([i + 0.31, i + 0.69], [bottoms[i] + heights[i] if v >= 0 else bottoms[i]] * 2,
                    color=ctx.c["rule"], linewidth=0.8, zorder=1)
    ax.set_xticks(pos, [wrap(s["label"], 12) for s in steps])
    frame(ax, ctx, spec, axis="y")
    ax.margins(y=0.16)


def _draw_heatmap(ax, spec, ctx):
    rows, cols_, vals = spec["rows"], spec["columns"], spec["values"]
    kind = spec.get("scale", "sequential")
    im = ax.imshow(vals, cmap=ctx.cmap(kind), aspect="auto",
                   vmin=spec.get("v_min"), vmax=spec.get("v_max"))
    ax.set_xticks(range(len(cols_)), [wrap(str(c), 12) for c in cols_])
    ax.set_yticks(range(len(rows)), [wrap(str(r), 24) for r in rows])
    ax.tick_params(colors=ctx.c["muted"], length=0, labelsize=ctx.base * 0.74)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_fontname(ctx.body)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.grid(False)
    if spec.get("cell_labels", True):
        for i, row in enumerate(vals):
            for j, v in enumerate(row):
                if v is None:
                    continue
                fill = im.cmap(im.norm(v))
                chosen = ctx.ch.get("label_color", "auto")
                color = chosen if chosen != "auto" else contrast_color(fill[:3], ctx.c["surface"])
                ax.text(j, i, label_text(ctx, f"r{i}c{j}", v, spec), ha="center", va="center",
                        fontsize=ctx.base * 0.7 * ctx.ch.get("label_font_scale", 1.0), fontname=ctx.body,
                        color=color)
    else:
        cb = ax.figure.colorbar(im, ax=ax, shrink=0.7, pad=0.02)
        cb.outline.set_visible(False)
        cb.ax.tick_params(colors=ctx.c["muted"], labelsize=ctx.base * 0.7, length=0)


def _draw_donut(ax, spec, ctx):
    cats, vals = spec["categories"], spec["values"]
    cols = [ctx.color_for(c, i) for i, c in enumerate(cats)]
    total = sum(vals)
    w, _ = ax.pie(vals, colors=cols, startangle=90, counterclock=False,
                  wedgeprops=dict(width=0.42, edgecolor=ctx.c["surface"], linewidth=1.5))
    ax.set_aspect("equal")
    for wedge, cat, v in zip(w, cats, vals):
        ang = (wedge.theta1 + wedge.theta2) / 2
        import math
        x, y = 0.79 * math.cos(math.radians(ang)), 0.79 * math.sin(math.radians(ang))
        ax.text(x, y, f"{cat}\n{v / total * 100:.0f}%", ha="center", va="center",
                fontsize=ctx.base * 0.72, fontname=ctx.body, color=ctx.c["body"])
    if spec.get("center"):
        ax.text(0, 0, spec["center"], ha="center", va="center",
                fontsize=ctx.base * 1.2, fontname=ctx.head,
                color=ctx.c["ink"], fontweight="bold")


def _draw_stat(ax, spec, ctx):
    """A row of KPI tiles. Each stat still carries its own [E#] in the caption."""
    stats = spec["stats"]
    n = len(stats)
    ax.set_xlim(0, n); ax.set_ylim(0, 1); ax.axis("off")
    for i, s in enumerate(stats):
        ax.add_patch(FancyBboxPatch((i + 0.03, 0.06), 0.94, 0.88,
                                    boxstyle="round,pad=0,rounding_size=0.02",
                                    facecolor=ctx.c["surface_alt"],
                                    edgecolor=ctx.c["rule"], linewidth=0.7))
        ax.plot([i + 0.03, i + 0.03], [0.06, 0.94], color=ctx.c["accent"], linewidth=3,
                solid_capstyle="butt")
        got = s.get("value") is not None
        ax.text(i + 0.5, 0.62, str(s["value"]) if got else "to obtain",
                ha="center", va="center",
                fontsize=ctx.base * (2.0 if got else 0.95), fontname=ctx.head,
                color=ctx.c["ink"] if got else ctx.c["muted"],
                fontweight="bold" if got else "normal",
                style="normal" if got else "italic")
        ax.text(i + 0.5, 0.32, wrap(s["label"], 26), ha="center", va="center",
                fontsize=ctx.base * 0.76, fontname=ctx.body, color=ctx.c["muted"])
        if s.get("delta"):
            ax.text(i + 0.5, 0.15, s["delta"], ha="center", va="center",
                    fontsize=ctx.base * 0.72, fontname=ctx.body, color=ctx.c["accent"])


def _annotate(ax, a, ctx, xs, cats):
    """Point an arrow at a category, with a short label. The 'so what' on the chart."""
    if "category" in a and a["category"] in cats:
        x = xs[cats.index(a["category"])]
    else:
        x = a.get("x", 0)
    ax.annotate(a["text"], xy=(x, a["y"]) if "y" in a else (x, ax.get_ylim()[1] * 0.92),
                xytext=(a.get("dx", 12), a.get("dy", 14)), textcoords="offset points",
                fontsize=ctx.base * 0.72, fontname=ctx.body, color=ctx.c["ink"],
                arrowprops=dict(arrowstyle="-", color=ctx.c["muted"], linewidth=0.8))


def _draw_band_line_bar(ax, spec, ctx):
    """Cumulative lines over a low-high band, with a stacked comparison bar on a shared y-axis.

    Built to set a single commitment against a long cumulative series on one scale:
    the band carries the range, the lines carry the components, and the side bar is
    drawn on the same axis so its size reads directly against the history.
    `"bar_inline": true` draws the bar on the main axis, just past the last year,
    instead of in a side panel. Band, series and segments each take an optional
    `"color"` that overrides the style palette for this figure only.
    """
    from mpl_toolkits.axes_grid1 import make_axes_locatable
    from matplotlib.patches import Patch
    cats, ser = spec["categories"], series_of(spec)
    xs = list(range(len(cats)))
    lw = ctx.ch.get("line_width", 2.0)
    handles, labels, ends = [], [], []
    band = spec.get("band")
    if band:
        bcol = band.get("color") or ctx.color_for(band.get("name", "band"), 0)
        balpha = band.get("alpha", ctx.ch.get("area_fill_opacity", 0.22))
        ax.fill_between(xs, band["low"], band["high"], color=bcol, alpha=balpha, linewidth=0, zorder=2)
        handles.append(Patch(color=bcol, alpha=min(1.0, balpha + 0.13))); labels.append(band.get("name", "Range"))
        ends.append([band["high"][-1], ctx.c["body"], 0.72])
    for i, s_ in enumerate(ser):
        name = s_.get("name", f"s{i}")
        col = s_.get("color") or ctx.color_for(name, i + 1)
        w = lw * (1.5 if s_.get("emphasis") else 1.0)
        ln, = ax.plot(xs, s_["values"], color=col, linewidth=w, zorder=4 if s_.get("emphasis") else 3,
                      linestyle=s_.get("linestyle", ctx.ch.get("line_style", "solid")),
                      alpha=ctx.ch.get("line_opacity", 1.0), solid_capstyle="round")
        handles.append(ln); labels.append(name)
        if s_.get("end_label", True):
            ends.append([s_["values"][-1], ctx.c["ink"] if s_.get("emphasis") else col, 0.68])
    step = spec.get("tick_every") or max(1, -(-len(cats) // 10))
    keep = [k for k in range(len(cats)) if k % step == 0]
    if step > 1 and (len(cats) - 1) - keep[-1] >= step:
        keep.append(len(cats) - 1)
    ax.set_xticks([xs[k] for k in keep], [str(cats[k]) for k in keep])
    frame(ax, ctx, spec, axis="y")
    top = max(([max(band["high"])] if band else []) + [max(v for v in s_["values"]) for s_ in ser])
    ax.set_ylim(0, top * 1.08)
    bar = spec.get("bar")
    inline = bool(bar) and spec.get("bar_inline", False)
    bx_pos = xs[-1] + len(xs) * 0.13
    ax.set_xlim(-0.5, (bx_pos + len(xs) * 0.05) if inline else (xs[-1] + 0.5 + len(xs) * 0.09))
    # End labels sit at their values, pushed apart just enough not to overprint.
    gap = top * 1.08 * 0.04
    ends.sort(key=lambda e: e[0])
    placed = []
    for v, col, size in ends:
        y = max(v, placed[-1] + gap) if placed else v
        placed.append(y)
        ax.text(xs[-1] + len(xs) * 0.012, y, fmt(v, spec), va="center", ha="left",
                fontsize=ctx.base * size, fontname=ctx.body, color=col)
    if bar:
        if inline:
            bx, x0, bw = ax, bx_pos, len(xs) * 0.055
            ax.axvline((xs[-1] + bx_pos) / 2 + len(xs) * 0.02, color=ctx.c["rule"], linewidth=0.8,
                       linestyle=(0, (2, 3)), zorder=1)
        else:
            div = make_axes_locatable(ax)
            bx = div.append_axes("right", size=spec.get("bar_panel", "17%"), pad=0.45, sharey=ax)
            bx.set_facecolor(ctx.c["surface"])
            x0, bw = 0, 0.6
        base = 0.0
        for j, seg in enumerate(bar["segments"]):
            col = seg.get("color") or ctx.color_for(seg["name"], 10 + j)
            bx.bar([x0], [seg["value"]], bottom=base, width=bw, zorder=3,
                   **bar_fill_kwargs(ctx, col))
            handles.append(Patch(color=col)); labels.append(seg["name"])
            base += seg["value"]
        bx.annotate(fmt(base, spec), (x0, base), xytext=(0, 4), textcoords="offset points",
                    ha="center", va="bottom", fontsize=ctx.base * 0.78, fontname=ctx.head,
                    color=ctx.c["ink"], fontweight="bold")
        if inline:
            ticks = list(ax.get_xticks()) + [x0]
            names = [t.get_text() for t in ax.get_xticklabels()] + [wrap(bar.get("label", ""), 14)]
            ax.set_xticks(ticks, names)
            for lbl in ax.get_xticklabels():
                lbl.set_fontname(ctx.body)
        else:
            bx.set_xlim(-0.6, 0.6)
            bx.set_xticks([0], [wrap(bar.get("label", ""), 12)])
            frame(bx, ctx, {}, axis="y")
            bx.tick_params(axis="y", labelleft=False)
            bx.set_ylim(0, top * 1.08)
    legend(ax, ctx, spec, handles=handles, labels=labels, n=spec.get("legend_cols", 3))


def _pack_circles(radii, gap, targets=None):
    """Greedy circle packing. Each circle goes to the free spot nearest its target
    (default the origin), placed in order of distance of target from the origin,
    so circles with central targets claim the middle first. Returns centres in
    input order."""
    import math
    targets = targets or [(0.0, 0.0)] * len(radii)
    order = sorted(range(len(radii)), key=lambda i: (math.hypot(*targets[i]), -radii[i]))
    placed = {}
    step = 0.04 * max(radii)
    for i in order:
        tx, ty = targets[i]
        best = (tx, ty)
        for k in range(0, 20000):                      # spiral outwards from the target
            a, d = k * 0.3, step * math.sqrt(k) * 1.2
            x, y = tx + d * math.cos(a), ty + d * math.sin(a)
            if all(math.hypot(x - px, y - py) >= radii[i] + radii[j] + gap
                   for j, (px, py) in placed.items()):
                best = (x, y)
                break
        placed[i] = best
    return [placed[i] for i in range(len(radii))]


def _pack_tangent(radii, gap, targets, order=None):
    """Tight packing: each circle goes to the free spot nearest its target among
    spots tangent to one or two circles already placed. Returns centres in input order."""
    import math
    order = order or sorted(range(len(radii)), key=lambda i: (math.hypot(*targets[i]), -radii[i]))
    placed = {}
    def free(x, y, r):
        return all(math.hypot(x - px, y - py) >= r + radii[j] + gap - 1e-9 for j, (px, py) in placed.items())
    for i in order:
        r, (tx, ty) = radii[i], targets[i]
        if not placed:
            placed[i] = (tx, ty); continue
        cands = [(tx, ty)]
        items = list(placed.items())
        for j, (px, py) in items:                       # tangent to one circle
            d = r + radii[j] + gap
            for k in range(36):
                a = 2 * math.pi * k / 36
                cands.append((px + d * math.cos(a), py + d * math.sin(a)))
        for a_ in range(len(items)):                     # tangent to two circles
            j, (x1, y1) = items[a_]
            for b_ in range(a_ + 1, len(items)):
                k, (x2, y2) = items[b_]
                r1_, r2_ = r + radii[j] + gap, r + radii[k] + gap
                d = math.hypot(x2 - x1, y2 - y1)
                if d == 0 or d > r1_ + r2_ or d < abs(r1_ - r2_):
                    continue
                a = (r1_ ** 2 - r2_ ** 2 + d ** 2) / (2 * d)
                h = math.sqrt(max(0.0, r1_ ** 2 - a ** 2))
                mx, my = x1 + a * (x2 - x1) / d, y1 + a * (y2 - y1) / d
                cands.append((mx + h * (y2 - y1) / d, my - h * (x2 - x1) / d))
                cands.append((mx - h * (y2 - y1) / d, my + h * (x2 - x1) / d))
        best = min((c for c in cands if free(c[0], c[1], r)),
                   key=lambda c: math.hypot(c[0] - tx, c[1] - ty))
        placed[i] = best
    return [placed[i] for i in range(len(radii))]


def _draw_coverage_bubbles(ax, spec, ctx):
    """A universe of required data: a ring of data classes, coloured by group,
    numbered, with each group's legend set beside its own arc.

    Each bubble is one class of data, all the same size, so no class is claimed to
    be bigger than another. The disc inside, sitting on the bubble's inner edge,
    has `measured` times the bubble's area: the share measured, to scale.
    `measured: null` is a share no source quantifies (dotted ring; `share_label`
    gives a count instead, shown in the legend); `"status": "absent"` is a class
    with no dataset found (hatched). Groups take contiguous arcs, so adjacent hues
    are the only pairs a reader compares, and every group is named in its legend
    block, so colour never carries identity alone. Legend blocks sit left and
    right of the ring, each level with its arc; the figure is drawn at print size
    and its height follows whichever is taller, ring or legend.
    """
    import math
    import textwrap as _tw
    from matplotlib.patches import Circle, Wedge, Rectangle
    bubbles = spec["bubbles"]
    groups = spec.get("groups") or [{"name": g} for g in sorted({b.get("group", "") for b in bubbles})]
    names = [g["name"] for g in groups]
    # validated as a ring (adjacent pairs incl. the wrap): similar hues never touch
    pal = ["#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7", "#e34948", "#eda100", "#008300", "#e87ba4"]
    gcol = {g["name"]: g.get("color") or pal[k % len(pal)] for k, g in enumerate(groups)}
    ink, ink2, muted = ctx.c["ink"], ctx.c.get("body", "#52514e"), ctx.c["muted"]
    face, ring_neutral = "#FFFFFF", spec.get("ring_color", "#b8bdc6")
    uni_c, band_c = spec.get("universe_fill", "#F4F6F9"), spec.get("band_fill", "#E9EDF2")
    fl = spec.get("legend_pt", 7.4)                 # legend type
    fn = spec.get("number_pt", 9.5)                 # numbers inside bubbles

    def rank(i):
        b = bubbles[i]
        return (b.get("status") == "absent", b.get("measured") is None, -(b.get("measured") or 0))
    order = []
    for g in names:
        order += sorted([i for i, b in enumerate(bubbles) if b.get("group") == g], key=rank)
    num = {i: k + 1 for k, i in enumerate(order)}

    r, gap, ggap = 1.0, 0.14, spec.get("group_gap", 0.7)
    Rr = (len(order) * (2 * r + gap) + len(names) * ggap) / (2 * math.pi)
    ang, theta, arcs = math.pi / 2, {}, []
    for g in names:
        members = [i for i in order if bubbles[i].get("group") == g]
        ang -= ggap / 2 / Rr
        a0 = ang
        for i in members:
            ang -= (r + gap / 2) / Rr
            theta[i] = ang
            ang -= (r + gap / 2) / Rr
        arcs.append((g, a0, ang))
        ang -= ggap / 2 / Rr
    R_in = Rr + r + 0.45
    R = R_in * spec.get("universe_pad", 1.07)

    # ---- frame at print size: legend columns either side of the ring
    w_in = ax.figure.get_size_inches()[0]
    col_in, gap_in = spec.get("legend_col_in", 1.62), 0.10
    D_in = w_in - 2 * (col_in + gap_in)
    upi = 2 * R / D_in                              # data units per inch
    lu = fl * 1.34 / 72 * upi                       # one legend line, data units
    fn = min(fn, 0.5 * (2 * r / upi * 72))          # numbers sized to the bubble on the page
    colw = col_in * upi
    xL0 = -R - (gap_in + col_in) * upi
    xR0 = R + gap_in * upi
    x0, x1 = xL0, R + (gap_in + col_in) * upi

    rend = ax.figure.canvas.get_renderer()
    def w_units(t, fs, bold=False):
        tt = ax.text(0, 0, t, fontsize=fs, fontname=ctx.body, fontweight="bold" if bold else "normal")
        bb = tt.get_window_extent(renderer=rend); tt.remove()
        return bb.width / ax.figure.dpi * upi

    def share_of(b):
        m, absent = b.get("measured"), b.get("status") == "absent"
        return b.get("share_label") or ("none found" if absent else "unsized" if m is None
                                        else (f"{m * 100:.0f}%" if m >= 0.01 else "<1%"))

    # build each group's block as lines of (kind, payload)
    blocks = {}
    num_w = w_units("00", fl, True) + 0.15 * upi / 2.5
    for g in names:
        lines = [("head", g)]
        for i in [i for i in order if bubbles[i].get("group") == g]:
            b = bubbles[i]
            sh = share_of(b)
            room = colw - num_w - w_units(sh, fl) - 0.25 * lu
            nm = b["name"]
            if w_units(nm, fl) > room:
                parts = _tw.wrap(nm, max(8, int(len(nm) * room / max(w_units(nm, fl), 1e-6))), break_long_words=False)
                lines.append(("item", (i, parts[0], sh)))
                for extra in parts[1:]:
                    lines.append(("cont", extra))
            else:
                lines.append(("item", (i, nm, sh)))
        blocks[g] = lines

    # side and target height for each block: level with its arc
    sides = {"L": [], "R": []}
    for g, a0, a1 in arcs:
        mid = (a0 + a1) / 2
        sides["R" if math.cos(mid) >= 0 else "L"].append((g, Rr * math.sin(mid)))
    placed = {}
    for sd, items in sides.items():
        items.sort(key=lambda t: -t[1])
        ys, cursor = [], None
        for g, ty in items:
            h = len(blocks[g]) * lu
            top = ty + h / 2
            if cursor is not None:
                top = min(top, cursor - 0.6 * lu)
            ys.append([g, top, h]); cursor = top - h
        # if pushed below the ring's bottom edge, lift the whole column
        low = ys[-1][1] - ys[-1][2] if ys else 0
        if low < -R:
            for row in ys:
                row[1] += (-R - low)
        for g, top, h in ys:
            placed[g] = (sd, top, h)
    top_y = max(R + 2.8 * lu, max(t for _, t, _ in placed.values()) + 0.4 * lu) + 0.6 * lu
    bot_y = min(-R - 1.0 * lu, min(t - h for _, t, h in placed.values()) - 0.4 * lu) - 4.8 * lu
    ax.figure.set_size_inches(w_in, (top_y - bot_y) / upi)
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(x0, x1); ax.set_ylim(bot_y, top_y); ax.set_aspect("equal")

    # ---- universe, band, inner field
    ax.add_patch(Circle((0, 0), R, facecolor=band_c, edgecolor=ring_neutral, linewidth=1.0,
                        linestyle=(0, (6, 4)), zorder=0.5))
    ax.add_patch(Circle((0, 0), R_in, facecolor=uni_c, edgecolor="#FFFFFF", linewidth=1.6, zorder=0.6))
    for g, a0, a1 in arcs:
        ax.add_patch(Wedge((0, 0), Rr + r + 0.22, math.degrees(a1), math.degrees(a0), width=2 * r + 0.44,
                           facecolor=gcol[g], alpha=0.14, edgecolor="none", zorder=1))

    # ---- bubbles
    for i in order:
        b, t = bubbles[i], theta[i]
        c = gcol[b.get("group")]
        x, y = Rr * math.cos(t), Rr * math.sin(t)
        m, absent = b.get("measured"), b.get("status") == "absent"
        unq = m is None and not absent
        ax.add_patch(Circle((x, y), r, facecolor=face, edgecolor=c, linewidth=1.2,
                            linestyle=(0, (1.4, 1.6)) if unq else ((0, (3, 2)) if absent else "-"),
                            hatch="//////" if absent else None, zorder=2))
        if absent:
            ax.add_patch(Circle((x, y), r * 0.58, facecolor=face, edgecolor="none", zorder=2.5))
        dr = math.sqrt(min(1.0, m)) if m else 0.0
        if m:
            rr = r * max(dr, 0.09)
            cx, cy = x - (r - rr) * math.cos(t), y - (r - rr) * math.sin(t)
            ax.add_patch(Circle((cx, cy), rr - 0.03, facecolor=c, edgecolor=face, linewidth=0.6, zorder=3))
        if b.get("hard"):                          # hard to measure with current methods
            hx, hy = (Rr + r + 0.34) * math.cos(t), (Rr + r + 0.34) * math.sin(t)
            ax.plot([hx], [hy], marker="D", markersize=4.2, color=ink, zorder=6, markeredgewidth=0)
        on_disc = dr >= 0.62
        nx, ny = (x, y) if (on_disc or not m) else (x + 0.40 * math.cos(t), y + 0.40 * math.sin(t))
        ax.text(nx, ny, str(num[i]), ha="center", va="center", fontsize=fn, fontname=ctx.head,
                fontweight="bold", color="#FFFFFF" if on_disc else ink, zorder=5)

    # ---- centre statistic: a count of classes, never a sum of unlike shares
    shares = [b.get("measured") for b in bubbles if b.get("measured") is not None and b.get("status") != "absent"]
    low = sum(1 for v in shares if v < 1 / 3)
    ax.text(0, 1.0, f"{len(shares)} of {len(bubbles)}", ha="center", va="center", fontsize=spec.get("stat_pt", 30),
            fontname=ctx.head, fontweight="bold", color=ink, zorder=6)
    ax.text(0, -1.0, "\n".join(_tw.wrap(spec.get("center_note") or
             f"classes have a measured share; {low} of those {len(shares)} are under a third", 26)),
            ha="center", va="top", fontsize=spec.get("center_pt", 9.5), fontname=ctx.body, color=ink2,
            zorder=6, linespacing=1.15)

    # ---- universe and band labels, outside the circle
    if spec.get("universe_label"):
        ax.text(0, R + 0.7 * lu, "\n".join(_tw.wrap(spec["universe_label"].upper(), 46)), ha="center", va="bottom", linespacing=1.1,
                fontsize=fl * 1.05, fontname=ctx.head, fontweight="bold", color=ink2, zorder=6)
    if spec.get("band_label"):
        ax.text(0, -R - 0.6 * lu, "\n".join(_tw.wrap(spec["band_label"], 90)), ha="center", va="top",
                fontsize=fl, fontname=ctx.body, style="italic", color=ink2, zorder=6, linespacing=1.1)

    # ---- legend blocks beside their arcs
    sw = lu * 0.62
    for g, (sd, top, h) in placed.items():
        lx = xL0 if sd == "L" else xR0
        share_x = lx + colw
        ly = top - lu / 2
        for kind, pay in blocks[g]:
            if kind == "head":
                ax.add_patch(Rectangle((lx, ly - sw * 0.5), sw * 1.6, sw, facecolor=gcol[g], edgecolor="none", zorder=6))
                ax.text(lx + sw * 2.0, ly, pay.upper(), ha="left", va="center", fontsize=fl * 0.95,
                        fontname=ctx.head, fontweight="bold", color=ink, zorder=6)
            elif kind == "item":
                i, nm, sh = pay
                b = bubbles[i]
                ax.text(lx + num_w, ly, str(num[i]), ha="right", va="center", fontsize=fl,
                        fontname=ctx.head, fontweight="bold", color=ink2, zorder=6)
                ax.text(lx + num_w + 0.25 * lu, ly, nm, ha="left", va="center", fontsize=fl,
                        fontname=ctx.body, color=ink, zorder=6)
                ax.text(share_x, ly, sh, ha="right", va="center", fontsize=fl, fontname=ctx.body,
                        color=ink if b.get("measured") else muted,
                        style="normal" if b.get("measured") else "italic", zorder=6)
            else:
                ax.text(lx + num_w + 0.25 * lu, ly, pay, ha="left", va="center", fontsize=fl,
                        fontname=ctx.body, color=ink, zorder=6)
            ly -= lu

    # ---- encoding key, one row across the bottom
    kr = lu * 0.4
    items = [("measured", "Disc: share measured, to scale"), ("unq", "Dotted: measured, share not quantified"),
             ("absent", "Hatched: no dataset found")]
    if any(b.get("hard") for b in bubbles):
        items.append(("hard", spec.get("hard_label", "Diamond: hard to measure with current methods")))
    widths = [2 * kr + 0.25 * lu + w_units(t, fl) for _, t in items]
    rows_ = [list(range(len(items)))]
    if sum(widths) + 1.2 * lu * (len(items) - 1) > 0.94 * (x1 - x0):   # wrap the key to two rows
        h = (len(items) + 1) // 2
        rows_ = [list(range(h)), list(range(h, len(items)))]
    for ri, row in enumerate(rows_):
        kx = -(sum(widths[j] for j in row) + 1.2 * lu * (len(row) - 1)) / 2
        ky = bot_y + (1.0 + 1.25 * (len(rows_) - 1 - ri)) * lu
        _draw_key_row(ax, ctx, [items[j] for j in row], [widths[j] for j in row], kx, ky, kr, lu, fl, face, ink, ink2)
    ax.axis("off")


def _draw_key_row(ax, ctx, items, widths, kx, ky, kr, lu, fl, face, ink, ink2):
    from matplotlib.patches import Circle
    for (kind, text), wd in zip(items, widths):
        if kind == "hard":
            ax.plot([kx + kr], [ky], marker="D", markersize=4.2, color=ink, zorder=7, markeredgewidth=0)
        elif kind == "absent":
            ax.add_patch(Circle((kx + kr, ky), kr, facecolor=face, edgecolor=ink2, hatch="//////", lw=0.7, zorder=6))
        else:
            ax.add_patch(Circle((kx + kr, ky), kr, facecolor=face, edgecolor=ink2, lw=0.7, zorder=6,
                                linestyle=(0, (1.2, 1.4)) if kind == "unq" else "-"))
            if kind == "measured":
                ax.add_patch(Circle((kx + kr, ky - kr * 0.4), kr * 0.6, facecolor=ink2, edgecolor=face, lw=0.5, zorder=7))
        ax.text(kx + 2 * kr + 0.25 * lu, ky, text, ha="left", va="center", fontsize=fl, fontname=ctx.body,
                color=ink2, zorder=6)
        kx += wd + 1.2 * lu


DRAW = {t: globals()[f"_draw_{t}"] for t in TYPES}


# ---------------------------------------------------------------- rendering

DEFAULT_H = {"coverage_bubbles": 7.0, "stat": 1.5, "hbar": None, "dot": None, "dumbbell": None,
             "heatmap": None, "donut": 3.6, "slope": 4.0}


def render(spec, ctx, outdir, formats=("png", "svg")):
    kind = spec["type"]
    if kind not in DRAW:
        raise ValueError(f"unknown figure type {kind!r}; known: {', '.join(TYPES)}")
    spec = apply_sort(dict(spec)) if kind in ("bar", "hbar") else spec

    w, h = spec.get("size", [None, None]) if isinstance(spec.get("size"), list) else (None, None)
    w = w or (9.0 if spec.get("wide") else 6.5)
    if h is None:
        h = DEFAULT_H.get(kind)
    if h is None and kind in ("line", "area", "band_line_bar"):       # time series: landscape, never row-scaled
        h = round(w * 0.55, 2)
    if h is None:                                    # category charts grow with rows
        rows = len(spec.get("categories") or spec.get("rows") or [1])
        h = max(2.4, min(9.0, 1.0 + rows * (0.42 if kind != "heatmap" else 0.36)))
    h = h or 3.9

    plt.rcParams["font.family"] = ctx.body
    base0 = ctx.base                     # `font_scale` enlarges every label on this figure only
    ctx.base = base0 * spec.get("font_scale", 1.0)
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    if kind in ("stat", "donut"):
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.patch.set_facecolor(ctx.c["surface"])
    ax.set_facecolor(ctx.c["surface"])

    DRAW[kind](ax, spec, ctx)

    if spec.get("baseline") is not None and kind not in ("stat", "donut", "heatmap", "coverage_bubbles"):
        ax.axhline(spec["baseline"], color=ctx.c["muted"], linewidth=0.9,
                   linestyle=(0, (4, 3)), zorder=2)

    # The chart's own title is its message; the caption below carries the source.
    # Stack title and subtitle above whatever is already highest — the legend, if
    # there is one, otherwise the axes — measuring rather than guessing, because a
    # guessed offset collides the moment a title wraps to two lines.
    def stack(text, size, color, weight, cursor):
        t = fig.text(0.0, cursor + 0.014, text, ha="left", va="bottom",
                     fontsize=size, fontname=ctx.head, color=color, fontweight=weight)
        fig.canvas.draw()
        return t.get_window_extent().transformed(fig.transFigure.inverted()).y1

    fig.canvas.draw()
    cursor = ax.get_position().y1 + 0.02          # headroom so the top tick never touches the subtitle
    leg = ax.get_legend()
    if leg is not None:
        cursor = max(cursor, leg.get_window_extent()
                     .transformed(fig.transFigure.inverted()).y1)
    if spec.get("subtitle"):
        cursor = stack(wrap(spec["subtitle"], int(w * 17)), ctx.base * 0.82,
                       ctx.c["muted"], "normal", cursor)
    if spec.get("chart_title", False) and spec.get("title"):
        stack(wrap(spec["title"], int(w * 15)), ctx.base * 1.05,
              ctx.c["ink"], "bold", cursor)

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for ext in formats:
        p = outdir / f"{spec['id']}.{ext}"
        fig.savefig(p, bbox_inches="tight", pad_inches=0.06,
                    facecolor=ctx.c["surface"], transparent=False)
        paths[ext] = p
    plt.close(fig)
    ctx.base = base0
    return paths


# ---------------------------------------------------------------- document pass

def parse(md):
    """Return (specs in document order, table-caption matches in document order)."""
    specs = []
    for m in BLOCK.finditer(md):
        raw = m.group(1)
        try:
            spec = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"figure block at char {m.start()} is not valid JSON: {e}") from e
        spec["_span"] = (m.start(), m.end())
        specs.append(spec)
    return specs


def validate(spec):
    problems = []
    fid = spec.get("id", "?")
    for k in ("id", "type", "title", "source"):
        if not spec.get(k):
            problems.append(f"ERROR {fid}: missing required field '{k}'")
    if spec.get("type") not in TYPES:
        problems.append(f"ERROR {fid}: unknown type {spec.get('type')!r} "
                        f"(known: {', '.join(TYPES)})")
    if not CITE.search(str(spec.get("source", ""))):
        problems.append(f"ERROR {fid}: 'source' carries no [E#] evidence ID — "
                        f"a chart is a claim and needs one")
    t = spec.get("type")
    if t in NEEDS_SERIES and t not in ("scatter",):
        if not spec.get("categories"):
            problems.append(f"ERROR {fid}: '{t}' needs 'categories'")
        for s in series_of(spec):
            if len(s.get("values", [])) != len(spec.get("categories", [])):
                problems.append(f"ERROR {fid}: series {s.get('name')!r} has "
                                f"{len(s.get('values', []))} values for "
                                f"{len(spec.get('categories', []))} categories")
    if t == "band_line_bar":
        b = spec.get("band") or {}
        for k in ("low", "high"):
            if b and len(b.get(k, [])) != len(spec.get("categories", [])):
                problems.append(f"ERROR {fid}: band '{k}' length does not match categories")
        for seg in (spec.get("bar") or {}).get("segments", []):
            if not isinstance(seg.get("value"), (int, float)):
                problems.append(f"ERROR {fid}: bar segment {seg.get('name')!r} has no numeric value")
    if t == "coverage_bubbles":
        for b in spec.get("bubbles", []):
            m = b.get("measured", "missing")
            if m == "missing" or (m is not None and not 0 <= m <= 1):
                problems.append(f"ERROR {fid}: bubble {b.get('name')!r} needs 'measured' between 0 and 1, or null")
            if m is None and not spec.get("data_gaps"):
                problems.append(f"ERROR {fid}: bubble {b.get('name')!r} has no measured share but the spec has no 'data_gaps' note")
    if t == "waterfall" and not spec.get("steps"):
        problems.append(f"ERROR {fid}: waterfall needs 'steps'")
    if t == "heatmap" and not (spec.get("rows") and spec.get("columns") and spec.get("values")):
        problems.append(f"ERROR {fid}: heatmap needs 'rows', 'columns', 'values'")
    if t in ("donut",) and not (spec.get("categories") and spec.get("values")):
        problems.append(f"ERROR {fid}: donut needs 'categories' and 'values'")
    if t == "stat" and not spec.get("stats"):
        problems.append(f"ERROR {fid}: stat needs 'stats'")
    gaps = len(missing_idx(spec)) + sum(
        1 for st in spec.get("stats", []) if st.get("value") is None)
    if gaps and not spec.get("data_gaps"):
        problems.append(f"ERROR {fid}: {gaps} value(s) are null, i.e. not obtained, but the "
                        f"spec has no 'data_gaps' note saying what is missing and where a "
                        f"reader would get it")
    if t == "donut" and len(spec.get("categories", [])) > 5:
        problems.append(f"WARN  {fid}: donut with {len(spec['categories'])} slices — "
                        f"a ranked 'dot' or 'hbar' reads better above ~5")
    if t in ("bar", "hbar") and len(series_of(spec)) > 4:
        problems.append(f"WARN  {fid}: {len(series_of(spec))} grouped series is hard to read; "
                        f"consider 'line', 'dot', or splitting the exhibit")
    return problems


def build(md_path, style_name, outdir, out_md=None, formats=("png", "svg"),
          img_ext="png", rel_from=None):
    md = Path(md_path).read_text()

    # Repoint author-placed images before anything else runs, so that only
    # hand-written paths are touched: every image added later in this function
    # is generated here and already carries a correct path. A supplied
    # illustration is as much an exhibit as a rendered chart, and it has to
    # survive into the export rather than arriving as a broken link.
    src_dir = Path(md_path).resolve().parent

    def _repoint(m):
        alt, target = m.group(1), m.group(2)
        if re.match(r"^(?:[a-z]+:|/|#)", target, re.I):
            return m.group(0)                      # URL, absolute, or anchor
        resolved = (src_dir / target).resolve()
        if not resolved.exists():
            print(f"WARN image not found, left as written: {target}")
            return m.group(0)
        out = resolved
        if rel_from:
            try:
                out = resolved.relative_to(Path(rel_from).resolve())
            except ValueError:
                out = resolved
        return f"![{alt}]({out})"

    md = MD_IMAGE.sub(_repoint, md)

    st = stylelib.load(style_name)
    ctx = Ctx(st) if st else Ctx(stylelib.load(stylelib.available()[0]))

    specs = parse(md)
    problems = [p for s in specs for p in validate(s)]
    if any(p.startswith("ERROR") for p in problems):
        for p in problems:
            print(p)
        sys.exit(1)

    # Figures and tables have separate sequences in document order.
    order = sorted([(s["_span"][0], "F", s) for s in specs] +
                   [(m.start(), "T", m) for m in TABLE_CAP.finditer(md)],
                   key=lambda x: x[0])
    numbers = {}
    counts = {"F": 0, "T": 0}
    for _, kind, obj in order:
        counts[kind] += 1
        numbers[obj["id"] if kind == "F" else obj.group(2)] = counts[kind]

    rendered = {}
    for spec in specs:
        override = st.get("item_overrides", {}).get("figures", {}).get(spec["id"]) if st else None
        fig_ctx = ctx
        if override:
            fig_style = copy.deepcopy(ctx.st)
            fig_style["series"] = override["series"]
            fig_style["color"]["surface"] = override["background"]
            fig_style["fonts"]["heading"] = [override["heading_font"], *ctx.st["fonts"]["heading"][1:]]
            fig_style["fonts"]["body"] = [override["body_font"], *ctx.st["fonts"]["body"][1:]]
            fig_style["chart"].update({k: v for k, v in override.items() if k not in ("series", "background", "heading_font", "body_font")})
            fig_ctx = Ctx(fig_style)
        paths = render(spec, fig_ctx, outdir, formats)
        rendered[spec["id"]] = paths

    # rewrite, back to front so spans stay valid
    out = md
    for spec in sorted(specs, key=lambda s: -s["_span"][0]):
        n = numbers[spec["id"]]
        img = rendered[spec["id"]][img_ext]
        rel = Path(img)
        if rel_from:
            try:
                rel = Path(img).resolve().relative_to(Path(rel_from).resolve())
            except ValueError:
                rel = Path(img).resolve()
        cap = f"**Figure {n}.** {spec['title']}"
        if spec.get("subtitle") and spec.get("chart_title"):
            cap += f" {spec['subtitle']}"
        cap += f" *Source: {spec['source']}.*"
        if spec.get("note"):
            cap += f" *{spec['note']}*"
        if spec.get("data_gaps"):
            cap += (f" **Incomplete — hatched slots are data this research could not obtain:** "
                    f"*{spec['data_gaps']}*")
        a, b = spec["_span"]
        out = out[:a] + f"![{cap}]({rel})" + out[b:]

    out = TABLE_CAP.sub(lambda m: f"**Table {numbers[m.group(2)]}.** {m.group(1)}", out)
    # A reference already preceded by its type takes the number alone.
    def _xref(m):
        if m.group(1) not in numbers:
            return m.group(0)
        before = out[max(0, m.start() - 40):m.start()]
        label = "Figure" if m.group(1).startswith("F") else "Table"
        bare = re.search(rf"{label}s?\s+$", before)
        return f"{numbers[m.group(1)]}" if bare else f"{label} {numbers[m.group(1)]}"
    out = XREF.sub(_xref, out)

    for p in problems:
        print(p)
    if out_md:
        Path(out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(out_md).write_text(out)
        print(f"{counts['F']} figures and {counts['T']} tables numbered · {out_md}")
    else:
        sys.stdout.write(out)
    return out


# ---------------------------------------------------------------- demo

DEMO = [
    {"id": "F1", "type": "stat", "title": "Where the market stands", "source": "[E1][E2]",
     "stats": [{"value": "38%", "label": "share held by the top three", "delta": "+6pp since 2023"},
               {"value": "1.9M", "label": "units shipped, TTM to Q3 2025"},
               {"value": "4", "label": "jurisdictions with binding rules"}]},
    {"id": "F2", "type": "bar", "title": "Adoption stalled in the two regulated markets",
     "subtitle": "Installed base, thousands of units, year end", "source": "[E7][E12]",
     "unit": "k", "categories": ["Germany", "France", "Spain", "Italy", "Poland"],
     "series": [{"name": "2024", "values": [120, 98, 76, 64, 31]},
                {"name": "2025", "values": [124, 101, 112, 96, 58]}]},
    {"id": "F3", "type": "line", "title": "Cost fell fastest where volume grew",
     "source": "[E19]", "unit": "/kWh", "prefix": "$",
     "categories": ["2020", "2021", "2022", "2023", "2024", "2025"],
     "series": [{"name": "Cells", "values": [137, 118, 129, 98, 82, 71]},
                {"name": "Packs", "values": [180, 159, 171, 139, 121, 108]}]},
    {"id": "F4", "type": "dot", "title": "Compliance cost per unit, by jurisdiction",
     "source": "[E22]", "prefix": "€", "sort": "desc", "highlight": ["Germany"],
     "categories": ["Germany", "France", "Netherlands", "Spain", "Poland"],
     "series": [{"name": "2025", "values": [42.5, 31.0, 28.4, 19.2, 11.6]}]},
    {"id": "F5", "type": "waterfall", "title": "What moved the unit cost between 2023 and 2025",
     "source": "[E19][E31]", "prefix": "$",
     "steps": [{"label": "2023 cost", "value": 98, "type": "start"},
               {"label": "Cell chemistry", "value": -14},
               {"label": "Scale", "value": -19},
               {"label": "Compliance", "value": 8},
               {"label": "Logistics", "value": -2},
               {"label": "2025 cost", "value": 71, "type": "total"}]},
    {"id": "F6", "type": "dumbbell", "title": "Every market narrowed the gap except Poland",
     "source": "[E7][E12]", "unit": "%",
     "categories": ["Germany", "France", "Spain", "Italy", "Poland"],
     "series": [{"name": "2023", "values": [31, 28, 19, 16, 22]},
                {"name": "2025", "values": [44, 39, 37, 31, 24]}]},
    {"id": "F7", "type": "heatmap", "title": "Rule coverage by jurisdiction and product class",
     "source": "[E4][E5]", "unit": "", "decimals": 0,
     "rows": ["Germany", "France", "Spain", "Poland"],
     "columns": ["Portable", "Industrial", "EV", "Storage"],
     "values": [[3, 3, 2, 1], [3, 2, 2, 1], [2, 2, 1, 0], [1, 1, 1, 0]]},
    {"id": "F8", "type": "stacked_bar", "title": "Cost stack shifted from cells to compliance",
     "source": "[E19][E22]", "prefix": "$",
     "categories": ["2021", "2023", "2025"],
     "series": [{"name": "Cells", "values": [118, 98, 71]},
                {"name": "Assembly", "values": [28, 24, 21]},
                {"name": "Compliance", "values": [6, 11, 19]}]},
]


def demo(style_name, outdir):
    st = stylelib.load(style_name)
    ctx = Ctx(st)
    outdir = Path(outdir)
    for spec in DEMO:
        render(spec, ctx, outdir, formats=("png",))
    md = [f"% {st['label']} — style preview", "% Research workspace", "% Sample document", ""]
    md.append(f"**Answer:** This page exists to show what the *{st['label']}* style looks like "
              f"before you commit a real report to it. {st.get('tagline','')} [E1]\n")
    md.append("## Every heading in this workspace is a finding, not a topic label\n")
    md.append("Body copy sits at the style's base size, and a table looks like this. [E2]\n")
    md.append("| Jurisdiction | Rule in force | Units, 2025 | Compliance cost |\n"
              "|---|---|---:|---:|\n"
              "| Germany | Yes | 124,000 | €42.50 |\n"
              "| France | Yes | 101,000 | €31.00 |\n"
              "| Spain | Partial | 112,000 | €19.20 |\n"
              "| Poland | No | 58,000 | €11.60 |\n")
    md.append("**Exhibit:** Rule status and unit economics by jurisdiction [E7] {#T1}\n")
    for spec in DEMO:
        cap = f"**Exhibit.** {spec['title']} *Source: {spec['source']}.*"
        md.append(f"![{cap}]({outdir.resolve()}/{spec['id']}.png)\n")
    md.append("> Confidence: Medium. Every number on this page is invented for layout "
              "purposes and cites nothing real.\n")
    p = outdir / "preview.md"
    p.write_text("\n".join(md))
    return p


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="validate every figure block without rendering")
    c.add_argument("md")

    b = sub.add_parser("build", help="render figures and emit styled markdown")
    b.add_argument("md")
    b.add_argument("--style", default="none")
    b.add_argument("--outdir", required=True)
    b.add_argument("-o", "--out")
    b.add_argument("--img", default="png", choices=("png", "svg"))
    b.add_argument("--rel-from", help="write image paths relative to this directory")

    g = sub.add_parser("gaps", help="list every unobtained data point in the report")
    g.add_argument("md")

    sub.add_parser("types", help="list the chart types and what each is for")

    d = sub.add_parser("demo", help="render a sample document in a style")
    d.add_argument("--style", required=True)
    d.add_argument("-o", "--out", required=True)

    a = ap.parse_args()

    if a.cmd == "types":
        for t in TYPES:
            print(f"  {t:<14} {(DRAW[t].__doc__ or '').strip().splitlines()[0] if DRAW[t].__doc__ else ''}")
        return
    if a.cmd == "gaps":
        md = Path(a.md).read_text()
        n = 0
        for spec in parse(md):
            idx = missing_idx(spec)
            cats = spec.get("categories") or []
            named = [cats[i] for i in idx if i < len(cats)] or [str(i) for i in idx]
            named += [st.get("label", "?") for st in spec.get("stats", [])
                      if st.get("value") is None]
            if named:
                n += len(named)
                print(f"{spec['id']} ({spec['type']}): {', '.join(named)}")
                print(f"    to obtain: {spec.get('data_gaps', 'UNDOCUMENTED')}")
        for m in re.finditer(r"\[NEEDS DATA[^\]]*\]", md):
            n += 1
            print(f"prose/table: {m.group(0)}")
        print(f"\n{n} unobtained data point(s)")
        return
    if a.cmd == "check":
        specs = parse(Path(a.md).read_text())
        problems = [p for s in specs for p in validate(s)]
        for p in problems:
            print(p)
        print(f"\n{len(specs)} figure blocks · "
              f"{sum(p.startswith('ERROR') for p in problems)} errors")
        sys.exit(1 if any(p.startswith("ERROR") for p in problems) else 0)
    if a.cmd == "build":
        fmts = ("png", "svg") if a.img == "png" else ("svg", "png")
        build(a.md, a.style, a.outdir, a.out, fmts, a.img, a.rel_from)
        return
    if a.cmd == "demo":
        print(demo(a.style, a.out))


if __name__ == "__main__":
    main()
