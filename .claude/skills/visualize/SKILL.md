---
name: visualize
description: Put tables and charts inside a research report, write figure specs, caption and number figures and tables, and handle data that could not be obtained.
---

# Visualize

A chart in this workspace is **a claim, not an illustration.** It carries evidence
IDs, it is validated by a script, and its numbers live in the report source as
data rather than in a picture. That is what makes a figure or table as auditable as a
sentence — and what stops the failure mode where a chart says something the text
never claimed and no reviewer ever checked.

Read `references/figure-spec.md` for the full field reference before writing your
first block. Design judgment for charts generally lives in the global `dataviz`
skill; this skill owns the mechanics, the citation discipline, and the workspace's
figure and table conventions.

## Does this finding earn a figure or table?

Charts cost the reader attention. Spend it only where the shape of the data *is*
the finding:

| The finding is… | Give it |
|---|---|
| One number | A sentence. Never a chart |
| Two or three numbers | A sentence, or a stat row if they are the report's headline figures |
| A ranking across 4+ items | `dot` (preferred) or `hbar` |
| A comparison of 2–4 groups across categories | `bar` |
| A trend over time | `line` |
| A composition that changed | `stacked_bar`, or `waterfall` if you can name the drivers |
| Before/after per item | `dumbbell`, or `slope` if rank order is the point |
| A relationship between two variables | `scatter` |
| A grid of qualitative states | `heatmap`, or a plain markdown table |
| Anything with named text values, mixed units, or footnotes per cell | **A table.** Not a chart |

**Default to a table.** Tables are searchable, translatable, quotable, and survive
every export intact. Reach for a chart only when the reader needs to see a shape —
a gap, a crossing, a cluster, an outlier — that a table hides.

Three figures or tables in a ten-page report is normal. Ten is a deck pretending to be a
report.

**The necessity test, applied to every figure or table before it ships:** delete it and
read the surrounding prose. If the argument survives intact, the figure or table was
decoration and stays deleted. A figure or table earns its place only when the reader
would have to reconstruct a shape — a gap, a crossing, a cluster, an outlier —
from a sentence that cannot carry it. Visuals here prove a point or they go.

## Writing a figure

A fenced ```figure block holding one JSON object, placed where the figure belongs:

````markdown
```figure
{"id": "F2", "type": "bar",
 "title": "Adoption stalled in the two regulated markets",
 "subtitle": "Installed base, thousands of units, year end",
 "source": "[E7][E12]", "unit": "k",
 "categories": ["Germany", "France", "Spain"],
 "series": [{"name": "2024", "values": [120, 98, 76]},
            {"name": "2025", "values": [124, 101, 112]}]}
```
````

**`title` is the message, not the subject.** "Adoption stalled in the two regulated
markets" — never "Adoption by market". Same rule as headings: a title that only
names the axes has wasted the most-read line on the page.

**`subtitle` carries the basis**: unit, period, geography, population. A chart
without its basis is a future misquotation.

**`source` must contain at least one `[E#]`.** The validator rejects a figure
without one. Every number plotted must trace to the same evidence rows that would
back the claim in prose — if you cannot cite it, you cannot chart it.

### Every number in a figure comes from evidence.jsonl

Do not compute a figure's values from memory, from a plausible trend, or by
interpolating between two sourced points. If the chart shows five years, five
years must be sourced. A derived value (a sum, a share, a CAGR) is allowed when
its inputs are cited and the derivation is stated in `note` — anything else is a
fabricated number wearing a chart's authority.

### Cross-references

Write `[[F2]]` or `[[T1]]` in prose; these resolve to "Figure 2" and "Table 1"
at build time. Never hard-code a number because insertions renumber the report.

### Captioning a table

Put this line directly above the table so its caption stays with the first rows:

```markdown
**Table:** Published vendor pricing across the five shortlisted suppliers [E22][E23] {#T1}
```

Figures and tables have separate sequences, each numbered in document order.
Use "Figure" and "Table" in captions and prose. Never use "Exhibit".

Before delivery, inspect the rendered page. Keep every table within its page width
with readable type. Rework wide tables into long form, split them by period, or
use a landscape page; do not solve overflow by shrinking type below 8 pt.
Check chart axes, units, tick spacing, legends, labels, captions, and references
at final display size. Remove a redundant legend for one series, and keep
multi-series legends close to the plot. Make every figure readable without zoom.

## Data you could not obtain

**Build the figure anyway**, with its holes visible. Doctrine and syntax:
`.claude/references/gaps.md`. The mechanics here: the value is `null`, the spec
carries a `data_gaps` note, and the renderer draws a hatched slot labelled "to
obtain" where the bar would be, appending the note to the caption.

```json
{"id": "F4", "type": "dot", "title": "Compliance cost per unit",
 "source": "[E22]", "prefix": "€",
 "data_gaps": "Netherlands and Poland: regulators publish fees only in annual PDFs not yet released for 2025; request from the national competent authority.",
 "categories": ["Germany", "France", "Netherlands", "Spain", "Poland"],
 "series": [{"name": "2025", "values": [42.5, 31.0, null, 19.2, null]}]}
```

## Before the draft is done

```bash
python3 .claude/scripts/figures.py check outputs/<slug>/draft.md
python3 .claude/scripts/figures.py gaps  outputs/<slug>/draft.md
```

`check` catches malformed JSON, unknown chart types, series/category length
mismatches, missing evidence IDs, and undocumented nulls. It exits non-zero on
any of these. Fix the spec; do not delete the figure to silence the checker.

`gaps` enumerates every hole, and is what the `## Data still to obtain` section is
built from.

## Captions and titles obey the voice

A figure title is a claim and a caption is prose, so both sit under
`.claude/references/voice.md` and the author's profile: no em-dashes, no
"matters" formula, no editorial adverbs. Under the `explanatory` narration mode a
caption also carries the anchor a specialist would not need, saying what the
number is large or small against. `voice.py lint` reads figure `title`,
`subtitle`, `note` and caption lines, so a defect there fails the gate like any
other.

## Rendering happens at export, not at draft time

`report.md` keeps the specs. `/export` runs `figures.py build` with the chosen
style, which writes the images and emits a *copy* of the markdown with each block
replaced by an image and a numbered caption. The report source is never modified,
so the same report re-renders in any style, and a reviewer reading `report.md`
sees the numbers rather than a picture of them.

## What not to do

- **No chart whose title restates the axes.** If the message won't fit in a title,
  you have not decided what the figure is for.
- **No truncated value axis on a bar chart.** Bars encode length; a non-zero
  baseline lies. Lines may start where the data lives.
- **No third dimension, no gradients, no drop shadows, no pie beyond three slices.**
- **No chart the text does not discuss.** Every figure is referenced from prose,
  and the prose states the finding — a reader skipping figures must lose nothing.
- **No re-plotting a source's chart from pixels.** If you cannot get the numbers,
  cite the source's figure in prose and mark the data as unobtained.
