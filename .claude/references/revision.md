# Revising a supplied document

Shared doctrine. `audit`, `changes`, `revise` and `rebuild` point here.

A revision run takes a document the author already has (a business plan, an
investor deck, a cash-flow model, a two-pager), finds through research what is
wrong, stale, unsupported or missing, proposes changes, and, once the author has
accepted them, produces a new version that reads and looks like the original.

The research standards do not change. The deliverable does: it is the author's own
document, so its form, its citation system and its voice govern every word added
to it.

---

## The author's three decisions

These were settled by the author and are not reopened per run.

1. **Citations follow the document.** If the document cites sources, new
   references use the same style and continue its numbering. A document that
   links source names in parentheses gets linked source names in parentheses; a
   footnoted one gets footnotes; a numbered one gets the next number and a new
   entry in its reference list. Evidence IDs never appear in the deliverable: the
   trail from each change to its evidence lives in the change plan.
2. **The author accepts every change.** Nothing reaches the document until the
   author has accepted it, in the app's Changes view or by stating it in chat.
   The agent never accepts on the author's behalf, and a change edited after it
   was accepted goes back to the author.
3. **"Exact" means the same style, fonts, colours, tone and voice.** Layout may
   be flexible, but every new page, slide or paragraph must look and read as
   part of the existing document.

---

## Roles of a supplied file

Declared with `subject.py add <run> <file> --role subject|template`, or by
placing the file in `external_data/subject/` or `external_data/template/`.

| Role | What it is | Standing as evidence |
| --- | --- | --- |
| **subject** | The document being improved | Its claims are what the run audits. A row may cite it only to say what the document states (`--about-document`). A claim about the world is sourced independently. |
| **template** | A document whose design and voice are copied | None. Its content is not read as evidence at all. |
| source (default) | Everything else in `external_data/` | As in `.claude/references/external-data.md` |

A statement about the company itself (its team, its plan, its own assumptions) is
the author's knowledge, cited as the document. A statement about the world (market
size, competitor prices, regulation) needs a source like any other claim, however
confidently the document makes it.

## The pipeline

```text
/audit    research the subject: what is right, wrong, stale, missing, weak  → report.md
/changes  turn the findings into a change plan, reviewed independently     → subjects/<slug>/changes.json
          the author accepts, rejects or rewrites each change               → subjects/<slug>/decisions.json
/revise   apply the accepted changes to a copy of the original             → deliverable/<slug>/vN/<file>
/rebuild  build a new file in the original's design (PDFs, new decks)       → deliverable/<slug>/vN/<file>
```

Each stage keeps the workspace loop: investigate, draft, independent review,
repair. `/audit` runs the research pipeline in full. `/changes` and `/revise`
each end with a `change-reviewer` pass (`.claude/agents/change-reviewer.md`); the
thread that wrote the plan or applied it never reviews it.

`/audit` is optional when the author states the changes themselves ("add Activin A
as the third target"): `/changes` then works from the instruction and whatever
evidence the run holds, and sends scouts for what it lacks.

## Files

```text
subjects/<slug>/source.json      the file, its role, its hash
subjects/<slug>/model.json       every addressable part, with its ID
subjects/<slug>/text.md          the readable text, one part per line: quote `before` from here
subjects/<slug>/design.json      fonts, sizes, colours, styles, layouts, page set-up
subjects/<slug>/references.json  the citation system and its numbering
subjects/<slug>/voice.md         the document's tone and voice (written by /changes)
subjects/<slug>/theme.json       design roles for a rebuild (deck_kit.py theme, then corrected)
subjects/<slug>/pages/ images/   page renders and pictures of a PDF
subjects/<slug>/changes.json     the plan (agent)
subjects/<slug>/changes.md       the plan, readable (changes.py render)
subjects/<slug>/decisions.json   the author's decisions (app or changes.py decide; never the agent unprompted)
subjects/<slug>/review.md        the independent review of the plan
deliverable/<slug>/vN/           the file, applied.json, check.json, text.md, review.md, build.py
```

The original in `external_data/` is never modified. Every version starts again
from it, so v3 is the original plus everything accepted up to then, not v2 edited.

## The change plan

`subjects/<slug>/changes.json`:

```json
{"subject": "<slug>",
 "changes": [
  {"id": "C01", "op": "replace", "target": "P013",
   "before": "a 6.8% CAGR (Roots Analysis)",
   "after": "a 6.8% CAGR ([Roots Analysis](https://…)); …",
   "kind": "update", "basis": "evidence", "evidence": ["E205"],
   "finding": "Market sizing is two years old", "summary": "Update market growth",
   "rationale": "Why the document is better for it, in one or two sentences.",
   "pairs_with": ["v4-cash-flow-forecast-2:C03"]}
 ],
 "open": [{"where": "Section 12", "what": "GMP peptide synthesis quote", "why": "no public price"}]}
```

| Field | Meaning |
| --- | --- |
| `op` | `replace`, `insert_after`, `insert_before`, `delete` (Word, PowerPoint, Markdown, PDF plans); `insert_table` (Word); `add_slide` (PowerPoint, PDF plans); `set_cell` (Excel) |
| `target` | A part ID from `text.md`: `P012`, `T1.R2.C3.P1`, `FN1.P1`, `S03.#5.p2`, `S03`, `Sheet!C14`, `PG04.b2`, `B012` |
| `before` | `replace`: the exact original text it changes, unique in the target. `delete`: optionally the whole text. `set_cell`: optionally the current value |
| `after` | The new text, with the markup below. Blocks separated by a blank line become separate paragraphs (Word, Markdown); lines become paragraphs on a slide |
| `like` | The part whose formatting new text copies: a paragraph, a table (`insert_table`), a slide (`add_slide`). A block may start with `{P032}` to take its own donor |
| `rows` | `insert_table`: rows of cell text, each as wide as `like` |
| `fill`, `drop` | `add_slide`: text per shape ID of the cloned slide (`{"#2": "Title", "#3": "Line one\nLine two"}`), shapes to remove |
| `kind` | `correct`, `update`, `add`, `remove`, `adjust`, `style` |
| `basis` | `evidence` (needs `evidence`), `author` (the author's instruction), `consistency` (follows from another change), `editorial` (clarity, structure) |
| `open` | What the document needs that the evidence cannot supply. Each item is registered with `wanted.py` and named to the author. It is never filled with a guessed value |

Markup in `after`: `**bold**`, `*italic*`, `[label](https://url)`, and `^[note text]`
for a footnote in a Word document that already uses footnotes. Every link must point
to a URL that is in `evidence.jsonl`: `changes.py check` fails a deliverable that
links anywhere else.

**One change, one edit.** The smallest scope that does the job: a phrase over a
sentence, a sentence over a paragraph. A plan the author cannot review in one
sitting is a plan they will accept blind. Two edits to one passage are one change.

**Cascades are changes too.** A new section needs its line in the contents list; a
corrected figure in the body may appear again in the executive summary, the deck and
the cash-flow model. Each occurrence is its own change, and paired changes name each
other in `pairs_with` so the author accepts or rejects them together.

**Spreadsheets.** Change inputs, not outputs: a cell that holds a formula keeps a
formula. Never type a computed value over a formula. Rows are not inserted (the
formulas would not follow); new lines go in empty rows, with formulas written to
match their neighbours. The workbook recalculates when it opens.

## Citations, by the document's system

`references.json` names the system and shows samples. Follow it:

| `system` | New citations |
| --- | --- |
| `linked_parenthetical` | The source's name in parentheses, linked: `([Roots Analysis](https://…))` |
| `footnotes` | `^[Publisher, Title, date.]` shaped like the existing notes; Word numbers it |
| `numbered` | The next number, `[n]`, and a new reference-list entry: `insert_after` the last entry with `like` set to it, numbered and formatted as the others |
| `author_date` | `(Author, year)`, and a reference-list entry if the document has a list |
| `parenthetical_source` | The source's name in parentheses, as the document does |
| `none` | Add no citation apparatus. The evidence stays in the plan; say so to the author |

A deck with a sources slide gets its new entries there, in that slide's format.

## Voice

The subject's voice governs new text, ahead of the house voice profile and the
narration modes, because the reader is the document's reader. `/changes` writes
`subjects/<slug>/voice.md` before drafting: person and stance ("we", "Optima"),
tense, sentence length, how numbers and currencies are written ("500,000 pounds",
"USD 9.7 billion", "£60k"), spelling convention, recurring terms and abbreviations,
how headings are phrased, how sources are named in the text, and three sentences
quoted verbatim. New text is written to it. The author's own writing rules in
`.claude/voice/profile.md` still bind where the document is silent.

## Form

- **Edit in place, never re-create.** `apply_changes.py` edits inside the original's
  structure, copying formatting from donor parts, so styles, fonts, colours,
  numbering, headers, fields and every untouched byte survive.
- **No formatting the original does not use.** `changes.py check` fails on any font,
  size, colour, highlight or style that the original never uses.
- **A PDF is rebuilt, never edited.** Ask whether the author has the source file
  first: editing a `.pptx` or `.docx` always beats rebuilding from a PDF.
- **Rebuilt files use the design, nothing else.** `deck_kit.py` draws only with
  `theme.json`, whose every value comes from `design.json`; `changes.py fidelity`
  enforces it. Look at the original's pages and set the theme's motifs (header band,
  kicker, panel, list style, title weight) until a new slide could sit between two
  old ones unnoticed. Logos and pictures are reused from `images/`; none are invented.

## Gaps

A number the evidence cannot supply is not proposed as a value. It goes in `open`,
is registered with `wanted.py`, and is named in the hand-over. A change that inserts
a visible `[NEEDS DATA — …]` placeholder is legitimate only if the author accepts it.

## Hand-over

The deliverable is the author's document, so it carries no trace of the pipeline:
no evidence IDs, no internal file names, no review vocabulary. Word tracked changes
carry the author name the author gave, or `Revision`. The hand-over message names
the file, the version, how many changes were applied, the warnings, the open items,
and the next step.
