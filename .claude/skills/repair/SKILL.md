---
name: repair
description: Apply verification and critique findings to a draft — surgical edits that fix each defect, downgrade overstated claims, remove fabricated citations, and re-run the audit, then report what was fixed, what was cut, and what stays open. Use after /verify or /critique, when the user asks to fix, address, incorporate, or act on review findings, or to revise a draft against a list of issues.
disable-model-invocation: true
---

# Repair

**Which document.** When the run has more than one master (an audit and a revised
document), act on the one the request names, or ask; then read it wherever this
skill says `report.md`. A revised document keeps its own form and citations.
Doctrine: `.claude/references/masters.md`.

Fix the findings. Do not rewrite the report.

When `/repair` is launched from **Apply feedback to article**, read the named
`critique*.md` file, the linked `repair-feedback-*.json`, and the current master.
Apply only the scope the author selected and treat their answers and notes as
editorial decisions. Do not guess the answer to an unresolved question: ask the
author through the app's question tool, then continue when they answer. The
button starts a repair round;
it does not authorise a broad rewrite or a change to an approved final section.
In the feedback file, `all` includes minor findings, `material` includes only
blocking and material findings, and `specified` follows the author's written
selection. Findings outside the selected scope are logged as declined by scope,
with no change to the article.
Before editing, check that each quoted target still exists. A finding whose
target has changed since the critique is `open (stale target)` until it is
reassessed; never apply its suggested fix to a different passage by guesswork.

Before touching a saved `report.md`, run
`python3 app/backend/edit_state.py inspect <run>/report.md`. If the author save
is still pending, finish `/user-edits` first. Then list final sections with
`python3 .claude/scripts/section_guard.py locks <run>/report.md`. A final section
stays byte-identical even when a finding recommends changing it. Record that
finding as open with the exact proposed edit, and ask the author to **Reopen
section** if they want it applied. Never unlock or refresh a final lock yourself.

Inside `/research-pipeline` this skill runs in a `report-writer` agent. Typed on
its own against a finished report (one finding, one section), it runs here: read
the findings named and the sections they point to, not the whole document
(`python3 .claude/scripts/section_map.py <run> --find E42`, then `--show
"<heading>"`).

## Order

1. **BLOCKING / FABRICATED / CONTRADICTED first.** These change the answer. If the top-line answer moves, fix `## Answer` and the title before anything else — a repaired body under a stale headline is worse than the original.
2. Material findings (overstatement, missing qualifiers, **unattributed** single-sourcing).
3. Minor findings, only if the above are done.

## Edits are surgical

Use Edit, not Write. One finding, one edit, matched to the exact text the finding names. Rewriting a whole section to fix one sentence discards reviewed prose and re-introduces defects the reviewers already cleared.

Declare the sections the fixes will touch before editing. For a report with a
section guard baseline, run `section_guard.py check` with those sections as
`--allow` before closing the round. The guard's final locks still apply inside
the allowed scope.

## Fixing by verdict

| Verdict | Repair |
|---|---|
| `FABRICATED` | Delete the claim **and its citation**. Re-source only if load-bearing. Never swap in a plausible substitute URL. |
| `CONTRADICTED` | Replace with the better-sourced version, new `[E#]`, and note the disagreement if it's live. |
| `PARTIAL` | Restore the missing qualifier verbatim from the source. This is usually a five-word edit, not a rewrite. |
| `WEAK` / `CIRCULAR` | **Attribute, don't dilute.** Name the source in the sentence ("one vendor reports…", "in the only located study…"); collapse circular citations to their single origin. Demote out of the load-bearing path only if the grade cannot carry the conclusion. See `.claude/references/attribution.md`. |
| `UNSUPPORTED` | Cut it, or mark `[UNVERIFIED]` and move it out of the conclusion. |
| `STALE` | Update the figure and its period. Check whether anything downstream depended on the old one. |

**Never repair by softening into vagueness.** Turning a wrong number into "significant growth" hides the error instead of fixing it.

## Critique findings

Each names a Fix — implement that, not your own alternative. If the proposed fix is wrong or infeasible, say so explicitly in the summary rather than silently doing something else.

If a fix requires facts you don't have, spawn one `research-scout` with a tight brief. Do not fill the gap from memory.

## Exhibits and placeholders

A repaired number is repaired **everywhere**, including inside figure specs. After changing any figure, grep the report for the old value and for the claim's evidence IDs — a corrected number that survives in one chart is exactly the defect this pipeline exists to catch.

A `FABRICATED` or `CONTRADICTED` number in a chart does not mean deleting the chart — it becomes a visible hole. Rebuild `## Data still to obtain` from `python3 .claude/scripts/figures.py gaps outputs/<slug>/report.md` after any repair that adds or closes one. Doctrine: `.claude/references/gaps.md`.

## Promote the draft, once

On the **first** repair pass, after the fixes land: `cp <run>/draft.md <run>/report.md`.
From then on `report.md` is the master and every edit — this pass and every later
one — is made to it in place. `draft.md` is never read again. Auditing or
exporting a superseded file is a failure this pipeline has actually produced.

Then baseline it, so any later work — a further round, or an edit the user makes
by hand — can prove what it did and did not touch:

```bash
python3 .claude/scripts/section_guard.py snapshot <run>/report.md
python3 .claude/scripts/run_check.py <run> --ship
```

`run_check` names any stage that never ran. A report has shipped from this
workspace with its coverage table still holding the empty scaffold, which meant
the gap hunt and the coverage audit had not happened and nothing said so.

## Close the loop

1. Clear every hard failure the gate returned. Zero agent artifacts is a hard gate, not a warning.
2. Re-check that every finding is now `fixed`, `won't fix (reason)`, or `open (needs input)`. No finding disappears without a disposition.
3. Re-read `report/references/anti-slop.md` and strip anything the edits reintroduced. Repairs add hedges; hedges accumulate.
4. Re-read `report/references/register.md`. Surgical edits drift toward chat voice — "it should be noted that", "as mentioned above" — and a document repaired ten times reads like ten documents unless this pass runs.
4a. Repair is the stage where voice regresses hardest: a fix written against a verification finding is written in the finding's vocabulary, not the report's, and em-dashes reappear one surgical edit at a time. The gate catches those on each write. Comply with `<run>/voice.md` for the narration mode; if a repaired passage now explains more or less than the sections around it, the mode has drifted and the passage is rewritten, not left.
4b. Read the `ECHO`, `ECHO-NEAR`, `OPENER` and `DICTION` lines the same command prints, for the paragraphs you touched. A repair reuses the vocabulary of the finding it answers, so the repaired sentence tends to echo the sentence beside it; that is the defect this pass catches. Fix a real echo by rebuilding the sentence, not by reaching for a synonym that shifts the claim. Doctrine: `.claude/references/diction.md`.
5. Confirm the repair left no trace of itself. A fix that cites the finding that prompted it ("corrected following verification") is the pipeline leaking into the deliverable — state the fact, not its history.

## Report back

Write the disposition of every finding to `<run>/repair-log.md`, and summarize in chat:

```
FIXED     n  (blocking: a, material: b, minor: c)
WON'T FIX n  <finding — reason>
OPEN      n  <finding — what's needed>
ANSWER CHANGED: yes/no — <how>
```

Be honest about `OPEN`. A finding marked fixed that wasn't is the one defect this whole pipeline cannot catch.
