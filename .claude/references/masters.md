# Which document

Shared doctrine. Every stage that reads or edits a run's master points here.

A run can hold more than one master. A research run has `report.md` (and `draft.md`
before the first repair). A revision run has `report.md`, the audit, and one revised
document per supplied Word or PDF file, `<slug>.md`, declared by `document.py start`.

```bash
python3 .claude/scripts/runmeta.py <run> --masters      # every master, existing first
python3 .claude/scripts/runmeta.py <run> --documents    # the revised documents: slug, path
```

## Choosing

- The request names a document (a file, its slug, "the business plan", "the audit"):
  act on that one.
- One master exists: act on it.
- More than one exists and the request names none: **ask** (`AskUserQuestion`), one
  option per master, labelled by what it is ("the audit, report.md"; "the business
  plan, optima-business-plan.md"). Never guess, and never act on both.

Wherever a skill says `report.md`, read the chosen master. Its edit state, history and
final sections are its own: `saved_check.py <run> <master>`, `edit_state.py inspect
<master>`, `section_guard.py locks <master>`.

## A revised document is not a report

It belongs to the authors and keeps the original's form, so a stage acting on it:

- Keeps its structure, headings, voice and citation system (`subjects/<slug>/voice.md`,
  `references.json`). It adds no Sources list, no `## Data still to obtain`, no
  report sections; a gap is an open item (`<!-- open: where | what | why -->`) and a
  visible `[NEEDS DATA: what · where]` in the text.
- Keeps each block's `<!-- P013 -->` anchor above it: the anchors are how the export
  finds the original paragraph. A new block has none; a deleted block takes its anchor.
- Cites in the document's own system and with the evidence ID after the claim
  (`[E12]`). The export removes the IDs.
- Leaves the authors' own text as they wrote it unless a finding is about it. The gate
  lints only the lines that differ from the original.
- Is exported with `document.py export`, never with the house styles: the Word file
  keeps the original's design.
