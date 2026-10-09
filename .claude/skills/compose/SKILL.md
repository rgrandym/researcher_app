---
name: compose
description: Write or improve a piece that is not a research report: a CV adapted to a posting, a cover letter, an application answer, a personal statement, an email, or the author's rough draft developed into finished prose. Use when the author asks to write, adapt, tailor, redraft, tighten, polish, or develop something in their own voice, when they hand over a job description or a form, or when they say "make this read better". Facts about the author come from dossier/, never from memory. Exports to md, docx and pdf.
disable-model-invocation: true
---

# Compose

The workspace has two lanes. `/research` answers a question from sources and
produces `report.md`. **Compose writes a piece the author signs and sends**: a
CV against a posting, a letter, an answer to a question on a form, a statement,
a paragraph they drafted and want made to work.

The lanes share everything that makes the output trustworthy: the voice profile,
the gates, the run folder, the rule that the author's own edits are direction.
They differ in what the writing answers to. A report answers to evidence about
the world; a piece answers to **the author's record** and to **the reader it is
aimed at**.

```
NEVER   a date, employer, title, figure, degree, publication or metric that
        no file in dossier/ supports. Memory of an earlier session is not a
        source here, exactly as it is not a source in /research.
ALWAYS  the voice profile in .claude/voice/profile.md, read before writing.
ALWAYS  the whole piece re-read before any paragraph is changed.
```

## 1. Scale it first, and say which you picked

`.claude/references/response-scale.md` governs; this is its compose column.

| Tier | The ask | You produce | Run folder |
|---|---|---|---|
| **0 · Inline** | Reword a sentence, shorten a paragraph, answer one line of an email | The text in chat | No |
| **1 · Piece** | A cover letter, one application answer, a bio, a short statement | A run folder and one master document | Yes |
| **2 · Dossier piece** | A CV adapted to a posting, a multi-answer application, anything with a form to satisfy | Run folder, `context.md` filled, independent review | Yes |

Tier 0 stays in chat and writes nothing to disk. It is the common case for
"make this sentence better", and turning it into a folder wastes the author's
attention. Say which tier in one line, and move up out loud when the ask turns
out larger: a cover letter that needs the CV rebuilt behind it is Tier 2.

Anything the author will send to a named reader gets the independent review in
§6. Nothing they sign ships on a first draft.

## 2. Scaffold, and read before writing

```bash
run=$(bash .claude/scripts/new_piece.sh <kind> "<slug>" "<the author's prompt, verbatim>")
python3 .claude/scripts/external_index.py scan dossier   # the author's record
python3 .claude/scripts/external_index.py scan $run      # this piece's brief
```

Kinds: `cv` · `cover-letter` · `answer` · `statement` · `piece`. The master
document is named after the kind (`cover-letter.md`), is declared in
`.run.json`, and is what every gate, review and export acts on from then on.

Three things get read before a word is written, and in this order:

1. **`dossier/`**, the author's standing record. Everything the piece can
   truthfully claim is in there. Read only what the piece will draw on; write
   the extracts you will actually use to `notes/`.
2. **`$run/source_material/`**: the posting, the call, the form, the thread.
   Mine it for what it *asks for*, including anything it asks for twice, and
   for the word limits, which are hard constraints.
3. **Anything the author already wrote**, such as their rough draft or a
   previous letter in `dossier/letters/`. Their draft is the text this round
   starts from; it is never raw material for a replacement.

Then fill `$run/context.md`: reader, purpose, the line, constraints. That file
is what a later round re-reads instead of re-deriving the brief, and
`run_check.py` refuses to ship a piece whose context was never filled in.

## 3. Match the claim to the record

Go through what the target asks for and mark each one against the dossier:

| State | What it means | What you do |
|---|---|---|
| **Supported** | A dossier file states it | Write it, in the strongest true form |
| **Partial** | The record supports something adjacent or smaller | Write the true smaller claim. Never round it up |
| **Absent** | Nothing in the record supports it | Leave it out, list it under "Claims that need checking" in `context.md`, and tell the author in chat |

Absent is the case that decides whether this pipeline is worth anything. A
posting asking for ten years where the record shows six is answered by the
record. Ask the author; they often have the fact and have not filed it. What
never happens is a number appearing because the posting wanted one.

The author asserting something in chat or in the draft **is** a source for the
piece: it is their claim about their own life and it stands. Add it to the
dossier so the next piece has it, and say that you did.

## 4. Write it

Read `.claude/voice/profile.md` first, every time. Then
`references/kinds.md` in this skill for the doctrine of the kind you are
writing: a CV, a letter, an answer and a statement fail in different ways.

Rules that hold across all of them:

- **One line, followed through.** The line in `context.md` is what the piece
  argues. A paragraph that does not advance it comes out, however well written.
- **Specific beats broad.** One project described concretely outranks four
  listed. The evidence for that is in the dossier; use it.
- **The reader's language.** Where the posting names the problem in its own
  words, answer in those words, provided the claim underneath is true. Matching
  vocabulary is legitimate; matching a requirement you cannot meet is not.
- **Word limits are exact.** A 300-word box takes 290 words, never 340. Report
  the count when you hand over.
- **No pipeline in the piece.** The same rule as a report: no evidence markers,
  no internal filenames, no notes to the author inside the text. Anything the
  author needs to decide goes in chat.

Write to `$run/<kind>.md`. The hook gates it on write; a `VOICE` failure is a
construction the author has banned, and the fix is to rebuild the sentence.

## 5. When the author has edited it

They will. The moment the piece exists they will rewrite the last paragraph, and
the rest of the document has to move to match.

**That is `/user-edits`, and it works on this master unchanged.** Do not
re-implement it here and do not start by re-reading the source material. Their
concepts survive; the prose around them is repaired; a claim of theirs that the
record contradicts is flagged in chat and left standing in the text.

```bash
python3 .claude/scripts/saved_check.py $run          # exit 1 = still in their editor, STOP
python3 .claude/scripts/voice.py learn $run/<kind>.md   # capture how they write, before you touch it
diff -u $run/.voice-mirror-<kind>.md $run/<kind>.md
```

`voice.py learn` is the whole reason the system gets better at their voice: it
files what they wrote by hand into the corpus. Run it before your first edit of
the round or the sample is contaminated with your own prose.

Absorbing an edit is a **whole-document** job even though the change is local.
Re-read the piece end to end, then repair the seam: the paragraph before now has
to hand off to what they wrote, the paragraph after has to pick up from it, and
a claim they moved into paragraph three must come out of paragraph one.

## 6. Review it, with a thread that did not write it

Nothing the author signs ships on a first draft, and the thread that wrote the
draft cannot review it.

Spawn `report-critic` with the piece, `context.md`, and the target's
requirements. Ask for: requirements the piece fails to answer, claims stronger
than the record supports, paragraphs that do not advance the line, voice
defects, and anything a hostile reader would seize on. It returns findings;
write them to `$run/review.md` and repair the ones that stand.

Then:

```bash
python3 .claude/scripts/gate.py $run/<kind>.md      # must exit 0
python3 .claude/scripts/run_check.py $run --ship    # prompt, context, piece, review
```

## 7. Validate, when the author asks

"Check this", "is that right?", "find me something that backs this up", "does
this claim hold?" A piece can carry claims about the world as well as about the
author: a market figure in a business case, a statement about the field in a
personal statement, a technical assertion in an answer.

That is a research job inside a compose run, and it uses the research
machinery:

- Spawn `research-scout` for the claim. It writes verbatim extracts to `notes/`
  and rows to `$run/evidence.jsonl`, the same as in a report.
- The verdict goes to the author **in chat**, with the source.
- **The evidence ID does not go into the text.** A cover letter that says
  `[E4]` is not a cover letter. The ledger holds the backing; the sentence
  stays clean. The exceptions are the kinds that carry references by
  convention: a research statement, a grant answer, an essay. `kinds.md` says
  which, and `/export` renders those the same way it renders a report.
- A claim of the author's that the sources contradict is **flagged, not
  rewritten**. Their text, their call. Say it plainly in one line and offer the
  version the sources support.

Record what was checked in `$run/verification.md` so a later round does not
re-fetch it.

## 8. Export

`/export` handles the compose branch. With no figures to render and no
citations to resolve, it converts the master straight to `.docx`, `.pdf` and
`.html`.
Markdown is already the master and needs no conversion. Ask for format and
style once, as `/export` requires, and run `check_export.py` afterwards: for a
piece with no citations and no exhibits, the word count is the only thing
standing between a clipped second page and a document that looks complete.

A CV goes out as `.docx` more often than not, because recruiters edit it and
applicant tracking systems parse it. Say so rather than assuming a PDF.

## What this skill does not do

- It does not research a subject. A piece that needs a body of evidence behind
  it is `/research` first, then compose against the report.
- It does not invent a fact to fill a gap in the record.
- It does not overrule the author. Their sentence stands; the concern goes in
  chat.
