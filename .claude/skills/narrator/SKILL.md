---
name: narrator
description: Set or change how a report sounds — choose the narration mode (scientific for specialists, explanatory for technical but non-specialist readers), apply the author's own voice profile, and re-narrate an existing report into a different mode without touching its evidence. Use when the user asks who the report is for, asks for a version a non-scientist can read, says the writing sounds like AI, asks to rewrite in their style, or before drafting any report so the voice is decided once. Also runs the style-learning loop that captures the author's manual edits into the voice profile.
---

# Narrator

You are deciding, and then enforcing, **how the report sounds**. You are not
deciding what it claims. Every fact, citation, caveat, number, and confidence
statement is fixed before you start and comes through unchanged.

Read `.claude/references/voice.md` first. It defines the two narration modes,
what may not change between them, and where the decision is recorded. Read
`.claude/voice/profile.md` for the author's own rules. Both are short.

The one-line summary of the division of labour:

```
register    what kind of document        report/references/register.md
narration   who is reading it            .claude/references/voice.md
profile     how this author writes       .claude/voice/profile.md
anti-slop   what nobody should write     report/references/anti-slop.md
```

## When you are invoked

| Situation | Do this |
| --- | --- |
| Before a first draft | §1, then hand the decision to `/report` |
| "Give me a version for non-scientists" | §2, full re-narration |
| "This reads like AI" | §3, voice pass against the profile |
| "Remember how I write" | §4, learning loop |
| A report already has `<run>/voice.md` | Read it and comply. Do not re-ask |

---

## 1. Decide the mode

Ask exactly one question, and only when the answer is not already available:

> Who is reading this? **Scientific** (specialists in the field: terms used
> directly, mechanisms at full detail) or **explanatory** (technically literate
> non-specialists: terms defined at first use, mechanisms built before they are
> used, same evidence and same caveats).

If the user has already named an audience anywhere in the request, infer from it
and say which you inferred rather than asking. "For our investors" is
`explanatory`. "For the R&D team" is `scientific`.

Write `<run>/voice.md` with the template in `.claude/references/voice.md`, then
continue. That file is what stops a later `/expand` round from silently changing
voice halfway through a document.

## 2. Re-narrate an existing report

A mode change touches every section, so it is a document-wide edit and follows
the same containment discipline as any other.

```bash
run=outputs/<slug>
python3 .claude/scripts/section_guard.py snapshot $run/report.md   # baseline first
python3 .claude/scripts/voice.py stats $run/report.md              # where it starts
```

Declare the blast radius as the whole document, in writing, before editing.

Then work **section by section**, and hold two invariants at every step:

1. **The claim set is identical.** Same `[E#]` on the same assertions, same
   numbers, same units, same qualifiers, same hedges. Run
   `audit_citations.py` afterwards and confirm the cited-ID set did not change.
2. **The structure is identical.** Same headings, same order, same exhibits,
   same tables. If a heading has to change to survive the new mode, that is a
   structural decision: propose it, do not perform it.

What actually changes, going from `scientific` to `explanatory`:

- A term used cold gets a defining clause at its first appearance, and only
  there.
- A mechanism assumed gets built, in one or two sentences, immediately before
  the finding that leans on it.
- A bare quantity gets its anchor: what it is large or small compared to.
- Sentences with three or more subordinate clauses get split. The idea does not
  get simpler; the sentence carrying it does.
- Domain shorthand gets expanded once: "EC50 (the concentration producing half
  the maximum response)".

Going from `explanatory` to `scientific`, the same list runs backwards: the
defining clauses come out, the built mechanisms compress to their assertion, and
the anchors go, because a specialist supplies them.

**The failure to avoid in both directions** is drift in what the report claims.
A definition added at first use is voice work. A caveat softened because it was
hard to phrase for a lay reader is a factual change, and it is the reason this
skill re-runs the citation audit rather than trusting itself.

## 3. Voice pass against the author profile

This is the pass to run when the user says the writing sounds like a machine.

```bash
python3 .claude/scripts/voice.py lint $run/report.md
```

Every `VOICE` line is a defect. Fix each by **rewriting the sentence**, not by
deleting it and not by swapping the banned token for a near-synonym. An em-dash
replaced with a comma in a sentence that was built around an em-dash aside still
reads as machine prose; the sentence has to be rebuilt around its real subject.

Worked example of the rebuild, not the swap:

```
before   The window is wide — 10-fold — and no page says what it governs.
swap     The window is wide, 10-fold, and no page says what it governs.
rebuild  The window spans 10-fold, and no page states what it governs.
```

`ECHO`, `ECHO-NEAR`, `OPENER` and `DICTION` lines are the repetition and
word-choice pass, and they are the second half of this job. Work through them
paragraph by paragraph against `.claude/references/diction.md`:

- A repeated **term of art** is right. Leave it, and write the term into
  `<run>/voice-terms.txt` so the next round does not re-litigate it.
- A repeated **ordinary word** is a real echo. Restructure the sentence first, a
  pronoun or short definite phrase second, a synonym third and only when it
  carries exactly the same meaning. A synonym that shifts the strength of a
  claim is a factual edit and is out of bounds for this skill.
- A `DICTION` hit is ornate vocabulary or an American spelling. Replace with the
  plain British word unless the field sets the form.
- Read the paragraph openers of each section in sequence. They should trace the
  argument; if they read as unrelated subjects, say so as a structural finding
  rather than papering over it with connectives.

`DRIFT` lines are cadence, not defects. Read them as a question: if
`mean_sentence_words` is 46 against a band topping out at 30, the prose is
probably stacking clauses where the author would have used separate sentences.
Look at the longest sentences and decide; do not rewrite to hit a number.

The hook gates the file on every write and records the mirror, so what is left
is the containment proof:

```bash
python3 .claude/scripts/section_guard.py check $run/report.md --allow …
```

A re-narration touches wording everywhere and evidence nowhere. The cited-ID set
must come through unchanged; if it moved, the pass edited a claim.

## 4. The learning loop

The author's manual edits are the only honest sample of how they write.

```bash
python3 .claude/scripts/voice.py learn $run/report.md      # capture their prose
python3 .claude/scripts/voice.py profile --rebuild         # remeasure cadence
```

`learn` diffs `report.md` against the mirror of what an agent last wrote, so it
depends on `mark` having been run. If the mirror is missing, say so plainly:
the capture for that round is lost, and the fix is to run `mark` from now on
rather than to guess which lines the author wrote.

Then do the part the script cannot:

- Read the captured passages. Separate **finished prose** (voice evidence) from
  **rough notes and directives** (content, handled by `/user-edits`). Delete the
  directives from the corpus file and rebuild.
- If the author stated a rule about their own writing, in chat or in the edit,
  add it to `.claude/voice/profile.md` under *Stated rules*, with the date, and
  add a pattern to the `HARD` list in `.claude/scripts/voice.py` if it is
  mechanically checkable. A rule that lives only in a conversation is lost by the
  next session.
- Never infer a stated rule from a single edit. One replaced semicolon is not a
  policy. Ask, or wait for the pattern to repeat.

Report what was captured, what you filed as voice, what you discarded as
content, and any rule you added.

## 5. What this skill never does

- It never changes a number, a citation, a caveat, or a confidence grade.
- It never adds a claim to smooth a transition. A transition that needs a new
  fact is a research gap, not a writing problem.
- It never applies a voice to quoted material. A verbatim quote keeps the
  source's punctuation, including em-dashes, and the lint already exempts text
  inside quotation marks.
- It never produces a second copy of the report in a different voice. One
  master document, one voice, recorded in `<run>/voice.md`. If the user wants
  both, that is two runs of §2 and an explicit decision about which file is the
  master; say so rather than quietly forking the document.
