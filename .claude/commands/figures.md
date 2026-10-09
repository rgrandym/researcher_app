---
description: Improve a report's charts, figures and plots, as the author directs
argument-hint: "[run] [F3 | all] <what to improve>"
disable-model-invocation: true
---

Improve the figures in a report, as the author asks: $ARGUMENTS

The author may name a run, one or more exhibits (`F3`, `F2 F5`), or `all`, and says
what is wrong or what they want: "F4 is unreadable", "make the bars horizontal",
"the colours are too similar", "add the 2025 value as an annotation". If no run is
named and the conversation is inside a project, it is that project's run. If no
exhibit is named, ask which, unless the request plainly covers them all.

## Read first

1. `.claude/skills/visualize/SKILL.md` and its `references/figure-spec.md`: the
   spec fields, the chart types, and the exhibit conventions. Load the `dataviz`
   skill for design judgment (form, colour, labelling, emphasis).
2. The figures themselves, not the report: `grep -n '^```figure' <master>` lists
   them, and `python3 .claude/scripts/section_map.py <run> --find F3` names the
   section that refers to one. Read only the blocks in scope and the sentence that
   cites each.

## What may change, and what may not

A figure here is a claim with its data in the source. **Presentation is yours to
change; the claim is not.**

- **Free**: chart type, orientation, sort order, which category is highlighted,
  labels, annotations, axis range (never truncated so as to exaggerate), size,
  legend, value labels, decimals, subtitle wording, splitting one crowded chart into
  two.
- **Only with every number traced**: adding a value, a series or an annotation that
  carries a figure. It must come from a row in `evidence.jsonl` with its `[E#]` in
  `source`; a number with no row is not drawn. If the data is not in the ledger,
  say what is missing and offer `/expand` to get it.
- **Never silently**: the `title`, which is the exhibit's message, and the data
  values. If the author's request changes what the figure claims, make the change
  and list it at the end as needing `/verify`, because a changed message is a new
  claim.
- A `null` value stays a visible gap with its `data_gaps` note. Never interpolate
  or drop it to make a chart look complete.

Edit the master (`report.md`, or the piece named in `.run.json`) in place, one
figure block at a time. Change the prose only where a sentence describes the chart
in a way the edit made untrue ("the bars show…" after a switch to dots).

## Check, render, look

```bash
python3 .claude/scripts/figures.py check <master>
python3 .claude/scripts/figures.py build <master> --style <style> \
        --outdir <run>/figures/preview -o <run>/figures/preview/report.md
```

`<style>` is the one the run exports in (the folder name under `<run>/export/`),
or `meridian` if it has none. Then look at each changed figure's PNG in
`figures/preview/`. **Look at each figure at most twice**: once after the change
and once after any fix it needed. Every image opened stays in the conversation, and
re-opening one chart to nudge it is the most expensive habit this command can have.
Settle the spec from the reference, then render to confirm.

The gate runs after each write to the master; clear what it reports.

## Report back

One line per figure: what changed and why, in the author's terms. Then, if any:

- **Needs /verify**: figures whose message or numbers changed.
- **Could not do**: requests the data does not support, with what would.

Never paste a figure block or an image into the reply; the author sees them in the
report's HTML view.
