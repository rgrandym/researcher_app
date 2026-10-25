---
name: changes
description: Turn an audit's findings, or the author's own instructions, into a revised version of a supplied document. A Word or PDF document is rewritten as a Markdown master the author reads, edits, critiques and exports to Word and PDF; a deck, spreadsheet or Markdown file gets a change plan the author accepts or rejects. Every edit is evidenced, cited in the document's own style, written in its voice and reviewed independently. Use after /audit, or when the author asks to change, update, extend or correct an existing document in external_data.
disable-model-invocation: true
---

# Changes

The original file is never touched, and nothing reaches a finished file until the
author says so. A Word or PDF document is revised as a Markdown master that the author
reads and edits, and exports when it is ready. A deck, spreadsheet or Markdown file
gets a change plan that the author accepts change by change.

Doctrine, the plan schema and the citation table: `.claude/references/revision.md`.
Read it first.

## 0. Inputs

- The subject: `python3 .claude/scripts/subject.py list <run>`. If none is
  declared, ask which file (`AskUserQuestion`), then `subject.py add` and
  `subject.py extract`. `extract` is free when nothing changed; run it every time.
- What to change: the audit (`report.md`, its recommended changes), and the
  author's instruction in the command. The instruction wins where they differ.
- Evidence: `evidence.jsonl`. A change that needs a fact the run does not hold
  sends a scout first (`research-scout`, one brief per missing fact). Run
  `external_index.py scan` too: the author may have added a source.

If the author has edited `report.md` by hand since the last round, run
`saved_check.py` first, as for any round that reads their edits.

## 1. Voice of the document

Write `subjects/<slug>/voice.md` before drafting a word: person and stance, tense,
sentence length, how numbers, currencies and dates are written, spelling,
recurring terms, how headings are phrased, how sources are named, and three
sentences quoted verbatim. Read every passage a change lands in, as well as the
opening. Reuse the file on later rounds; update it if the subject changed.

## 2. Draft the plan

Read `text.md` whole before writing a change: the story as the author tells it,
section by section, and the working marks. Struck text is deleted; draft colours
are working marks; each comment is an instruction from the authors to address or
to answer in `open`.

### A Word or PDF document: write the revised document

The route for every `.docx` and `.pdf`: one reading, one writing pass, no plan.

```bash
python3 .claude/scripts/document.py start <run> <slug>
```

It copies `document.md` to `<run>/<slug>.md` and declares it a master of the run.
On a later round the master already exists: edit it in place, never start again.
Edit it as the document, in place:

- Leave every `<!-- P013 -->` / `<!-- T1 -->` line above the block it belongs to.
  Delete the anchor with a block you delete. New blocks have no anchor.
- Write in Markdown the document can carry: `## Heading` at the document's levels,
  `**bold run-in labels**` as it uses them, `- ` bullets, `1. ` numbered items,
  `| tables |`, `[links](url)`, `[^0]` for its existing footnotes.
- Cite twice: in the document's own system (`references.json`: links, footnotes),
  as its reader will see it, and with the evidence ID after the claim (`[E12]`), as
  in a report. The export removes the IDs; until then they are what /verify checks.
- Each open item: `<!-- open: where | what is needed | why it cannot be sourced -->`.
- Struck text (`~~...~~`) is the author's deletion: drop it or leave it, never edit it.
  The `<!-- comment ... -->` lines are the authors' instructions: act on each one.
  Answer each in the text, or in an open item saying why not.
- The text the authors wrote stands unless a finding says otherwise. The gate lints
  only the lines you changed; theirs are theirs.

The rules under **Other formats** below (keep the story, shape, cascade) hold here as
well. No `clean` step: the export removes the draft's working marks itself.

### Other formats: the JSON plan

Decks, spreadsheets and Markdown files take `changes.json` directly, as below.

Decide, **section by section**, what each needs: nothing, a correction, or a
rewrite. When the task is to incorporate an assessment, most sections that the
audit touches need a rewrite (`rewrite_section`, or `replace` of whole paragraphs),
not a scatter of phrase edits. Write `subjects/<slug>/changes.json` (schema and
blocks in the doctrine). For each change:

- **Keep the story.** Start from the section as written: its argument, its order,
  its good sentences. Put each new point where the argument needs it, with the
  sentence that connects it to what comes before. The section must read as one
  piece by one writer.
- **Locate** it by a part ID from `text.md`. For a phrase, copy `before` character
  for character. For a section, target its heading.
- **Shape** it in the document's own forms, with the blocks: its headings, its
  bullet lists, its tables. Bring the report's tables in where the reader needs the
  numbers side by side (costs, margins, market layers, competitors), cut to the
  columns that matter. For a deck, `add_slide` clones the most similar slide.
- **Ground** it: `basis` and `evidence`, and `finding` naming the audit point, the
  author's instruction or the comment it answers. `rationale` says why the document
  is better for it.
- **Cite** it in the document's system (`references.json`), with links only to URLs
  in `evidence.jsonl`.
- **Write** it in the document's voice (`voice.md`), as the author would have.
- **Cascade** it: the contents line for a new section, the summary that repeats a
  corrected figure, the deck slide and the cash-flow cell that carry the same
  number. Each is a change; paired changes name each other in `pairs_with`.
- **Clean** it: when the document carries working marks, one `clean` change removes
  them, so the new version is finished. Say in its rationale what it removes.

What the evidence cannot supply goes in `open`, never into `after` as a guess.
Register each open item with `wanted.py`.

## 3. Check and render

For a Word or PDF document, the gate runs on every write to the master. Then:

```bash
python3 .claude/scripts/document.py diff <run> <slug> --write   # subjects/<slug>/diff.md
```

Read the master start to finish, as its reader would, with the questions below, and
go to step 4. For a change plan:

```bash
python3 .claude/scripts/changes.py validate <run> <slug>    # must exit 0
python3 .claude/scripts/changes.py preview  <run> <slug>    # writes preview.md, the revised document
python3 .claude/scripts/changes.py render   <run> <slug>    # writes changes.md
```

Fix every `PROBLEM`. Read every `warn`: a missing citation on a new claim is
almost always a defect, and a document with working marks needs its `clean` change.

Then read `preview.md` start to finish, as its reader would. Does each section
follow from the one before? Does every rewritten section still make the author's
argument? Does a new table sit where the text introduces it? Is any point now made
twice, or contradicted elsewhere? Fix the plan and preview again until it reads as
one document.

## 4. Independent review

Spawn `change-reviewer` (`.claude/agents/change-reviewer.md`) in `PLAN` mode with
the run, the slug and the audit. For a Word or PDF document it reads the master and
`diff.md`; for a change plan, `preview.md` and the plan. It writes
`subjects/<slug>/review.md`. Fix every blocking and material finding (in the master,
or in the plan, then validate and render again). Do not write or edit the review
yourself; if the spawn fails, stop and say so.

**One review.** Do not send the plan back for a second one unless the first found a
blocking problem whose fix rewrote a section. Every extra pass re-reads the whole
document, and the deliverable gets its own review after it is applied.

## 5. Hand over

**A Word or PDF document.** Tell the author what changed, section by section, and
the open items. The master is theirs now: they read and edit it like a report, run
/critique, /repair, /expand or /verify on it, and export it from **Revised
document** in the app, or with:

```bash
python3 .claude/scripts/document.py export <run> <slug> --to docx,pdf [--track]
```

The Word file keeps the original's design; the export checks it against the original.
Then stop.

**A change plan.** Tell the author how many changes are proposed, grouped by kind,
the open items, and how to decide: the **Changes** view in the app (accept, reject or
rewrite each change, then **Apply accepted changes**), or in chat. Then stop.

**Never record a decision the author did not state.** When the author decides in
chat ("accept all except C04"), record exactly that:

```bash
python3 .claude/scripts/changes.py decide <run> <slug> all accept --by "author in chat"
python3 .claude/scripts/changes.py decide <run> <slug> C04 reject --by "author in chat"
```

Next step for a change plan: `/revise` for PowerPoint, Excel and Markdown;
`/rebuild` for a new design.
