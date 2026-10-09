---
name: research-pipeline
description: Run the full research-to-report pipeline end to end — brief, parallel scout research, draft, adversarial verification, red-team critique, repair, and final report with a confidence statement. Use for any substantial deliverable ("write me a report on…", "do a deep dive", "research X and write it up") where the output must be citable and defensible. Orchestrates the research, report, verify, critique, and repair skills with the correct quality gates.
disable-model-invocation: true
---

# Research pipeline

The loop is **investigate → draft → independent review → fix and refine**, and it
closes before anything reaches the user. Nothing ships on a first draft.

Full run: **brief → gap hunt → research → coverage audit → draft → verify →
critique → repair → ship**, then `export` and `expand` on request.

You are the orchestrator. Your context holds the brief, the digests, and the
findings — never raw sources.

**Load each stage by reading its file**: `.claude/skills/<stage>/SKILL.md` for
`research`, `report`, `verify`, `critique`, `repair` and `export`. The stage
skills run only when the author types them, so the Skill tool cannot load them;
reading the file is the one route, inside this pipeline and inside `expand`. Read
a stage's file when that stage starts, not all of them up front.

**You never hold the document.** Drafting (stage 5) and repair (stage 8) run in a
`report-writer` agent: brief it with `MODE`, `RUN`, and for repair the ledgers to
act on. It reads the stage skill itself, writes the file, runs the gate, and hands
back a short summary. The reviewers read the file from disk. A draft or a repair
pasted into this thread is re-read on every later call for the rest of the run,
and that re-reading was most of what a run used to cost. Read a section of the
document only to settle a specific question, through
`python3 .claude/scripts/section_map.py <run> --show "<heading>"`, never whole.

When the writer returns `NEEDS SCOUT`, send the scouts, then call the writer again
with the new evidence IDs. When it returns `NEEDS VOICE`, ask the author the
narration question (`.claude/references/voice.md`) and record it in
`<run>/voice.md` first.

**Review is done by subagents, not by you.** The thread that wrote the draft
cannot review it: it already believes the argument, and it is the source of any
bias in it. `source-verifier` re-fetches the sources; `report-critic` attacks the
reasoning. Both work in isolated contexts and both are adversarial by design.

## Stages

| # | Stage | Skill | Gate to pass |
|---|---|---|---|
| 0 | Supplied sources | `research` | `external_index.py scan` clean, or its unread files assigned to a scout |
| 1 | Brief | `research` | Sub-questions orthogonal; scope agreed; narration mode recorded in `<run>/voice.md` |
| 2 | Gap hunt | `research` | `coverage.md` opened; dimensions the brief missed are assigned or logged |
| 3 | Gather | `research` | Every sub-question has ≥2 independent sources, or is logged as a classified gap |
| 4 | Coverage audit | `research` | Every sub-question and swept dimension has a status; `THIN` load-bearing claims re-scouted |
| 5 | Draft | `report`, in `report-writer` | Every fact carries `[E#]`; `gate.py` exits 0; every blocked source registered with `wanted.py` |
| 6 | Verify | `verify` | Zero `FABRICATED`/`CONTRADICTED` unresolved |
| 7 | Critique | `critique` | Zero `BLOCKING` unresolved |
| 8 | Repair | `repair`, in `report-writer` | Every finding has a disposition; `draft.md` promoted to `report.md` |
| 9 | Ship | — | `gate.py` exits 0 with **0 agent artifacts**; `run_check.py --ship` exits 0; confidence statement written; every `coverage.md` gap visible in the report; `wanted.py build` has written the author's list |
| 10 | Export *(on request)* | `export` | Gates 6–8 clean; format and style chosen by the user |
| 11 | Expand *(on request)* | `expand` | New evidence reconciled, not appended; changed claims re-verified |

**Gates are not advisory.** A stage that fails its gate loops back once, with a narrower brief. Failing twice is reported to the user as a limitation, not papered over.

Two of them are mechanical and cost nothing to run:

```bash
python3 .claude/scripts/gate.py <run>/report.md       # voice, citations, figures
python3 .claude/scripts/run_check.py <run> --ship     # which stages actually ran
```

`gate.py` also runs from a hook after every write, so its findings arrive
whether or not anyone remembers to ask. `run_check.py` is the one that catches a
stage skipped rather than failed: it reads the artefact each stage leaves, and
treats a file still holding its scaffolded template as a stage that never ran.

## Staged runs (one conversation per stage)

The app can run this pipeline one stage per fresh conversation, so no conversation
carries the stages before it. It tells you so in the prompt. The four stages, what
each covers, and what it must leave on disk before the app starts the next:

| Stage | Covers (table above) | Complete when |
|---|---|---|
| `gather` | 0–4: supplied sources, brief, gap hunt, scouts, coverage audit, and the voice decision (research §5b) | `brief.md`, `voice.md`, a filled `coverage.md`, evidence rows, digests in `notes/digests/` |
| `draft` | 5: the `report-writer` in DRAFT mode | `draft.md` |
| `review` | 6–7: `verify` and `critique`, concurrently | `verification.md` and `critique.md` |
| `finish` | 8–9: the `report-writer` in REPAIR mode, then the ship gates and the confidence statement | `report.md`, `repair-log.md`, `run_check.py --ship` clean |

- **The first stage** arrives as the author's request with a note that the run is
  staged. Do `gather` and end your turn. Do not start drafting.
- **A later stage** arrives as `/research-pipeline stage=<name> run=outputs/<slug>`.
  You have no conversation behind you, by design: everything is in the run folder.
  Read `brief.md`, `coverage.md`, `voice.md` and the digests (and, for `finish`, the
  two ledgers), do that stage only, and end your turn.
- **Questions to the author are fine.** Ask, and end the turn; the app waits, and
  the stage continues in the same conversation when the author replies.
- **A failed gate** is handled inside the stage, as the table above requires. Never
  end a stage by leaving its file in a state that looks complete when it is not:
  the app reads the files to decide whether to go on.
- **Typed by hand**, `stage=<name>` runs just that stage, which is also how to
  re-run one.

Outside the app, or with staging switched off, the pipeline runs as described in
the rest of this file, in one conversation.

## Parallelism

- Stage 3: all scouts in one message.
- Stages 6 and 7 can run **concurrently** — verification and critique are independent. Spawn `source-verifier` batches and `report-critic` together, then merge findings before repair.
- Never spawn an agent whose brief depends on another running agent's output.

## Scaling to the question

**Not every question earns this pipeline, and running it on one that doesn't is a
failure — not thoroughness.** Judge the tier before you scaffold anything, using
`.claude/references/response-scale.md`, and say in one line which you picked.

- **Tier 0–1** — a fact, a definition, a question with one sourced answer. Answer
  in chat, plainly and briefly, with the link. **No run folder, no brief, no
  report.** Stop here; the rest of this skill does not apply.
- **Tier 2 · Standard** (most requests that reach this skill): 3–5 scouts, full
  verify, one critic.
- **Tier 3 · Deep** (decision-grade, contested, high-stakes): 6 scouts including a
  dedicated dissent scout, full verify, two critics with different angles, two
  repair rounds.

Run the gap hunt even on a question that looks small — it takes seconds and it is
what catches a question that only *looks* quick. If it surfaces a live
disagreement, escalate and say so.

This sizes the *research effort*, not the report. Once a report is warranted it is
as long as fully answering the brief requires, in full register — see `report`'s
completeness rules. **A small question never produces a simplified report; it
produces no report and a short answer.**

Re-judge as evidence lands, in both directions, and say when you do.

## Voice and supplied sources

Two decisions cut across every stage, and both are cheap at the start and
expensive later.

**Narration mode** is chosen once, before drafting, and recorded in
`<run>/voice.md`: `scientific` for specialists, `explanatory` for technically
literate non-specialists. Both carry identical claims, citations, caveats and
confidence. Every later round reads that file rather than re-deciding. The
author's own writing rules are in `.claude/voice/profile.md` and are enforced by
`voice.py lint`. Doctrine: `.claude/references/voice.md`; the skill is
`/narrator`.

**Author-supplied sources** live in `<run>/external_data/` and are indexed by
content hash. Scan at the start of research, verification, expansion, and edit
absorption; read only what is unread; register each file once its evidence rows
exist. Doctrine: `.claude/references/external-data.md`.

## Final confidence statement

Ships with every report:

```
Confidence: Medium
Basis: 14 sources, 9 primary; strongest load-bearing source B2.
Checked: 23 of 23 extracted claims verified; 2 partial (qualifiers restored), 1 removed.
Coverage: 5 of 6 sub-questions COVERED, 1 CONTESTED (shipments vs installs, §3).
Holes: 4 data points not obtained — 3 access-restricted, 1 unpublished. See "Data still to obtain".
Weakest link: install-base figures rest on one vendor survey [E19] (D2).
Would change the answer: <specific observation>.
```

Never state High confidence on single-origin evidence, however many outlets repeated it.

The confidence statement is the report's claim about its own evidence, so it
names **no internal file, no subagent, no round, and no script**. "Twenty-three of
twenty-three claims were re-checked against their sources" ships; "see
`verification.md`" does not.

## The deliverable is one Markdown file

`report.md` in the run folder, always holding the latest state — the promotion
from `draft.md` happens once, in stage 8, and every later edit is made in place.
Exports are derived copies. When the user asks for "the report", it is this file,
and it is clean: no severity tags, no round headings, no pipeline vocabulary. Run
`gate.py` and confirm the artifact count is zero before you hand it over.

## Continuing after ship

A finished report is a checkpoint. When the reader comes back — "go deeper on X", "what about Y", "is this still true?" — that is `expand`, not a new run: it opens a round inside the same folder, researches the ask, and **reconciles** the new evidence into the document rather than appending it. The audit trail is cumulative and the reader must not be able to tell which round wrote which paragraph.

When the reader comes back having **edited `report.md` themselves**, that is `user-edits`: their text is respected and completed in place, never reverted. Check for this before extending — `section_guard.py check` will show sections moving that no round moved, and extending over an unabsorbed manual edit is how a user's wording disappears.

Both work inside a declared scope. Sections outside it come through byte-identical, and that is proved rather than asserted — but a wider blast radius is legitimate when a reframing or a contradicted claim genuinely reaches further. It is named before the edit, never discovered after it.

## Failure honesty

If the research did not answer the question, the deliverable says so in the first paragraph and explains what would be needed. A confidently-written report about something you could not establish is the worst possible output of this pipeline — worse than no report.

Partial answers ship **partial, not trimmed** — with visible holes rather than a deleted section. See `.claude/references/gaps.md`.
