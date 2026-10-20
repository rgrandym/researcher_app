#!/usr/bin/env python3
"""Analysis notebooks that reproduce a report's figures and tables.

A figure in a report is a claim with its numbers in the source. A notebook is
the working behind it: where each dataset came from, how it was cleaned, what
was computed, and code that redraws the figure or rebuilds the table, so a
reader can verify, rerun or change the analysis without asking anyone.

    python3 .claude/scripts/notebook.py list     <run>
    python3 .claude/scripts/notebook.py scaffold <run> "Figure 1" T2 [--name N] [--style S]
    python3 .claude/scripts/notebook.py run      <notebook.ipynb>
    python3 .claude/scripts/notebook.py check    <notebook.ipynb> [--allow-unexecuted]
    python3 .claude/scripts/notebook.py refresh  <notebook.ipynb>
    python3 .claude/scripts/notebook.py index    <run>

`scaffold` writes the deterministic half: the sources table from the evidence
ledger, the published values as data, standalone plotting code, and the
reconciliation cell that asserts the reproduced numbers equal the report's.
Every cell that needs an analyst's judgement carries ANALYST-TODO, and `check`
fails until none remain. Notebooks live in <run>/notebooks/.

Targets accept a spec ID (F3, T1), a printed number ("Figure 2", "table 1",
"fig 2"), or `all`. Printed numbers follow document order, as `figures.py build`
assigns them, so they match the exported report.
"""

import argparse
import datetime as dt
import hashlib
import importlib.metadata as md
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figures  # noqa: E402
import runmeta  # noqa: E402
import style as stylelib  # noqa: E402

TODO = "ANALYST-TODO"
URL = re.compile(r"https?://[^\s)\]>\"'`]+")
EID = re.compile(r"\[?(E\d+)\]?")
CITE = re.compile(r"\[(E\d+)\]")
SECTIONS = ("Summary", "Environment", "Data sources", "Data acquisition",
            "Cleaning and validation", "Methodology", "Analysis",
            "Reconciliation with the report", "Limitations", "Reproducibility")
PACKAGES = ("pandas", "numpy", "matplotlib", "jupyterlab", "nbclient", "ipykernel")
DATA_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet"}
PIPELINE_FILE = re.compile(r"critique|repair|guard|verify-|draft|wanted|blocked", re.I)


# ---------------------------------------------------------------- report targets

def master_of(run):
    doc = runmeta.primary(run)
    if doc is None:
        sys.exit(f"{run}: no master document (report.md) found")
    return doc


def parse_table(md_text, start):
    """The pipe table that follows a caption line: (header, rows) of raw cells."""
    lines = md_text[start:].splitlines()[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    block = []
    for ln in lines:
        if not ln.lstrip().startswith("|"):
            break
        block.append(ln)
    if len(block) < 2:
        return [], []

    def cells(ln):
        ln = ln.strip()
        ln = ln[1:] if ln.startswith("|") else ln
        ln = ln[:-1] if ln.endswith("|") else ln
        return [c.strip() for c in re.split(r"(?<!\\)\|", ln)]

    header = cells(block[0])
    rows = [cells(ln) for ln in block[2:]]
    return header, rows


def targets(master):
    """Every figure and table in document order, numbered as the export numbers them."""
    text = Path(master).read_text()
    found = []
    for spec in figures.parse(text):
        found.append({"kind": "F", "id": spec["id"], "pos": spec["_span"][0],
                      "title": spec.get("title", ""), "spec": spec,
                      "evidence": CITE.findall(json.dumps(spec))})
    for m in figures.TABLE_CAP.finditer(text):
        header, rows = parse_table(text, m.start())
        found.append({"kind": "T", "id": m.group(2), "pos": m.start(),
                      "title": CITE.sub("", m.group(1)).strip(),
                      "header": header, "rows": rows,
                      "evidence": list(dict.fromkeys(
                          CITE.findall(m.group(1)) +
                          CITE.findall(" ".join(" ".join(r) for r in rows))))})
    found.sort(key=lambda t: t["pos"])
    counts = {"F": 0, "T": 0}
    for t in found:
        counts[t["kind"]] += 1
        t["number"] = counts[t["kind"]]
        t["label"] = f"{'Figure' if t['kind'] == 'F' else 'Table'} {t['number']}"
    return found


def resolve(all_targets, names):
    """Map what the author typed ("figure 1", "T2", "all") onto targets."""
    if not names or [n.lower() for n in names] == ["all"]:
        return all_targets
    picked = []
    joined = " ".join(names).lower().replace(",", " ").replace(" and ", " ")
    tokens = re.findall(r"(fig(?:ure)?s?|tab(?:le)?s?|[ft]\w*\d+|\d+)", joined)
    kind = None
    for tok in tokens:
        if re.fullmatch(r"fig(?:ure)?s?", tok):
            kind = "F"
            continue
        if re.fullmatch(r"tab(?:le)?s?", tok):
            kind = "T"
            continue
        hit = None
        if re.fullmatch(r"[ft]\w*\d+", tok):        # a spec ID such as F3 or T1
            hit = next((t for t in all_targets if t["id"].lower() == tok), None)
        elif kind:                                   # a printed number after Figure/Table
            hit = next((t for t in all_targets
                        if t["kind"] == kind and t["number"] == int(tok)), None)
        if hit is None:
            sys.exit(f"no figure or table matches {tok!r}; run `notebook.py list <run>`")
        if hit not in picked:
            picked.append(hit)
    if not picked:
        sys.exit(f"could not read a figure or table from {' '.join(names)!r}")
    return picked


def load_evidence(run):
    rows = {}
    path = Path(run) / "evidence.jsonl"
    if path.is_file():
        for ln in path.read_text().splitlines():
            try:
                row = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("id"):
                rows[row["id"]] = row
    return rows


def data_files(run):
    """Machine-readable files the run already holds, newest knowledge first."""
    out = []
    for sub in ("external_data", "notes", "figures"):
        base = Path(run) / sub
        if base.is_dir():
            out += sorted(p for p in base.rglob("*")
                          if p.is_file() and p.suffix.lower() in DATA_EXT
                          and "ai_reports" not in p.parts and not p.name.startswith(".")
                          and not PIPELINE_FILE.search(p.name))
    return out


def slugify(text, n=6):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:n]) or "analysis"


# ---------------------------------------------------------------- cells

def md_cell(text):
    return {"cell_type": "markdown", "metadata": {}, "source": _lines(text)}


def code_cell(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": _lines(text)}


def _lines(text):
    text = text.strip("\n")
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + [parts[-1]]


def var(t):
    """Variable stem in the notebook. Kept once written, so renumbering cannot break code."""
    return t.get("var") or f"{'fig' if t['kind'] == 'F' else 'table'}{t['number']}"


def fingerprint(t):
    """Hash of what the report publishes for an item, to tell a stale notebook."""
    body = ({k: v for k, v in t["spec"].items() if not k.startswith("_")} if t["kind"] == "F"
            else [t["title"], t["header"], t["rows"]])
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def published_cell(t):
    """The item's numbers exactly as the report prints them, tagged so `refresh` can find it."""
    if t["kind"] == "F":
        cols, rows, keys = tidy_rows(t["spec"])
        if cols is None:
            text = (f"# Values as published in {t['label']}.\n"
                    f"{var(t)}_published_spec = {py({k: v for k, v in t['spec'].items() if not k.startswith('_')})}\n"
                    f"# {TODO}: lay these values out as a tidy table named {var(t)}_published.")
        else:
            text = (f"# Values exactly as published in {t['label']}, kept for the reconciliation in section 8.\n"
                    + frame_literal(f"{var(t)}_published", cols, rows))
            if "category" in cols and "series" in cols:
                text += (f"\n{var(t)}_categories = {py(list(dict.fromkeys(r[0] for r in rows)))}"
                         f"\n{var(t)}_series = {py(list(dict.fromkeys(r[1] for r in rows)))}")
    else:
        header, rows = t["header"], t["rows"]
        text = (f"# Table exactly as published in {t['label']}, kept for the reconciliation in section 8.\n"
                + frame_literal(f"{var(t)}_published", header,
                                [r + [""] * (len(header) - len(r)) for r in rows]))
    cell = code_cell(text)
    cell["metadata"]["research"] = {"published": t["id"]}
    return cell


def py(value):
    """A Python literal for a JSON value, with None rather than null."""
    return repr(value)


def tidy_rows(spec):
    """(columns, rows, key columns) for a figure spec, in long form."""
    kind = spec["type"]
    if kind in figures.NEEDS_SERIES and kind != "scatter":
        cats = spec.get("categories", [])
        rows = [(c, s.get("name", ""), v) for s in figures.series_of(spec)
                for c, v in zip(cats, s.get("values", []))]
        return ["category", "series", "value"], rows, ["category", "series"]
    if kind == "scatter":
        rows = []
        for s in spec.get("series", []):
            labels = s.get("labels") or [""] * len(s.get("points", []))
            for (x, y), lab in zip(s.get("points", []), labels):
                rows.append((s.get("name", ""), lab, x, y))
        return ["series", "label", "x", "y"], rows, ["series", "label"]
    if kind == "waterfall":
        rows = [(st.get("label"), st.get("type", "delta"), st.get("value"))
                for st in spec.get("steps", [])]
        return ["step", "kind", "value"], rows, ["step"]
    if kind == "heatmap":
        rows = [(r, c, v) for r, vals in zip(spec.get("rows", []), spec.get("values", []))
                for c, v in zip(spec.get("columns", []), vals)]
        return ["row", "column", "value"], rows, ["row", "column"]
    if kind == "donut":
        rows = list(zip(spec.get("categories", []), spec.get("values", [])))
        return ["category", "value"], rows, ["category"]
    if kind == "stat":
        rows = [(s.get("label"), s.get("value"), s.get("delta")) for s in spec.get("stats", [])]
        return ["label", "value", "delta"], rows, ["label"]
    return None, None, None


def frame_literal(name, columns, rows):
    body = ",\n".join(f"        {py(tuple(r))}" for r in rows)
    return (f"{name} = pd.DataFrame(\n    [\n{body},\n    ],\n"
            f"    columns={py(columns)},\n)")


def decimals_of(rows, col):
    d = 0
    for r in rows:
        v = r[col]
        if isinstance(v, float) and not float(v).is_integer():
            d = max(d, len(repr(v).split(".")[1]))
    return d


PLOT = {
    "bar": "wide.plot.bar(ax=ax, color=PALETTE[: wide.shape[1]], width=0.75, rot=0)\n"
           "ax.set_xlabel('')",
    "hbar": "wide.iloc[::-1].plot.barh(ax=ax, color=PALETTE[: wide.shape[1]], width=0.75)\n"
            "ax.set_ylabel('')",
    "stacked_bar": "wide.plot.bar(ax=ax, stacked=True, color=PALETTE[: wide.shape[1]], width=0.7, rot=0)\n"
                   "ax.set_xlabel('')",
    "stacked_hbar": "wide.iloc[::-1].plot.barh(ax=ax, stacked=True, color=PALETTE[: wide.shape[1]], width=0.7)\n"
                    "ax.set_ylabel('')",
    "line": "x = range(len(wide))\n"
            "for colour, name in zip(PALETTE, wide.columns):\n"
            "    ax.plot(x, wide[name], marker='o', markersize=3, color=colour, label=name)\n"
            "step = SPEC.get('tick_every') or max(1, -(-len(wide) // 8))  # at most about 8 labels\n"
            "ax.set_xticks(list(x)[::step], wide.index[::step], rotation=0)",
    "area": "wide.plot.area(ax=ax, stacked=SPEC.get('stacked', True), color=PALETTE[: wide.shape[1]], alpha=0.85)",
    "dot": "y = range(len(wide))\n"
           "ax.hlines(y, 0, wide.max(axis=1), color='#dddddd', linewidth=0.8, zorder=1)\n"
           "for colour, name in zip(PALETTE, wide.columns):\n"
           "    ax.scatter(wide[name], y, color=colour, s=40, label=name, zorder=2)\n"
           "ax.set_yticks(list(y), wide.index)\n"
           "ax.invert_yaxis()",
    "dumbbell": "first, last = wide.columns[:2]\n"
                "y = range(len(wide))\n"
                "ax.hlines(y, wide[first], wide[last], color='#bbbbbb', linewidth=2, zorder=1)\n"
                "ax.scatter(wide[first], y, color=PALETTE[0], s=40, label=first, zorder=2)\n"
                "ax.scatter(wide[last], y, color=PALETTE[1], s=40, label=last, zorder=2)\n"
                "ax.set_yticks(list(y), wide.index)\n"
                "ax.invert_yaxis()",
    "slope": "for colour, name in zip(PALETTE * 10, wide.columns):\n"
             "    ax.plot([0, 1], wide[name].values[:2], marker='o', color=colour, label=name)\n"
             "ax.set_xticks([0, 1], wide.index[:2])",
}

PLOT_OTHER = {
    "scatter": ("for colour, (name, grp) in zip(PALETTE, data.groupby('series', sort=False)):\n"
                "    ax.scatter(grp['x'], grp['y'], color=colour, s=36, label=name)\n"
                "    for _, r in grp.iterrows():\n"
                "        if r['label']:\n"
                "            ax.annotate(r['label'], (r['x'], r['y']), xytext=(4, 3),\n"
                "                        textcoords='offset points', fontsize=8)\n"
                "ax.set_xlabel(SPEC.get('x_label', 'x'))\n"
                "ax.set_ylabel(SPEC.get('y_label', 'y'))"),
    "waterfall": ("level, bottoms, heights, colours = 0.0, [], [], []\n"
                  "for _, r in data.iterrows():\n"
                  "    if r['kind'] in ('start', 'total'):\n"
                  "        bottoms.append(0); heights.append(r['value']); level = r['value']\n"
                  "        colours.append(PALETTE[0])\n"
                  "    else:\n"
                  "        bottoms.append(level if r['value'] >= 0 else level + r['value'])\n"
                  "        heights.append(abs(r['value'])); level += r['value']\n"
                  "        colours.append(PALETTE[1] if r['value'] >= 0 else PALETTE[2])\n"
                  "ax.bar(data['step'], heights, bottom=bottoms, color=colours)\n"
                  "ax.tick_params(axis='x', rotation=20)"),
    "heatmap": ("grid = data.pivot(index='row', columns='column', values='value')\n"
                "grid = grid.reindex(index=list(dict.fromkeys(data['row'])),\n"
                "                    columns=list(dict.fromkeys(data['column'])))\n"
                "im = ax.imshow(grid.values.astype(float), cmap='Blues', aspect='auto')\n"
                "ax.set_xticks(range(grid.shape[1]), grid.columns)\n"
                "ax.set_yticks(range(grid.shape[0]), grid.index)\n"
                "for i in range(grid.shape[0]):\n"
                "    for j in range(grid.shape[1]):\n"
                "        v = grid.iat[i, j]\n"
                "        if pd.notna(v):\n"
                "            ax.text(j, i, f'{v:g}', ha='center', va='center', fontsize=8)\n"
                "fig.colorbar(im, ax=ax, shrink=0.8)"),
    "donut": ("ax.pie(data['value'], labels=data['category'], colors=PALETTE[: len(data)],\n"
              "       wedgeprops={'width': 0.4}, startangle=90, counterclock=False)\n"
              "ax.set_aspect('equal')"),
}


def plot_code(t, style_name):
    spec = t["spec"]
    kind = spec["type"]
    n = t["number"]
    slim = {k: v for k, v in spec.items() if k in (
        "type", "title", "subtitle", "unit", "prefix", "tick_every", "stacked",
        "x_label", "y_label", "baseline", "decimals")}
    head = (f"SPEC = {py(slim)}\n"
            f"data = {var(t)}_data.copy()\n")
    if kind == "stat":
        return head + "display(data)  # the published figure is a row of headline tiles"
    if kind in PLOT:
        head += ("wide = data.pivot(index='category', columns='series', values='value')\n"
                 f"wide = wide.reindex(index={var(t)}_categories, columns={var(t)}_series)\n")
        body = PLOT[kind]
    elif kind in PLOT_OTHER:
        body = PLOT_OTHER[kind]
    else:
        return (head + f"# {TODO}: '{kind}' has no standard matplotlib equivalent here. Write the\n"
                f"# plotting code for this chart from `data` and remove this marker.\n"
                f"fig, ax = plt.subplots(figsize=(6.5, 4))")
    w = 9.0 if spec.get("wide") else 6.5
    return (head +
            f"fig, ax = plt.subplots(figsize=({w}, 4.2))\n" + body + "\n"
            "if SPEC.get('baseline') is not None:\n"
            "    ax.axhline(SPEC['baseline'], color='grey', linestyle='--', linewidth=0.8)\n"
            "subtitle = textwrap.fill(SPEC.get('subtitle', ''), 100)\n"
            "ax.set_title(textwrap.fill(SPEC['title'], 70), loc='left', fontsize=11, fontweight='bold',\n"
            "             pad=8 + 11 * (subtitle.count('\\n') + 1) * bool(subtitle))\n"
            "ax.text(0, 1.015, subtitle, transform=ax.transAxes, fontsize=8, color='grey',\n"
            "        ha='left', va='bottom')\n"
            "if len(ax.get_xticklabels()) > 6 and SPEC['type'] in ('bar', 'stacked_bar'):\n"
            "    ax.tick_params(axis='x', rotation=45)\n"
            "    plt.setp(ax.get_xticklabels(), ha='right')\n"
            "ax.spines[['top', 'right']].set_visible(False)\n"
            "if ax.get_legend_handles_labels()[0] and data.get('series', pd.Series()).nunique() > 1:\n"
            "    ax.legend(frameon=False, fontsize=8)\n"
            "elif ax.get_legend():\n"
            "    ax.get_legend().remove()\n"
            f"fig.savefig(OUTPUT_DIR / 'figure_{n}.png', dpi=200, bbox_inches='tight')\n"
            f"fig.savefig(OUTPUT_DIR / 'figure_{n}.svg', bbox_inches='tight')\n"
            "plt.show()")


# ---------------------------------------------------------------- scaffold

def palette(style_name):
    st = stylelib.load(style_name) if style_name else None
    if st is None:
        st = stylelib.load(stylelib.available()[0])
    return list(st["series"])


def default_style(run):
    exp = Path(run) / "export"
    styles = sorted(p.name for p in exp.iterdir() if p.is_dir()) if exp.is_dir() else []
    known = set(stylelib.available())
    return next((s for s in styles if s in known), stylelib.available()[0])


def versions():
    out = {}
    for pkg in PACKAGES:
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            out[pkg] = None
    return out


def sources_table(ids, ev):
    head = ("| Ref | Source | Publisher | Published | Type | Accessed | Link |\n"
            "|---|---|---|---|---|---|---|")
    lines = [head]
    for i in ids:
        r = ev.get(i)
        if not r:
            lines.append(f"| {i} | {TODO}: no ledger row for this reference | | | | | |")
            continue
        cell = lambda k: str(r.get(k) or "").replace("|", "/").replace("\n", " ")
        link = f"[link]({r['url']})" if r.get("url") else "supplied file"
        lines.append(f"| {i} | {cell('title')} | {cell('publisher')} | {cell('published') or 'n.d.'} "
                     f"| {cell('type')} | {cell('accessed')} | {link} |")
    return "\n".join(lines)


def excerpts(ids, ev):
    out = []
    for i in ids:
        r = ev.get(i)
        if r and r.get("quote"):
            q = " ".join(str(r["quote"]).split())
            out.append(f"**{i}**, {r.get('publisher') or r.get('title', '')}:\n\n> {q}")
    return "\n\n".join(out) or "No verbatim excerpts are held for these sources."


def scaffold(run, picked, name=None, style_name=None):
    run = Path(run)
    master = master_of(run)
    ev = load_evidence(run)
    style_name = style_name or default_style(run)
    report_title = next((ln[2:].strip() for ln in master.read_text().splitlines()
                         if ln.startswith("# ")), run.name)
    labels = " and ".join(t["label"] for t in picked)
    ids = list(dict.fromkeys(i for t in picked for i in t["evidence"]))
    nbdir = run / "notebooks"
    for sub in ("data/raw", "data/processed", "output"):
        (nbdir / sub).mkdir(parents=True, exist_ok=True)
    if name is None:
        name = "-".join(f"{'figure' if t['kind'] == 'F' else 'table'}-{t['number']}"
                        for t in picked)
        if len(picked) == 1:
            name += "-" + slugify(picked[0]["title"], 5)
    path = nbdir / f"{name}.ipynb"
    vers = versions()
    files = data_files(run)

    cells = []
    cells.append(md_cell(
        f"# {labels}: reproducible analysis\n\n"
        f"**Report:** {report_title}  \n"
        f"**Reproduces:** " + "; ".join(f"{t['label']}, *{t['title']}*" for t in picked) + "  \n"
        f"**Prepared:** {dt.date.today().isoformat()}\n\n"
        "This notebook documents how the numbers behind the items above were obtained, "
        "cleaned and analysed, and rebuilds each one from that work. Run it top to bottom "
        "with *Restart and Run All*; the reconciliation section fails loudly if any "
        "reproduced number departs from the published one.\n\n"
        "**Contents**\n\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(SECTIONS))))
    cells.append(md_cell(
        "## 1. Summary\n\n"
        f"{TODO}: the question each item answers, the data behind it, the method in one "
        "sentence, and the result in plain words. State the main caveat."))

    req = "\n".join(f"{p}=={v}" if v else p for p, v in vers.items())
    cells.append(md_cell(
        "## 2. Environment\n\n"
        "Python 3.10 or later. The pinned versions this notebook was last run with are "
        "listed in `requirements.txt` beside it:\n\n"
        f"```text\n{req}\n```\n\n"
        "Install them with `pip install -r requirements.txt`. Paths are relative to the "
        "notebook's folder: raw inputs in `data/raw/` are never modified, cleaned tables "
        "go to `data/processed/`, and rebuilt figures and tables go to `output/`."))
    cells.append(code_cell(
        "import hashlib\nimport platform\nimport textwrap\nfrom pathlib import Path\n\n"
        "import matplotlib\nimport matplotlib.pyplot as plt\nimport numpy as np\nimport pandas as pd\n\n"
        "pd.set_option('display.max_columns', 50)\npd.set_option('display.width', 120)\n\n"
        "RAW_DIR = Path('data/raw')\nPROCESSED_DIR = Path('data/processed')\nOUTPUT_DIR = Path('output')\n"
        "for d in (RAW_DIR, PROCESSED_DIR, OUTPUT_DIR):\n    d.mkdir(parents=True, exist_ok=True)\n\n"
        f"# Series colours of the report's '{style_name}' style, so the redrawn charts match.\n"
        f"PALETTE = {py(palette(style_name))}\n"
        "plt.rcParams.update({'figure.dpi': 110, 'axes.grid': True, 'grid.alpha': 0.25,\n"
        "                     'axes.axisbelow': True, 'font.size': 9})\n\n\n"
        "def sha256(path):\n"
        "    \"\"\"Checksum of a file, to show an input is the one this analysis used.\"\"\"\n"
        "    return hashlib.sha256(Path(path).read_bytes()).hexdigest()\n\n\n"
        "def profile(df, name):\n"
        "    \"\"\"Shape, types, missing values and duplicate rows of a table.\"\"\"\n"
        "    print(f'{name}: {df.shape[0]} rows x {df.shape[1]} columns; '\n"
        "          f'{int(df.duplicated().sum())} duplicate rows')\n"
        "    return pd.DataFrame({'dtype': df.dtypes.astype(str),\n"
        "                         'missing': df.isna().sum(),\n"
        "                         'example': df.iloc[0] if len(df) else None})\n\n\n"
        "print('Python', platform.python_version(), '| pandas', pd.__version__,\n"
        "      '| numpy', np.__version__, '| matplotlib', matplotlib.__version__)"))

    held = "\n".join(f"- `{p.relative_to(run)}`" for p in files) or "- none"
    cells.append(md_cell(
        "## 3. Data sources\n\n"
        "Reference IDs match the report's reference list. A source this notebook uses that "
        "the report does not cite is added to the table with its ID and marked *notebook only*.\n\n"
        f"{sources_table(ids, ev)}\n\n"
        f"{TODO}: for each source, say what it measures, its coverage (period, geography, "
        "population), its licence or terms of use where stated, and whether the numbers "
        "were downloaded as data or transcribed from a document. Remove this paragraph.\n\n"
        f"<!-- Data files held with the research, for the analyst's reference; delete this "
        f"comment once acquisition is written:\n{held}\n-->"))

    cells.append(md_cell(
        "## 4. Data acquisition\n\n"
        f"{TODO}: describe how each input is obtained. Download machine-readable data from "
        "its published URL into `data/raw/` and record the checksum. Where the source is a "
        "document, transcribe the figures into a table that names the page or table they "
        "came from. Remove this paragraph."))
    for t in picked:
        cells.append(published_cell(t))
    cells.append(code_cell(
        f"# {TODO}: acquisition code. Download or load each raw input into data/raw/,\n"
        "# print its checksum with sha256(), and load it into a DataFrame."))

    cells.append(md_cell(
        "## 5. Cleaning and validation\n\n"
        f"{TODO}: each step taken to make the raw data usable (renaming, type conversion, "
        "unit harmonisation, filtering to the period and population, handling of missing "
        "or revised values) and why. Back each step with an assertion. Remove this paragraph."))
    cells.append(code_cell(
        f"# {TODO}: cleaning steps, then profile() and assertions on the clean table, e.g.\n"
        "# assert clean['date'].is_monotonic_increasing\n"
        "# assert clean['value'].between(0, 1_000).all()\n"
        "# clean.to_csv(PROCESSED_DIR / 'clean.csv', index=False)"))

    gaps = [f"- {t['label']}: {t['spec']['data_gaps']}" for t in picked
            if t["kind"] == "F" and t["spec"].get("data_gaps")]
    notes = [f"- {t['label']}: {t['spec']['note']}" for t in picked
             if t["kind"] == "F" and t["spec"].get("note")]
    cells.append(md_cell(
        "## 6. Methodology\n\n"
        + ("The report states these derivations:\n\n" + "\n".join(notes) + "\n\n" if notes else "")
        + f"{TODO}: the method, step by step, with every formula written out (indices, "
        "growth rates, averages, shares, sums), the choices made and the alternatives "
        "rejected, so another analyst could reach the same numbers independently. "
        "Remove this paragraph."))

    cells.append(md_cell("## 7. Analysis\n\nEach item is derived from the clean data, then drawn or tabulated."))
    for t in picked:
        if t["kind"] == "F":
            cells.append(md_cell(f"### {t['label']}. {t['title']}"))
            cells.append(code_cell(
                f"# {TODO}: derive {var(t)}_data from the clean data, with the same columns as\n"
                f"# {var(t)}_published. Copy the published values only when the source offers no\n"
                f"# machine-readable data, and say so in section 4.\n"
                f"{var(t)}_data = {var(t)}_published.copy()\n"
                f"{var(t)}_data.to_csv(PROCESSED_DIR / '{var(t)}_data.csv', index=False)\n"
                f"{var(t)}_data"))
            cells.append(code_cell(plot_code(t, style_name)))
        else:
            cells.append(md_cell(f"### {t['label']}. {t['title']}"))
            cells.append(code_cell(
                f"# {TODO}: build {var(t)} from the clean data, with the published columns.\n"
                f"{var(t)} = {var(t)}_published.copy()\n"
                f"{var(t)}.to_csv(OUTPUT_DIR / 'table_{t['number']}.csv', index=False)\n"
                f"{var(t)}"))

    recon = ["def reconcile(reproduced, published, keys, value_cols, tolerance):\n"
             "    \"\"\"Rows where the reproduced value differs from the published one.\"\"\"\n"
             "    both = reproduced.merge(published, on=keys, how='outer',\n"
             "                            suffixes=('_reproduced', '_published'), indicator=True)\n"
             "    bad = both['_merge'] != 'both'\n"
             "    for col in value_cols:\n"
             "        a = pd.to_numeric(both[f'{col}_reproduced'], errors='coerce')\n"
             "        b = pd.to_numeric(both[f'{col}_published'], errors='coerce')\n"
             "        same_gap = a.isna() & b.isna()\n"
             "        bad |= ~same_gap & ~((a - b).abs() <= tolerance)\n"
             "    return both[bad]\n"]
    for t in picked:
        if t["kind"] == "F":
            cols, rows, keys = tidy_rows(t["spec"])
            if cols is None:
                recon.append(f"# {TODO}: reconcile {var(t)}_data with {var(t)}_published.")
                continue
            vcols = [c for c in cols if c not in keys and c != "kind" and c != "delta"]
            d = max(decimals_of(rows, cols.index(c)) for c in vcols)
            tol = 0.5 * 10 ** -d
            recon.append(
                f"# Published values carry {d} decimal place(s), so differences up to {tol:g} are rounding.\n"
                f"diff = reconcile({var(t)}_data, {var(t)}_published, {py(keys)}, {py(vcols)}, {tol:g})\n"
                f"assert diff.empty, f'{t['label']} does not reproduce:\\n{{diff}}'\n"
                f"print('{t['label']}: all', len({var(t)}_published), 'values reproduce the report')")
        else:
            recon.append(
                f"norm = lambda df: df.astype(str).apply(lambda s: s.str.strip())\n"
                f"assert norm({var(t)}).equals(norm({var(t)}_published)), '{t['label']} does not reproduce'\n"
                f"print('{t['label']}: all', {var(t)}_published.size, 'cells reproduce the report')")
    cells.append(md_cell(
        "## 8. Reconciliation with the report\n\n"
        "Every reproduced number is compared with the published one. A difference beyond "
        "rounding stops the notebook, so a figure that no longer follows from its data "
        "cannot pass unnoticed."))
    cells.append(code_cell("\n\n".join(recon)))

    cells.append(md_cell(
        "## 9. Limitations\n\n"
        + ("Data the research could not obtain, shown as gaps in the report:\n\n" + "\n".join(gaps) + "\n\n"
           if gaps else "")
        + f"{TODO}: what this data cannot show, known biases or breaks in the series, "
        "revisions to expect, and how sensitive the result is to the method's choices. "
        "Remove this paragraph."))
    cells.append(md_cell(
        "## 10. Reproducibility\n\n"
        "To rerun: install the requirements, open this notebook from its own folder and "
        "choose *Restart and Run All*. Downloaded inputs are cached in `data/raw/`; delete "
        "them to fetch fresh copies, and expect the reconciliation to fail if a source has "
        "since revised its figures. To change the analysis, edit sections 5 to 7; section 8 "
        "then shows which published numbers your change moves."))
    cells.append(code_cell(
        "for pkg in (pd, np, matplotlib):\n    print(f'{pkg.__name__:<12}{pkg.__version__}')\n"
        "print(f\"{'python':<12}{platform.python_version()}\")\n"
        "print('outputs:', sorted(p.name for p in OUTPUT_DIR.iterdir()))"))
    cells.append(md_cell("## Appendix: source excerpts\n\nThe passages each reference was cited for, "
                         "quoted from the source.\n\n" + excerpts(ids, ev)))

    nb = {"cells": cells,
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"},
                       "research": {"run": run.name, "master": master.name, "style": style_name,
                                    "targets": [{"id": t["id"], "label": t["label"], "title": t["title"],
                                                 "var": var(t), "fingerprint": fingerprint(t)}
                                                for t in picked],
                                    "evidence": ids}},
          "nbformat": 4, "nbformat_minor": 5}
    if path.exists():
        sys.exit(f"{path} exists; pass --name for a different file or delete it first")
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
    reqfile = nbdir / "requirements.txt"
    if not reqfile.exists():
        reqfile.write_text(f"# Last run with Python {sys.version.split()[0]}\n{req}\n")
    print(f"{path}")
    print(f"  {labels}; {len(ids)} sources; style {style_name}")
    return path


# ---------------------------------------------------------------- run

PRELUDE = ("import matplotlib\nmatplotlib.use('Agg')\n"
           "try:\n    display\nexcept NameError:\n"
           "    def display(*objs):\n        for o in objs:\n            print(o)\n")


def run_nb(path):
    """Execute top to bottom. With nbclient, outputs are written into the notebook;
    without it, the code cells run as one script, which checks the same thing."""
    path = Path(path).resolve()
    nb = json.loads(path.read_text())
    try:
        import nbformat
        from nbclient import NotebookClient
    except ImportError:
        nbformat = None
    if nbformat is not None:
        node = nbformat.read(str(path), as_version=4)
        try:
            NotebookClient(node, timeout=600, kernel_name="python3",
                           resources={"metadata": {"path": str(path.parent)}}).execute()
        except Exception as e:                   # noqa: BLE001  CellExecutionError and kernel failures
            nbformat.write(node, str(path))
            print(f"FAIL {path.name}: {str(e).splitlines()[0] if str(e) else e}")
            return 1
        nbformat.write(node, str(path))
        print(f"OK   {path.name}: executed with outputs saved")
        return 0
    code = PRELUDE + "\n\n".join(
        "".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    code = re.sub(r"^(\s*)(\w+)\s*$", r"\1display(\2)", code, flags=re.M)  # bare names display, as in Jupyter
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(code)
    env = dict(os.environ, MPLBACKEND="Agg")
    p = subprocess.run([sys.executable, fh.name], cwd=path.parent, env=env,
                       capture_output=True, text=True)
    os.unlink(fh.name)
    if p.returncode:
        print(f"FAIL {path.name}:\n" + "\n".join(p.stderr.strip().splitlines()[-12:]))
        return 1
    print(f"OK   {path.name}: ran top to bottom as a script (outputs not saved; "
          f"`pip install nbclient ipykernel` saves them into the notebook)")
    return 0


# ---------------------------------------------------------------- check

def check(path, allow_unexecuted=False):
    path = Path(path).resolve()
    run = path.parent.parent
    problems = []
    try:
        nb = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR {path.name}: not valid JSON: {e}")
        return 1
    if nb.get("nbformat") != 4 or not isinstance(nb.get("cells"), list):
        problems.append("ERROR not an nbformat 4 notebook")
    cells = nb.get("cells", [])
    text = lambda c: "".join(c.get("source", []))
    md_text = "\n\n".join(text(c) for c in cells if c["cell_type"] == "markdown")
    code_text = "\n\n".join(text(c) for c in cells if c["cell_type"] == "code")

    for i, c in enumerate(cells):
        if TODO in text(c):
            first = next(ln for ln in text(c).splitlines() if TODO in ln)
            problems.append(f"ERROR cell {i}: unfinished: {first.strip()[:90]}")
    heads = re.findall(r"^#{1,3}\s+(?:\d+\.\s+)?(.+)$", md_text, re.M)
    for s in SECTIONS:
        if not any(h.strip().lower().startswith(s.lower()) for h in heads):
            problems.append(f"ERROR missing section: {s}")
    # The notebook folder is shared on its own, so it may read nothing outside it.
    for m in re.finditer(r"""['"](\.\./[^'"]*)['"]""", code_text):
        problems.append(f"ERROR path outside the notebook folder: {m.group(1)}; copy the file into data/raw/")
    src = next((text(c) for c in cells if c["cell_type"] == "markdown"
                and re.match(r"#+\s+(?:\d+\.\s+)?Data sources", text(c))), "")
    listed = set(re.findall(r"^\|\s*(E\d+)\s*\|", src, re.M))
    for eid in sorted(set(CITE.findall(md_text)) - listed):
        problems.append(f"ERROR {eid} is cited but missing from the Data sources table")
    appendix = next((text(c) for c in cells if c["cell_type"] == "markdown"
                     and "Appendix" in text(c).split("\n")[0]), "")
    for eid in sorted(listed):
        if f"**{eid}**" not in appendix:
            problems.append(f"WARN  {eid} has no excerpt in the appendix")
    if "reconcile(" not in code_text and "assert" not in code_text:
        problems.append("ERROR no reconciliation: the notebook never checks its numbers against the report")

    ev = load_evidence(run)
    for eid in sorted(set(CITE.findall(md_text + code_text)) |
                      set(re.findall(r"\|\s*(E\d+)\s*\|", md_text))):
        if eid not in ev:
            problems.append(f"ERROR reference {eid} has no row in the evidence ledger")
    # Every link must be one the research actually fetched or was given.
    known = set()
    for r in ev.values():
        known |= set(URL.findall(json.dumps(r)))
    for sub in ("external_data", "notes"):
        for p in (run / sub).rglob("*") if (run / sub).is_dir() else []:
            if p.is_file() and p.suffix.lower() in (".md", ".txt", ".json", ".jsonl", ".csv"):
                try:
                    known |= set(URL.findall(p.read_text(errors="ignore")))
                except OSError:
                    pass
    norm = lambda u: u.rstrip(".,;:").rstrip("/")
    known = {norm(u) for u in known}
    for u in sorted(set(URL.findall(md_text + code_text))):
        if norm(u) not in known:
            problems.append(f"ERROR link not traceable to a fetched source: {u[:100]}")

    # The narrative is prose a reader sees: same voice and same ban on pipeline talk.
    scripts = Path(__file__).resolve().parent
    import audit_citations
    for p in audit_citations.scan_artifacts(md_text, path.name):
        if p.startswith("ERROR") and "unfinished scaffold" not in p:   # ANALYST-TODO is reported per cell
            problems.append(p)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(re.sub(r"```.*?```", "", md_text, flags=re.S))
    out = subprocess.run([sys.executable, str(scripts / "voice.py"), "lint", fh.name],
                         capture_output=True, text=True).stdout
    os.unlink(fh.name)
    problems += [f"ERROR {ln.replace(fh.name, 'markdown')}" for ln in out.splitlines()
                 if ln.startswith("VOICE")]

    outputs = [o for c in cells if c["cell_type"] == "code" for o in c.get("outputs", [])]
    if any(o.get("output_type") == "error" for o in outputs):
        problems.append("ERROR a cell raised an error when last executed")
    if not outputs and not allow_unexecuted:
        problems.append("WARN  notebook has no saved outputs; run it with nbclient so a reader "
                        "sees results without executing (pip install nbclient ipykernel)")
    for p in problems:
        print(p)
    errs = sum(p.startswith("ERROR") for p in problems)
    print(f"{path.name}: {errs} errors, {len(problems) - errs} warnings")
    return 1 if errs else 0


# ---------------------------------------------------------------- refresh

def refresh(path):
    """Rewrite the published-values cells from the current report and record the new
    fingerprints. The analyst's derivation is untouched: rerunning then shows, in the
    reconciliation, exactly which numbers the report changed."""
    path = Path(path).resolve()
    run = path.parent.parent
    nb = json.loads(path.read_text())
    meta = nb["metadata"]["research"]
    now = {t["id"]: t for t in targets(master_of(run))}
    for rec in meta["targets"]:
        t = now.get(rec["id"])
        if t is None:
            print(f"WARN {rec['id']} ({rec['label']}) is no longer in the report; this notebook reproduces a deleted item")
            continue
        t["var"] = rec.get("var") or var(t)
        fp = fingerprint(t)
        for i, c in enumerate(nb["cells"]):
            if c.get("metadata", {}).get("research", {}).get("published") == rec["id"]:
                nb["cells"][i] = published_cell(t)
        if t["label"] != rec["label"]:
            print(f"NOTE {rec['label']} is now {t['label']}; update the headings that name it")
        print(f"{'same' if fp == rec.get('fingerprint') else 'CHANGED'} {t['label']} ({t['id']})")
        rec.update(label=t["label"], title=t["title"], fingerprint=fp, var=t["var"])
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- index

def index(run):
    run = Path(run)
    nbdir = run / "notebooks"
    rows = []
    for p in sorted(nbdir.glob("*.ipynb")):
        meta = json.loads(p.read_text()).get("metadata", {}).get("research", {})
        what = "; ".join(f"{t['label']}, {t['title']}" for t in meta.get("targets", []))
        rows.append(f"| [{p.name}]({p.name}) | {what} |")
    master = master_of(run)
    title = next((ln[2:].strip() for ln in master.read_text().splitlines() if ln.startswith("# ")), run.name)
    (nbdir / "README.md").write_text(
        f"# Analysis notebooks: {title}\n\n"
        "Each notebook documents and reproduces figures or tables in the report: data "
        "sources, acquisition, cleaning, method, the rebuilt item, and a check that its "
        "numbers match the published ones.\n\n"
        "```bash\npip install -r requirements.txt\njupyter lab\n```\n\n"
        "| Notebook | Reproduces |\n|---|---|\n" + "\n".join(rows) + "\n\n"
        "`data/raw/` holds inputs as obtained, `data/processed/` the cleaned tables, and "
        "`output/` the rebuilt figures and tables.\n")
    print(f"{nbdir / 'README.md'}: {len(rows)} notebooks")


def cmd_list(run):
    run = Path(run)
    master = master_of(run)
    ts = targets(master)
    nbdir = run / "notebooks"
    have = {}
    current = {t["id"]: fingerprint(t) for t in ts}
    for p in nbdir.glob("*.ipynb") if nbdir.is_dir() else []:
        for t in json.loads(p.read_text()).get("metadata", {}).get("research", {}).get("targets", []):
            state = "" if t.get("fingerprint") == current.get(t["id"]) else " (stale)"
            have.setdefault(t["id"], []).append(p.name + state)
    print(f"{master}")
    for t in ts:
        kind = t["spec"]["type"] if t["kind"] == "F" else f"{len(t['rows'])} rows"
        nb = ", ".join(have.get(t["id"], [])) or "-"
        print(f"{t['label']:<10} {t['id']:<5} {kind:<16} {len(t['evidence']):>3} refs  "
              f"notebook: {nb}\n           {t['title'][:100]}")
    files = data_files(run)
    if files:
        print("data held with the research:")
        for p in files:
            print(f"  {p.relative_to(run)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("list", help="figures and tables in the master, with their notebooks")
    a.add_argument("run")
    s = sub.add_parser("scaffold", help="write a notebook skeleton for one or more items")
    s.add_argument("run")
    s.add_argument("targets", nargs="+", help='F1, T2, "Figure 1", "table 2", or all')
    s.add_argument("--name", help="file name without .ipynb")
    s.add_argument("--style", help="style whose palette the charts use")
    s.add_argument("--each", action="store_true", help="one notebook per item instead of one for all")
    r = sub.add_parser("run", help="execute a notebook top to bottom")
    r.add_argument("notebook")
    c = sub.add_parser("check", help="lint a finished notebook")
    c.add_argument("notebook")
    c.add_argument("--allow-unexecuted", action="store_true")
    f = sub.add_parser("refresh", help="update published values after the report changed")
    f.add_argument("notebook")
    i = sub.add_parser("index", help="write notebooks/README.md")
    i.add_argument("run")
    args = ap.parse_args()

    if args.cmd == "list":
        cmd_list(args.run)
    elif args.cmd == "scaffold":
        picked = resolve(targets(master_of(args.run)), args.targets)
        if args.each:
            for t in picked:
                scaffold(args.run, [t], None, args.style)
        else:
            scaffold(args.run, picked, args.name, args.style)
    elif args.cmd == "run":
        sys.exit(run_nb(args.notebook))
    elif args.cmd == "check":
        sys.exit(check(args.notebook, args.allow_unexecuted))
    elif args.cmd == "refresh":
        refresh(args.notebook)
    elif args.cmd == "index":
        index(args.run)


if __name__ == "__main__":
    main()
