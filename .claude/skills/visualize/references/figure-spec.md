# Figure spec reference

One JSON object per ```figure block. Run
`python3 .claude/scripts/figures.py types` for the live type list.

## Always required

| Field | |
|---|---|
| `id` | `F1`, `F2`, … unique in the document. Used by `[[F2]]` cross-references |
| `type` | one of the types below |
| `title` | the **message**, as a sentence. Becomes the figure caption |
| `source` | must contain at least one `[E#]` |

## Common optional fields

| Field | Effect |
|---|---|
| `subtitle` | Basis line drawn inside the chart: unit, period, population |
| `note` | Extra caption text — derivations, exclusions, definitions |
| `data_gaps` | **Required if any value is `null`.** What is missing and where to get it |
| `unit` / `prefix` | Appended / prepended to every value label (`"%"`, `"k"`, `"€"`, `"$"`) |
| `decimals` | Force decimal places. Default: none if the value is a whole number |
| `x_label`, `y_label` | Axis labels. Usually unnecessary if `subtitle` says the unit |
| `value_labels` | `false` to suppress numbers on marks (dense charts) |
| `legend` | `false` to suppress the legend |
| `highlight` | Category name(s) — or series name(s) for `line`/`slope` — to keep in the accent while everything else greys back |
| `sort` | `"desc"` / `"asc"` for single-series category charts |
| `baseline` | Draw a dashed reference line at this value |
| `annotate` | `[{"category": "Spain", "text": "rule in force", "y": 112}]` |
| `size` | `[width, height]` in inches. Default width 6.5 |
| `font_scale` | Scale all chart text together; check effective point size at final page width |
| `tick_every` | Show every nth category tick on crowded time axes |
| `wide` | `true` → 9in wide; pair with a `.wide` class for a landscape page |
| `chart_title` | `true` bakes the title into the image too (for slides). Default `false` — the title lives in the caption as real text |

## Page-size check

Render and inspect each chart at the width it will occupy in the report.
Keep axis ticks, legend, and annotations comfortably readable, normally at least
8 pt at final print size. Name the unit on the axis or in the subtitle. Use
enough ticks to orient the reader without overlapping labels. One-series charts
usually need no legend; multi-series charts need a clear legend or direct labels.
Captions and prose call the result a Figure and use `[[F#]]` cross-references.

## Types and their data

**Category charts** — need `categories: [...]` and
`series: [{"name": …, "values": [...]}]`, one value per category, `null` where
unobtained.

| Type | Use for |
|---|---|
| `bar` | 2–4 groups compared across a handful of categories |
| `hbar` | Same, when category names are long |
| `stacked_bar` / `stacked_hbar` | Composition; `total_labels` and `segment_labels` default true |
| `line` | Trend over time. Labels series at the line end when ≤5 series |
| `area` | Trend with magnitude; `stacked` defaults true |
| `dot` | Ranked comparison. The best default for "who is biggest" |
| `dumbbell` | Exactly two series: before/after, us/them, min/max |
| `slope` | Exactly two categories (the two periods), one line per entity |

**Other shapes**

| Type | Data |
|---|---|
| `scatter` | `series: [{"name": …, "points": [[x, y], …], "labels": [...]}]` |
| `waterfall` | `steps: [{"label": …, "value": …, "type": "start"\|"delta"\|"total"}]` |
| `heatmap` | `rows`, `columns`, `values` (row-major); `scale: "sequential"\|"diverging"`, `cell_labels` |
| `donut` | `categories`, `values`, optional `center`. Three slices maximum — above that use `dot` |
| `stat` | `stats: [{"value": …, "label": …, "delta": …}]`. `value: null` renders a tile to fill in by hand |

## Colour assignment

Series are coloured **by name, once per document**. "2024" is the same colour in
every figure or table that mentions it. That consistency is free and is the single
cheapest thing you can do for a reader comparing two charts — so name your series
identically across figures when they mean the same thing.

`highlight` overrides this: named series or categories take the accent, everything
else takes `mute_fill`. Use it whenever the figure or table has a subject rather than a
set — one highlighted bar among greys communicates faster than eight colours.

## Worked examples

```json
{"id": "F1", "type": "stat", "title": "Where the market stands",
 "source": "[E1][E2]",
 "stats": [{"value": "38%", "label": "share held by the top three", "delta": "+6pp since 2023"},
           {"value": "1.9M", "label": "units shipped, TTM to Q3 2025"},
           {"value": null,   "label": "median contract length"}],
 "data_gaps": "Median contract length: only reported in the paid IDC tracker; obtain from a subscriber."}
```

```json
{"id": "F5", "type": "waterfall",
 "title": "Scale and chemistry drove the cost down; compliance gave a third of it back",
 "source": "[E19][E31]", "prefix": "$",
 "steps": [{"label": "2023 cost", "value": 98, "type": "start"},
           {"label": "Cell chemistry", "value": -14},
           {"label": "Scale", "value": -19},
           {"label": "Compliance", "value": 8},
           {"label": "2025 cost", "value": 71, "type": "total"}]}
```

```json
{"id": "F7", "type": "heatmap", "title": "Rule coverage is thinnest in storage everywhere",
 "source": "[E4][E5]", "scale": "sequential", "decimals": 0,
 "rows": ["Germany", "France", "Spain", "Poland"],
 "columns": ["Portable", "Industrial", "EV", "Storage"],
 "values": [[3, 3, 2, 1], [3, 2, 2, 1], [2, 2, 1, 0], [1, 1, 1, 0]],
 "note": "0 = no rule, 3 = binding rule in force."}
```

## Adding a chart type

Write `_draw_<name>(ax, spec, ctx)` in `.claude/scripts/figures.py`, add the name
to `TYPES`, and give it a one-line docstring — `figures.py types` prints it. The
`ctx` object carries the resolved fonts, the palette, and `ctx.color_for(name, i)`
for document-consistent series colours. Add validation for its required fields in
`validate()` so a malformed spec fails before it renders.
