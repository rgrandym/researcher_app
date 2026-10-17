# Styles

One JSON file per style. Every consumer — CSS, the Word reference doc, the
PowerPoint theme, the chart renderer — reads these files, so **adding a style is
adding a file.** No code changes anywhere.

```bash
python3 .claude/scripts/style.py list                      # what exists
python3 .claude/scripts/style.py swatch verdant -o /tmp/v.png   # see the palette
python3 .claude/scripts/figures.py demo --style verdant -o /tmp/v  # see real charts
```

## The five

| Style | Reads as | Reach for it when |
|---|---|---|
| **Meridian** | Navy, serif throughout, thin rules | Board papers, policy and regulatory work; the document should look like an institution wrote it |
| **Verdant** | Deep green and sand, sans headings over a serif body | Long-form market or sustainability work someone will actually read end to end |
| **Ember** | Crimson on charcoal, all sans, high contrast | A recommendation you want acted on this week |
| **Graphite** | Cool graphite, slate charts, grey references, rules-only tables | Technical and quantitative work for readers who resent decoration |
| **Helix** | Violet and magenta, geometric sans, airy | Technology strategy and market entry, for audiences who expect current |

Plus `none` — pandoc defaults, no styling at all.

These are **originals built to sit in the same room** as the house styles of the
large consultancies: the restrained navy-serif school, the green analytical
school, the red decisive school, the monochrome analyst-note school, the modern
digital school. None copies any firm's marks, typefaces, or palette, and none
should be presented as any firm's work.

## Adding one

Copy the closest existing file, rename it, change the values. The filename stem
is the style's name on the command line.

```bash
cp .claude/styles/meridian.json .claude/styles/harbour.json
# edit; then check it loads and renders
python3 .claude/scripts/style.py show harbour
python3 .claude/scripts/figures.py demo --style harbour -o /tmp/harbour
```

`style.py show` fails loudly on a missing required key, so a broken style is
caught before a report is built on it.

## The schema

| Key | What it drives |
|---|---|
| `label`, `tagline`, `best_for`, `series_advice` | What `style list` prints, and how the export skill offers the choice |
| `fonts.heading` / `.body` / `.mono` | Font **stacks** — first one installed wins, so always end with a generic (`serif`, `sans-serif`) |
| `fonts.base_pt` | Body size; every heading, table, caption and chart label is a multiple of it |
| `fonts.heading_weight`, `.heading_tracking` | Heading weight and letter-spacing |
| `color.ink` | Headings and emphasis |
| `color.body` | Running text |
| `color.muted` | Captions, axis labels, footers |
| `color.accent` | The one colour that means "look here" |
| `color.accent_soft` | Callout and cover backgrounds |
| `color.rule` | Hairlines and borders |
| `color.mute_fill` | Fill for de-emphasised bars and lines when one series is highlighted |
| `color.surface`, `.surface_alt` | Page and panel backgrounds |
| `color.link` | Hyperlinks |
| `series[]` | Categorical chart colours, **in order**. Four minimum; eight is the practical maximum |
| `sequential[]` | Low→high ramp for heatmaps and choropleths |
| `diverging[]` | Ramp for a scale with a meaningful midpoint |
| `table.header_bg`, `.header_fg`, `.zebra`, `.border` | Table treatment; `zebra: "none"` turns banding off |
| `table.style` | `banded` (filled header) or `rules` (no fill, heavier rule under the header) |
| `chart.grid`, `.axis` | Gridline and axis colours |
| `chart.spines` | `left_bottom`, `bottom`, `left`, or `none` |
| `chart.bar_width`, `.line_width`, `.marker_size` | Mark weights |
| `chart.bar_corner_radius_px` | Optional subtle corner radius for grouped and single bars, measured in rendered pixels |
| `chart.value_labels` | Whether bars and points carry their numbers by default |
| `page.size`, `.margin_mm` | `A4`/`Letter`, and `[top, right, bottom, left]` |
| `page.cover` | Title-block treatment: `rule`, `band`, `block`, `minimal`, `off` |

Anything not listed is ignored, so annotating a style file with extra keys is safe.

## Rules for a new palette

1. **The accent must be the only loud colour.** If two colours compete, neither
   means "look here".
2. **Test the series colours at bar size, not swatch size.** Adjacent hues that
   separate cleanly in a 100px swatch merge in a 12px bar.
3. **Contrast body text against `surface` at 7:1 and muted text at 4.5:1.** The
   deliverable gets printed, photocopied, and read on a projector.
4. **Never encode meaning in hue alone.** Roughly one reader in twelve will not
   see a red/green distinction; that is why the styles ship dot, dumbbell, and
   direct-labelled charts rather than relying on the legend.
5. **Light backgrounds only.** These are print-first documents. A dark palette
   costs the reader a full toner cartridge and gains nothing.
