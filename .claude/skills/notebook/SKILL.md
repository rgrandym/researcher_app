---
name: notebook
description: Build Jupyter analysis notebooks that document and reproduce a report's figures and tables, written as a professional data analyst would, with sources, data acquisition, cleaning, methodology, all code, and a reconciliation against the published numbers. Runs only when the author types /notebook ("/notebook figure 1 and table 1 together"); no other stage makes notebooks.
argument-hint: "[run] <Figure 1 | T2 | all> [together | each]"
disable-model-invocation: true
---

# Notebook

A notebook is the working behind a figure or table: where each number came from,
what was done to it, and code that rebuilds the item from that work. A reader
who doubts a chart opens its notebook, runs it, and either gets the published
numbers or sees exactly where they diverge. A notebook that only re-plots the
report's values proves nothing, so the work here is tracing each item back to
its raw data and writing down every step.

## When notebooks are made

**Only when the author types `/notebook`**, for the items they name:
`/notebook figure 1 and table 1 together`, `/notebook all`. No other stage makes
one: not `/research`, `/report`, `/verify`, `/critique`, `/repair`, `/expand`,
`/user-edits`, and not `/export` or a request for the final report. Reports go
through several revisions before approval, and the author decides when the
analysis is settled enough to document. A request in plain words without the
command is answered by naming `/notebook`.

## Scope

"Together" means one notebook for the named items; otherwise one per item. When
the run is not named, it is the run the conversation is in. Resolve what the
author typed against the report's printed numbers, which follow document order:

```bash
python3 .claude/scripts/notebook.py list <run>
```

`list` prints each item as the reader sees it (Figure 1, Table 2), its spec ID,
its evidence count, any notebook that already covers it and whether that
notebook is **stale** (the report changed the item since). It also lists the
machine-readable files the run holds, which are the first place raw data is
found. An item that already has a current notebook is not rebuilt unless asked.

Notebooks read the saved `report.md`. When the author may still be editing,
run `saved_check.py <run>` first and stop if it exits 1.

## The steps

1. **Scaffold.** `notebook.py scaffold <run> "Figure 1" T2` writes one notebook;
   add `--each` for one per item, `--name` to choose the file name. Files go in
   `<run>/notebooks/` with `data/raw/`, `data/processed/`, `output/` and a pinned
   `requirements.txt`. The scaffold already holds the sources table from the
   evidence ledger, the published values as data, standalone matplotlib code in
   the report's palette, the reconciliation cell, and the source excerpts.
   Every cell that needs judgement is marked `ANALYST-TODO`.
2. **Trace the lineage of each item.** Read the item's evidence rows, its spec
   `note` (derivations the report states), the run's data files, and the notes
   that produced them. Establish for each input whether it exists as
   machine-readable data (a CSV or API the research downloaded) or only as
   numbers in a document. Grep before reading; never load a whole notes folder.
3. **Write the notebook** to the practices below, filling every `ANALYST-TODO`
   and deleting the marker. Edit cells with `NotebookEdit`.
4. **Run it**: `notebook.py run <nb>`. Repair until it runs top to bottom and the
   reconciliation passes. With `nbclient` and `ipykernel` installed it saves the
   outputs into the notebook; without them it runs the code as a script, and
   the delivery says the notebook ships without outputs.
5. **Check it**: `notebook.py check <nb>`. It fails on an unfinished cell, a
   missing section, a reference with no ledger row, a link the research never
   fetched, pipeline vocabulary, a voice violation, or a cell that errored.
6. **Independent review.** Spawn `notebook-reviewer` on the notebook. The thread
   that wrote it never reviews it. Repair what it reports, then rerun steps 4–5.
7. **Index**: `notebook.py index <run>` writes `notebooks/README.md`.

For more than two notebooks, write them in parallel: one `notebook-analyst`
subagent per notebook, spawned in one message, each given the run, the
notebook path and the items. Review each with its own `notebook-reviewer`.

## How a professional analyst writes the notebook

**Structure.** The ten sections the scaffold lays down, in order: Summary,
Environment, Data sources, Data acquisition, Cleaning and validation,
Methodology, Analysis, Reconciliation with the report, Limitations,
Reproducibility, then the source excerpts. One question per notebook section;
a markdown cell before each code cell says what the code does and why.

**Data from source, not from the report.** Download machine-readable data from
the URL the research fetched it from, into `data/raw/`, and print its SHA-256.
Where the research already holds a copy (in `external_data/` or `notes/`), copy
it into `data/raw/` so the notebook runs offline, and add a `REFRESH = False`
flag that downloads afresh when set. Raw files are never modified in place.
Transcribing values from a document is legitimate when no machine-readable form
exists: build the table in code with a column naming the page, table or passage
each value came from, and say in section 4 that it was transcribed. Copying the
report's own values into `*_data` is never the acquisition.

**The folder stands on its own.** `notebooks/` is handed to people who never
see the rest of the run, so code reads nothing outside it: held copies go into
`data/raw/` under the source's own file name, never loaded from `../notes/` or
`../external_data/`. `check` rejects any `../` path.

**Every statement about the data is shown by a cell.** If the prose says two
sources agree, that a rounding choice moves one value, or that a series fell by
half, a cell computes it and, where it is a fact the reader relies on, asserts
it. A claim in markdown that no output demonstrates is the notebook's version of
an uncited sentence.

**Every source used is listed.** A source cited anywhere in the notebook is in
the section 3 table, with *notebook only* when the report does not cite it,
and has its excerpt in the appendix. `check` enforces the table.

**Every derived number is computed in code.** Indices, averages, growth rates,
shares, sums, unit conversions and period selection are written as code with
the formula stated in section 6. A number typed into the notebook that could
have been computed is a defect.

**Cleaning is explicit and checked.** One step per cell or clearly commented
block: rename, parse types and dates, harmonise units, filter period and
population, handle missing, revised or provisional values, deduplicate. After
cleaning, `profile()` the table and `assert` the invariants (date order,
ranges, no duplicate keys, expected row counts). Save the clean table to
`data/processed/`.

**Code a colleague can maintain.** Imports and constants at the top; no hidden
state, so *Restart and Run All* is the only supported way to run it; functions
for anything done twice; tidy (long) tables; `.head()` rather than printing
whole frames; units in column names (`value_gbp_m`, `index_feb2020_100`);
deterministic results (fix a seed if anything is random). No magic numbers
without a comment saying where they come from.

**The reconciliation is the point.** Section 8 asserts that each reproduced
value equals the published one within rounding. Never edit the `*_published`
cells to make it pass; those cells come from the report. When the data does not
reproduce the report, the notebook is right to fail: stop, tell the author which
values differ and by how much, and recommend `/verify` for those claims. Ship
the notebook only once the author has decided, either correcting the report and
running `notebook.py refresh <nb>`, or keeping the report and stating the
discrepancy in section 9, with the assertion relaxed to that named value only.

**Gaps stay gaps.** A value the report marks as not obtained stays `NaN` in the
notebook and is listed in section 9 with what is missing and where to get it.
Never fill it to complete a chart.

**Prose.** The narrative is prose a reader sees, so it follows
`.claude/voice/profile.md` and the house rules, and carries no pipeline
vocabulary: no internal file names, no stages, no subagents. Sources are cited
by their reference IDs, which match the report's reference list. Write as the
analyst who did the work, plainly: "The index is rebased to February 2020",
never "I searched". Do not add claims the report does not make; a notebook
explains the evidence, it does not extend it.

**Links.** Rule 1 holds: every URL in the notebook is one the research fetched
or the author supplied. `check` enforces it against the ledger and the run's
notes. A data endpoint found during this work is fetched and recorded in a note
before it appears in the notebook.

## When the report changes later

`notebook.py list` marks a notebook stale when its item changed. Run
`notebook.py refresh <nb>`: it rewrites only the published-values cells from the
current report and keeps the analysis. Rerun; the reconciliation names every
number that moved, and the derivation is updated to match the new evidence.

## Report back

One line per notebook: its path, the items it reproduces, how each input was
obtained (downloaded, held copy, transcribed), and whether outputs are saved.
Then, if any: items that did not reproduce, with the values, and anything that
could not be done.
