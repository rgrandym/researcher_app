---
name: export
description: Convert a finished report into a distributable document — Word (.docx), PDF, HTML, slides, or spreadsheet — in one of five professional styles, rendering its charts and preserving citations, tables, exhibits and the sources list. Use when the user asks to export, convert, or "give me a Word/PDF version", to produce a deliverable file, to restyle or rebrand a report, or to package it for sharing. Runs only on verified content; never the final quality gate.
disable-model-invocation: true
---

# Export

Format and style conversion, nothing else. Never fix, rewrite, or trim content
during an export — if the content is wrong, that is `/repair`'s job, and exporting
first just produces a polished wrong document.

## Two kinds of run, and the gate differs

```bash
python3 .claude/scripts/runmeta.py <run> --kind      # research | compose
```

A **research** run exports `report.md` through the full pipeline below: figures
rendered, evidence IDs resolved into citations, reference list rebuilt. A
**compose** run exports a written piece (a CV, a letter, an answer) and skips
both of those steps, because the piece carries no figure blocks and no `[E#]`
markers by design. See "Exporting a written piece" at the end of this file, and
do not run steps 1 and 2 on one.

## Gate

Export only content that has passed verification. Before converting, confirm:

```bash
python3 .claude/scripts/gate.py outputs/<slug>/report.md    # must exit 0
python3 .claude/scripts/run_check.py outputs/<slug> --ship  # must exit 0
```

1. The gate exits 0, **including zero agent artifacts**. A styled PDF is the last
   place a stray `[BLOCKING]` tag or an internal filename should surface, and an
   export is a copy: a voice defect exported is a voice defect distributed.
2. `run_check` shows every stage ran. Exporting a run that never reached
   verification produces an authoritative-looking document backed by nothing.
3. `verification.md` has no unresolved `FABRICATED` / `CONTRADICTED`.
4. `critique.md` has no unresolved `BLOCKING`.

Export `report.md`, never `draft.md` — the script defaults to `draft.md`, so name
the file explicitly. Exporting a superseded draft is a failure this pipeline has
actually produced.

If a gate fails, say so and ask before exporting. A styled `.pdf` looks
authoritative in a way Markdown does not — that is exactly the risk.

`[NEEDS DATA]` placeholders do **not** block an export. They are deliberate,
visible holes and they must survive into the deliverable intact — that is what
makes the document completable by hand. Report the count when you deliver.

## Ask for format and style — always, before converting

**Never produce a set of formats because you can.** `/export` with no format named
is an *incomplete* instruction, not permission to emit every target. Each file is
a separate artifact the user has to store, version, and keep in sync.

If the invocation does not name both, **ask once — format and style in the same
question — then stop and wait.** Use `AskUserQuestion` when the session is
interactive; multi-select on format, since wanting both `.docx` and `.pdf` is
common and legitimate.

> **Format:** `.pdf` (circulates, read-only) · `.docx` (editable, tracked changes) · `.html` (self-contained, linkable) · `.pptx` (deck — restructured, see Slides)
>
> **Style:** Meridian (navy serif, institutional) · Verdant (green, long-form) · Ember (crimson, decisive) · Graphite (monochrome, data-first) · Helix (violet, modern) · none

**Citation system** is a third choice, and it is *not* asked every time. It is
recorded in `<run>/voice.md` when the report is drafted, and the export obeys
what is written there. Ask only when that file does not name one, or when the
user asks for a different convention:

> **Citations:** house (material class in the sentence) · MLA (author-page, Works Cited) · Chicago author-date (References) · Chicago notes (superscripts and a Bibliography)

Changing it is one command and no rewrite, the same as restyling. Doctrine:
`.claude/references/citation-style.md`.

Run `python3 .claude/scripts/style.py list` to read the current set and their
one-line descriptions to the user — do not recite this file's list, since styles
are added by dropping in a JSON and this file will go stale.

If the user cannot choose, show them rather than describing:

```bash
python3 .claude/scripts/style.py swatch <style> -o /tmp/<style>.png       # the palette
python3 .claude/scripts/figures.py demo --style <style> -o /tmp/<style>   # real charts
```

**Proceed without asking only when it is already determined:** the user named it;
an earlier turn in this session settled it; or the session is non-interactive, in
which case default to **`.docx` with style `none`** — the most broadly openable,
least presumptuous target — and say plainly that you defaulted.

A follow-up like "also PDF" extends the set; it does not retroactively license the
rest. Restyling is cheap: the same `report.md` re-renders in any style, so
"actually, try Ember" costs one command, not a rewrite.

## The pipeline

Every export is the same three steps. Do them in this order — figures must be
rendered before pandoc runs, or the ```figure blocks ship as raw JSON code blocks.

```bash
run=outputs/<slug>; S=meridian; out=$run/export/$S
mkdir -p "$out"

# 1. render the charts and produce styled markdown (report.md is never modified)
python3 .claude/scripts/figures.py build "$run/report.md" \
        --style $S --outdir "$run/figures/$S" -o "$out/_styled.md" --rel-from "$out"

# 2. render [E#] into reader-facing citations and rebuild the reference list.
#    --system defaults to house; use what <run>/voice.md records for this report.
python3 .claude/scripts/references.py render "$out/_styled.md" \
        --run $run -o "$out/report.md" --citemap "$out/citations.json" \
        --system house      # or mla · chicago-ad · chicago-notes

# 3. generate the style assets for the targets you need
python3 .claude/scripts/style.py css      $S --cover -o "$out/style.css"
python3 .claude/scripts/style.py docx-ref $S -o "$out/reference.docx"
python3 .claude/scripts/style.py pptx-ref $S -o "$out/reference.pptx"
```

Step 2 is what makes the deliverable readable as a scientific document: `[E205]`
becomes `(Halden Labs, product datasheet, 2026)` and `## Sources` becomes a formatted
reference list stating the class of every source. The list is headed
`## References`, `## Works Cited` or `## Bibliography` depending on the system,
and under `chicago-notes` the citations become superscript markers with the notes
carried as markdown footnotes, which pandoc renders as endnotes. Doctrine and the
rationale are in `.claude/references/citation-style.md`.

**Run `references.py audit <run>` first.** It reports sources whose material
type could not be determined, and those print as `[source type unclassified]`
in the deliverable. Zero unclassified is the target, and the fix is to set
`type` on the offending evidence rows, not to loosen the heuristics. It also
counts sources with no author and no date, which cite as corporate and `n.d.`
respectively.

To ship a deliverable that keeps the raw `[E#]` markers instead — for an
internal reader working against the ledger — skip step 2 and pandoc `_styled.md`
directly. Say which form you produced.

Then convert. Verified working in this workspace (pandoc 3.8.3, matplotlib 3.10):

| Target | Command |
|---|---|
| `.html` | `pandoc "$out/report.md" -s --toc --section-divs --embed-resources -c "$out/style.css" -o "$out/report.html"` |
| **PDF** | weasyprint, from the HTML — see below |
| `.docx` | `pandoc "$out/report.md" --reference-doc="$out/reference.docx" -o "$out/report.docx"` |
| `.pptx` | `pandoc "$out/report.md" -t pptx --reference-doc="$out/reference.pptx" -o "$out/deck.pptx"` |
| `.rtf` | `pandoc "$out/report.md" -s -o "$out/report.rtf"` |
| `.xlsx` | `openpyxl` — **not installed** (`pip install openpyxl`) |

`--section-divs` is not optional for HTML and PDF: the stylesheet targets
`#sources` to set the hanging indent on the source list, and without it the
sources render as ordinary paragraphs.

### PDF — the working recipe

weasyprint 69.0 and pango are installed. weasyprint **fails to import unless
Homebrew's libs are on the loader path**, so the env var is not optional. Pass
`base_url` or the embedded figures resolve to nothing and you get a PDF with
silent blank gaps where the exhibits were.

```bash
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH
python3 -c "
import weasyprint
weasyprint.HTML(filename='$out/report.html', base_url='$out/').write_pdf('$out/report.pdf')"
```

The style's CSS already carries `@page` size and margins, running footers, table
`table-layout: fixed` with wrapping, and `break-inside: avoid` on rows and
figures. A table still too wide for portrait gets `<div class="wide">` around it —
the stylesheet gives that its own landscape page.

### typst is installed but must not be used for these reports

`pandoc --pdf-engine=typst` **silently truncates wide tables.** On a 7-column
matrix it dropped entire trailing rows and 8 citations while producing a
clean-looking 18-page document with no warning. Changing papersize, `flipped`, and
font size all reproduced the identical loss.

Never silently substitute one format for another. If a target is unavailable, say
so, name the one-line install, and offer the alternative.

## Preserving citations and exhibits

- Citations are rendered by `references.py`, never by hand, and evidence IDs are
  never renumbered. Each reference entry ends with the IDs drawn from it, so the
  trail from a rendered citation back to `evidence.jsonl` survives into the PDF.
- The material type is part of the citation, in text and in the list. A vendor
  datasheet, a preprint, a conference abstract and a peer-reviewed article carry
  different weight, and the label must not flatter: "marketing material" does
  not become "technical note".
- The `## References` section always ships with the document. A cited document
  without its reference list is not exportable.
- The `## Data still to obtain` section ships too. It is the most actionable part
  of a partial report and the first thing a well-meaning conversion drops.
- Exhibit numbers are assigned at build time in document order. Never edit them by
  hand; re-run `figures.py build`.
- Include the confidence statement. It travels with the document; it is not a
  chat-only artifact.
- If the user wants real footnotes: convert `[E#]` to Pandoc footnote syntax
  (`[^E7]` plus definitions) and verify the count matches before and after.

## Quality check after conversion — every format, every time

**Conversion silently drops things, and the damaged file looks fine.** A renderer
that clips a table does not warn, does not error, and produces a document that
reads as complete.

```bash
python3 .claude/scripts/check_export.py --citemap "$out/citations.json" \
        "$out/report.md" "$out/report.pdf" "$out/report.docx" "$out/report.html"
```

It compares the **set** of citations, the exhibit count, and the placeholder
count in each artifact against the styled source, and exits non-zero on any loss.

**`--citemap` is required once references have been rendered.** Without it the
checker looks for `[E#]` markers, finds none in either source or output, and
passes vacuously — the worst kind of green. With it, it looks for each rendered
citation string instead. Omit the flag only when you skipped step 2.

Compare sets, not totals: pandoc writes an image caption twice — once as alt text,
once as the visible caption — so raw `[E#]` totals legitimately differ between
formats while the set of cited IDs must not. Never infer that because one format
survived, another did.

Two traps when diagnosing a mismatch:

- **Check your search strings against the source before believing one is missing.**
  Grepping for a phrase you misremembered produces a false alarm.
- **`pdftotext` wraps table cells across columns**, so a multi-word phrase can
  extract as two lines and appear absent when it is present. Test single tokens
  and count rows, not phrases.
- **Text inside a chart is pixels** and is invisible to every text extractor. That
  is why titles live in captions rather than baked into the image — if a
  figure's message is only in the PNG, it did not survive.

If a format proves lossy, **change the renderer, not the report.** Trimming a
table so it fits a broken engine corrupts the deliverable to flatter the tool.

## Styling beyond the five

The styles are data: `.claude/styles/*.json`. To add one, copy the closest and
edit the values — see `.claude/styles/README.md`. No code changes, and every
format picks it up. If the user supplies their own corporate template instead,
`--reference-doc=their.docx` overrides the generated one entirely.

Do not invent logos, cover art, or headers beyond what the chosen style defines.
Choosing a style is permission to style; it is not permission to brand.

## Slides

Markdown built for reading makes bad slides. When asked for a deck, restructure
explicitly: one claim per slide as the heading, ≤5 supporting lines, one exhibit
per slide where it carries the point, evidence IDs retained, and a final sources
slide. Set `"chart_title": true` on figures headed for a deck so each chart states
its own message when it appears without surrounding prose. State that you
restructured rather than dumping the report into `-t pptx`.

## Exporting a written piece

A compose run (`runmeta.py <run> --kind` prints `compose`) exports its master
straight from Markdown. There are no charts to render and no citations to
resolve, so steps 1 and 2 of the pipeline above do not apply.

```bash
run=outputs/<slug>
doc=$(python3 .claude/scripts/runmeta.py $run --masters | head -1)
name=$(basename $doc .md); S=graphite; out=$run/export/$S
mkdir -p "$out" && cp "$doc" "$out/$name.md"

python3 .claude/scripts/style.py css      $S -o "$out/style.css"     # no --cover
python3 .claude/scripts/style.py docx-ref $S -o "$out/reference.docx"

pandoc "$out/$name.md" -s --section-divs --embed-resources \
       -c "$out/style.css" -o "$out/$name.html"
pandoc "$out/$name.md" --reference-doc="$out/reference.docx" -o "$out/$name.docx"

export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH
python3 -c "
import weasyprint
weasyprint.HTML(filename='$out/$name.html', base_url='$out/').write_pdf('$out/$name.pdf')"

python3 .claude/scripts/check_export.py "$out/$name.md" \
        "$out/$name.pdf" "$out/$name.docx" "$out/$name.html"
```

Four rules specific to this branch:

- **No `--cover` and no `--toc`.** A cover page on a two-page letter and a table
  of contents on a CV both read as a document produced by a machine.
- **The word count is the whole loss check.** With no citations and no exhibits
  to compare, `check_export.py` falls back to counting words, and that is what
  catches a CV whose second page was clipped. Read the number it prints.
- **A CV usually wants `.docx`.** Applicant tracking systems parse it and
  recruiters edit it; a multi-column PDF defeats both. Offer the PDF as the
  copy for a human reader, and say why.
- **Markdown needs no export.** The master already is Markdown. Copying it into
  `export/` is for keeping the set together, and the author can be handed the
  master's path instead.

The gate for a compose run is `run_check.py <run> --ship` (prompt, context,
piece, independent review) plus `gate.py` on the master. `verification.md` is
required only where the piece asserts facts about the world.

## Where files go

`outputs/<slug>/export/<style>/` unless the user names a path. One directory per
style keeps two stylings of the same report from overwriting each other. Report
the absolute path, the format, the style, and the placeholder count on completion.
