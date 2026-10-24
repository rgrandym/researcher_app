---
name: changes
description: Turn an audit's findings, or the author's own instructions, into a change plan for a supplied document (Word, PowerPoint, Excel, Markdown or PDF), with each change located, evidenced, cited in the document's own style and written in its voice, reviewed independently, and handed to the author to accept or reject. Use after /audit, or when the author asks to change, update, extend or correct an existing document in external_data.
disable-model-invocation: true
---

# Changes

Propose; never apply. Every change is the author's to accept.

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

Write `subjects/<slug>/changes.json` (schema in the doctrine). For each change:

- **Locate** it by a part ID from `text.md`. Copy `before` character for
  character from `text.md`. Pick the smallest span that does the job.
- **Ground** it: `basis` and `evidence`, and `finding` naming the audit point or
  the author's instruction it answers. `rationale` says why the document is better
  for it.
- **Cite** it in the document's system (`references.json`), with links only to
  URLs in `evidence.jsonl`. Numbered references continue from `numbered.next`
  and get their reference-list entry as a paired change.
- **Write** it in the document's voice (`voice.md`), as the author would have.
- **Shape** it with the document's own parts: `like` for a new paragraph names a
  paragraph of the same kind (a heading for a heading, a list item for a list
  item); `insert_table` copies an existing table; `add_slide` clones the most
  similar slide and `fill`s its shapes.
- **Cascade** it: the contents line for a new section, the summary that repeats a
  corrected figure, the deck slide and the cash-flow cell that carry the same
  number. Each is a change; paired changes name each other in `pairs_with`.

What the evidence cannot supply goes in `open`, never into `after` as a guess.
Register each open item with `wanted.py`.

For a PDF subject, write the same plan against its page blocks (`PG04.b2`) and
pages (`PG04` for `add_slide`, with the new slide's text in `after`). `/rebuild`
carries it out.

## 3. Check and render

```bash
python3 .claude/scripts/changes.py validate <run> <slug>    # must exit 0
python3 .claude/scripts/changes.py render <run> <slug>      # writes changes.md
```

Fix every `PROBLEM`. Read every `warn`: a missing citation on a new claim is
almost always a defect.

## 4. Independent review

Spawn `change-reviewer` (`.claude/agents/change-reviewer.md`) in `PLAN` mode with
the run, the slug and the audit. It writes `subjects/<slug>/review.md`. Fix every
blocking and material finding in the plan, validate and render again. Do not
write or edit the review yourself; if the spawn fails, stop and say so.

## 5. Hand over

Tell the author how many changes are proposed, grouped by kind, the open items,
and how to decide: the **Changes** view in the app (accept, reject or rewrite each
change, then **Apply accepted changes**), or in chat. Then stop.

**Never record a decision the author did not state.** When the author decides in
chat ("accept all except C04"), record exactly that:

```bash
python3 .claude/scripts/changes.py decide <run> <slug> all accept --by "author in chat"
python3 .claude/scripts/changes.py decide <run> <slug> C04 reject --by "author in chat"
```

Next step: `/revise` for Word, PowerPoint, Excel and Markdown; `/rebuild` for a PDF
or a new design.
