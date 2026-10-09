# Research Workspace

This workspace produces two things, in two lanes that share one set of rules:

- **Cited research reports.** `/research` → `report.md`, accountable to evidence
  about the world.
- **Writing the author signs and sends**: a CV against a posting, a cover
  letter, an application answer, a statement, a draft of theirs developed into
  finished prose. `/compose` → a piece, accountable to the author's own record
  in `dossier/` and to the reader it is aimed at.

Human-facing docs: [USERGUIDE.md](USERGUIDE.md).

Two goals, in order: **accuracy** — every claim traceable to a source that
actually says it; then **completeness on the question asked**, including the
caveats, contradictions and gaps a reader needs in order to act. Length comes
from evidence, never from restatement or filler.

## The rules that hold on every turn

1. **Never write a URL, title, author, date, figure, or quote you have not
   fetched.** Memory is a lead, not a source. Quotes are copied from fetched
   text, never paraphrased into quote marks.
2. **Every factual claim in a report carries an evidence ID** (`[E12]`) that
   resolves to a row in `<run>/evidence.jsonl`. No ID means the sentence is a
   labelled inference or is marked `[UNVERIFIED]`. Never silently deleted.
3. **A gap the researcher found is a gap the reader sees.** Data you could not
   obtain is shown as a labelled hole, never as `N/A`, a deleted row, or a
   guessed value. Register it with `wanted.py` so the author can fetch it.
4. **Nothing ships on a first draft.** Every deliverable goes
   investigate → draft → independent subagent review → repair. The thread that
   wrote the draft never reviews it.
5. **The deliverable carries no trace of the pipeline.** No internal filenames,
   subagents, rounds, severity tags, or self-reference in `report.md`. The
   reader gets a report, not a research log.
6. **Nothing changes outside the declared scope.** A wider blast radius is
   legitimate and is declared *before* the edit, never discovered after it.
7. **What the author writes into the report is direction: preserve the concept,
   not the sentence.** Their additions, deletions and rewrites stand. If the
   evidence contradicts them, leave their text and flag it in chat.
8. **Facts about the author come from `dossier/`, never from memory.** A date,
   employer, title, figure, degree or publication appears in a CV, a letter or
   an answer because a file in that folder says so. Rule 1 in the other lane.
   The author asserting something about their own life is itself a source; file
   it in the dossier so the next piece has it.
9. **Scale the response to the question.** A fact gets a few plain sentences in
   chat and no run folder; a decision-grade question gets the full pipeline.
   State the tier and say when it moves. Plain language is never lower
   standards, and a small question yields no report rather than a simplified
   one. The same scale runs in the compose lane: rewording a sentence is a chat
   answer, and a letter someone will read is a run folder with a review.
   **Runs start only from a command the author types.** A message without one is
   a chat question: answer it at Tier 0 or 1 with a few searches at most, scaffold
   nothing, spawn no scouts, and when it deserves more, name the command that
   would do it (`/research`, `/verify`, `/expand`).
   Doctrine: `.claude/references/response-scale.md`.
10. **Today's date is in context and the knowledge cutoff is not the present.**
   Anything time-sensitive gets fetched.

## Voice

The author's writing rules live in `.claude/voice/profile.md` and nowhere else.
The file is personal and not in the repository; when it does not exist, write to
the house rules that `voice.py lint` enforces, and `/voice-rule` creates it with
the author's first rule.
Read that file before writing prose. The register is plain professional British
English for an educated reader.

When the author states a rule about their writing, in chat or in the document,
record it with `/voice-rule` in that turn. A rule left in the conversation is
lost by the next session.

## The gates run themselves

A `PostToolUse` hook runs `gate.py` after every write to a run's `report.md` or
`draft.md`. It collects the voice lint, the citation audit and the figure check,
returns hard failures for repair, and records what the agent wrote so the
author's next manual edit can be told from it.

Do not treat a passing gate as a passing report: it checks what a script can
check. Evidence quality, coverage and reasoning are checked by `/verify` and
`/critique`.

```bash
python3 .claude/scripts/gate.py <run>/report.md      # what the hook runs
python3 .claude/scripts/run_check.py <run> --ship    # did every stage run?
python3 .claude/scripts/saved_check.py <run>         # did the author's save land?
```

**Any round that claims to read the author's edits runs `saved_check.py` first**
and stops when it exits 1. Nothing bridges an unsaved editor buffer and a file
on disk, and both failures are silent: a round run against stale text reports a
clean result, and the author's next save overwrites the agent's work.

## The pipelines

**Research:** `/research` → `/report` → `/verify` → `/critique` → `/repair`,
then `/export` and `/expand` on request.

**Compose:** `/compose` (or `/cv`, `/cover-letter`, `/answer`, `/develop`,
`/polish`) reads `dossier/` and the run's `source_material/`, writes the piece,
takes an independent review, and exports to md, docx and pdf. `/user-edits` and
`/export` serve both lanes and act on whichever master the run declares in
`.run.json`. `/verify` runs inside a compose run when the author asks for a
claim to be checked; the evidence stays in the ledger and out of the text.

Run the research lane end to end with `/research-pipeline`. `/narrator` decides
who the report is written for and is consulted before the first draft.
`/user-edits` absorbs what the author wrote by hand into whichever master the
run declares. `/visualize` governs tables and charts.

Each stage is a skill in `.claude/skills/`. Doctrine shared by several of them
lives in `.claude/references/` and is **pointed to, never restated**: a rule
written in five places gets reconciled rather than obeyed.

A run has one master document, always current: `report.md` for research, and
the piece itself for a compose run. `draft.md` is promoted to `report.md` once,
during the first repair; every later edit is made to the master in place.
Exports are derived copies.

## Output layout

Every run gets its own folder under `outputs/`, named `YYYY-MM-DD-<short-slug>`,
and nothing from a run is written anywhere else. Scaffold it with:

```bash
bash .claude/scripts/new_run.sh "<slug>" "<the user's prompt, verbatim>"
bash .claude/scripts/new_piece.sh <kind> "<slug>" "<prompt>"   # cv · cover-letter · answer · statement · piece
```

`.run.json` records which lane the run is in and which document is its master.
Every script reads it through `runmeta.py`, so the gates, the save check, the
edit absorption and the export all follow the piece without being told its name.

`prompt.md` is written first, before any searching, and holds the request word
for word. A run you cannot trace back to what was asked cannot be audited.

```text
prompt.md  brief.md  voice.md  coverage.md  evidence.jsonl  blocked.jsonl
notes/  external_data/  draft.md  verification.md  critique.md  repair-log.md
report.md  figures/  rounds/rN/  export/<style>/
```

Keep every intermediate file: they are the reason a claim can be defended six
months later. `/expand` never scaffolds a new folder; it opens `rounds/rN/`
inside the original run and edits `report.md` in place.

A compose run is lighter: `prompt.md`, `context.md` (reader, purpose, the line,
constraints), `source_material/`, the master named for its kind, `review.md`,
`export/`. The standing record it draws on is `dossier/`, which is shared by
every piece and is never written to by a run.

Sources the author supplies live in `<run>/external_data/`, are indexed by
content hash, and are read exactly once. A supplied file nobody read is the same
failure as a source nobody searched for. Everything under
`external_data/ai_reports/` is model output, is always unverified, and is a lead
rather than a source.

## Context discipline

Context is the scarce resource: every token in the main thread is re-read on
every turn.

- **Main thread holds** the brief, digests, findings, file paths, the current
  draft. **Disk holds** raw pages, verbatim quotes, search results, full notes.
- **Delegate** when the work needs more than three sources read to produce a
  small answer, when independent lines can run at once, or when you need an
  opinion uncontaminated by this thread. Do not delegate what one targeted read
  answers.
- Grep before Read, then read the matching range. Read once; if you will need it
  again, write the extract to `notes/` and re-read that.
- Never paste raw HTML, full search results, or whole files into the main
  thread. Batch parallel spawns into one message and cap digest length.
- Move deterministic work to scripts. Counting, validating, dedup and diffing
  cost no model tokens and cannot hallucinate.
