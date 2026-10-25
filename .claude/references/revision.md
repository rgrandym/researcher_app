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

Word and PDF documents:

```text
/audit    research the subject: what is right, wrong, stale, missing, weak  → report.md
/changes  write the revised document as Markdown, reviewed independently   → <slug>.md, a master of the run
          the author reads and edits it; /critique, /repair, /expand, /verify act on it as on a report
export    carry it into the original's design, checked against the original → deliverable/<slug>/vN/<file>.docx, .pdf
```

Decks, spreadsheets and Markdown files:

```text
/audit    as above                                                          → report.md
/changes  turn the findings into a change plan, reviewed independently     → subjects/<slug>/changes.json
          the author accepts, rejects or rewrites each change               → subjects/<slug>/decisions.json
/revise   apply the accepted changes to a copy of the original             → deliverable/<slug>/vN/<file>
/rebuild  build a new file in the original's design (new decks)            → deliverable/<slug>/vN/<file>
```

The export is a script (`document.py export`), started by the author from the app or
by `/export`; no agent turn runs. A run holding both an audit and a revised document
has two masters, and every stage asks which it acts on: `.claude/references/masters.md`.

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
subjects/<slug>/document.md      (Word, PDF) the document as Markdown, each block under its <!-- ID -->
<slug>.md                        (Word, PDF) the revised document: a master of the run, edited in place
subjects/<slug>/diff.md          what the master changed against document.md, for review
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

A Word or PDF document has no plan. Its master, `<slug>.md`, is the document as
Markdown with each block under a hidden `<!-- ID -->`; the export turns its
difference from `document.md` into the changes below in memory and applies them, so
the schema is what decks, spreadsheets and Markdown files are planned in, and what a
Word export carries out. (`changes.py from-markdown` still turns an older run's
`revised.md` into a plan the author decides on.)

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
| `op` | `replace`, `insert_after`, `insert_before`, `delete` (Word, PowerPoint, Markdown, PDF plans); `rewrite_section`, `insert_table`, `clean` (Word); `add_slide` (PowerPoint, PDF plans); `set_cell` (Excel) |
| `target` | A part ID from `text.md`: `P012`, `T1.R2.C3.P1`, `FN1.P1`, `S03.#5.p2`, `S03`, `Sheet!C14`, `PG04.b2`, `B012` |
| `before` | `replace`: the exact original text it changes, unique in the target. `delete`: optionally the whole text. `set_cell`: optionally the current value |
| `after` | The new text, in the blocks below. Blocks separated by a blank line become separate paragraphs (Word, Markdown); lines become paragraphs on a slide |
| `like` | The part whose formatting new text copies: a paragraph, a table (`insert_table`), a slide (`add_slide`). A block may start with `{P032}` to take its own donor |
| `rows` | `insert_table`: rows of cell text; the first row is the header |
| `like_table` | The table whose formatting new tables in `after` copy (default: the document's first table) |
| `options` | `clean`: which marks to remove, all by default: `{"strike": true, "colors": true, "highlight": true, "comments": true}` |
| `fill`, `drop` | `add_slide`: text per shape ID of the cloned slide (`{"#2": "Title", "#3": "Line one\nLine two"}`), shapes to remove |
| `kind` | `correct`, `update`, `add`, `remove`, `adjust`, `style` |
| `basis` | `evidence` (needs `evidence`), `author` (the author's instruction), `consistency` (follows from another change), `editorial` (clarity, structure) |
| `open` | What the document needs that the evidence cannot supply. Each item is registered with `wanted.py` and named to the author. It is never filled with a guessed value |

Inline markup in `after`: `**bold**`, `*italic*`, `[label](https://url)`, and
`^[note text]` for a footnote in a Word document that already uses footnotes. Every
link must point to a URL that is in `evidence.jsonl`: `changes.py check` fails a
deliverable that links anywhere else.

Blocks in `after` (Word): a plain block is a paragraph; `## Heading` is a heading
in the document's own heading style of that level (a level the document lacks
becomes a bold run-in line, as its bold labels are); lines starting `- ` are bullets
in the document's own bullet list; a block of `| a | b |` lines is a table in the
document's own table formatting, as wide as the text column, first row the header;
`{T2}` alone keeps an original table in a rewritten section; `{P032}` at the start of
a block takes that paragraph's formatting.

**Match the change to the job.** A wrong figure, a stale date, a name: replace the
phrase. Incorporating an assessment into the document, adding a theme, reordering an
argument: rewrite the paragraph or the section (`rewrite_section`), so the story is
written once, in order, and reads as one piece. Never patch a section with a dozen
phrase edits that each make sense alone and together break its flow. Whatever the
size, two edits to one passage are one change, and a section that is rewritten has
no other change inside it.

**Keep the original's story.** A rewrite starts from the section as the author wrote
it: its argument, its order, its best sentences stay unless a finding says otherwise.
New material goes where the argument needs it, with the transition that connects it.
The result is the author's document improved, never a new document wearing its title.

**Tables from the report.** When the assessment carries a table the document's reader
needs (costs, margins, market layers, competitor comparison), bring it in as a table,
cut to the columns that reader uses, with its source cited in the sentence that
introduces it.

**A draft's working marks are not its design.** Struck-through text is text the author
deleted; draft colours, highlights and comments are working marks. `text.md` shows
them: struck parts are labelled, and each comment sits under the paragraph it is
attached to. Comments are the authors' instructions: address each one in the plan,
or say in `open` why not. Never edit or revive struck text unless the audit asks for
it. A plan for a document carrying marks includes one `clean` change, which removes
them (struck text, draft colours to body colour, links to the link colour, comments),
so the new version is a finished document; the author accepts it like any other.

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
- **New text takes the document's ordinary formatting.** Its font and size come from
  the donor paragraph's plain body text, never from a bold label, a struck run or a
  draft colour.
- **A file Word opens cleanly.** `changes.py check` also fails a Word file with
  comments left without an anchor, run formatting out of schema order, links to
  missing relationships, or a table wider than the text column.
- **Read the whole before anyone decides.** `changes.py preview` applies every
  change not rejected to a scratch copy and writes `preview.md`, the revised document
  start to finish. The plan is read there for flow before review.
- **A PDF is never edited.** Ask whether the author has the source file first:
  editing a `.pptx` or `.docx` always beats a PDF. A PDF document revised in
  Markdown exports to a Word file in plain styles; its design is not carried.
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
