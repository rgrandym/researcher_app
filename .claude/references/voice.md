# Voice

Doctrine for how a report **sounds**. Read by every skill that writes prose into
`report.md`, and by every agent that reviews it.

Voice is a separate decision from register, and the two are often confused:

| Axis | Question it answers | Where it is defined |
| --- | --- | --- |
| **Register** | What kind of document is this? | `.claude/skills/report/references/register.md` |
| **Narration mode** | Who is reading it, and how much do they already know? | this file |
| **Author voice** | How does *this author* write a sentence? | `.claude/voice/profile.md` |
| **Diction** | Which words, and how often may one repeat? | `.claude/references/diction.md` |

They compose. A consultancy-register report can be narrated in either mode, and
both modes obey the same author voice. Register decides the structure and the
argument shape; narration decides the explanation load; the profile decides the
punctuation and the sentence architecture. Nothing in narration mode may change
what the evidence supports.

---

## The two narration modes

### `scientific`

The reader is a specialist in the field of the report. Terminology is used
directly and defined only when a term is contested or used in a non-standard
sense. Mechanisms are stated at their real level of detail. Quantities carry
interval, n, and basis. Alternative explanations are stated and addressed.

Signals it is being done right: a domain expert reads a paragraph without
slowing down, and can locate the exact claim they would want to challenge.

### `explanatory`

The reader is technically literate and intelligent, but not a specialist in
this field: a founder, an investor, a programme manager, a clinician reading
outside their specialty, a policy analyst. They can follow a mechanism when it
is built for them, and they will not tolerate being talked down to.

What changes from `scientific`:

- **A term is defined at first use, inside the sentence, and then used
  normally.** "FGF-2 carries two exposed thiol groups (sulphur atoms on the
  protein's surface that readily bond to each other), so molecules clump
  together and lose activity [E15]." One clause, then move on. No glossary, no
  parenthetical redefinition on every later mention.
- **The mechanism is built before the finding rests on it.** Where the
  scientific mode can assert that expression host affects potency, the
  explanatory mode spends two sentences on why a bacterium and a mammalian cell
  fold a protein differently, then uses the finding.
- **Quantities are anchored.** A number a specialist reads as small or large
  gets its comparison stated: "a tenfold window, meaning the weakest acceptable
  batch delivers a tenth the signal of the strongest [E2]."
- **Sentence architecture is simpler**, with fewer subordinate clauses per
  sentence. The ideas stay as complex as the evidence requires; the sentences
  carrying them get shorter.

### What does **not** change between modes

This is the part an agent gets wrong, so it is stated as a rule rather than a
preference. Under `explanatory`:

- Every claim keeps its `[E#]`. No claim is simplified past what its source
  says.
- Every caveat, contradiction, and gap ships. A caveat is exactly the thing a
  non-specialist cannot reconstruct for themselves, so dropping it does more
  damage here than in the scientific mode.
- Calibrated language is unchanged. "One study reports" does not become "studies
  show" because the second reads more smoothly.
- Confidence is unchanged. Fluency is not evidence, and a softer voice must
  never sound more certain than a technical one.
- The register's structural obligations are unchanged: answer-first if
  consultancy, limitations section, data still to obtain, sources.

`explanatory` is a different **reader**, not a lower standard. A shorter report
is a length decision and is made separately; see
`.claude/references/response-scale.md`.

---

## Choosing the mode

1. If the user named a mode or an audience, use it.
2. If the run folder holds `voice.md`, use what it records. A report keeps one
   voice across its whole life, including every later `/expand`, `/repair`, and
   `/user-edits` round.
3. Otherwise **ask**, in one question, before drafting: scientific for
   specialist readers, or explanatory for a technical but non-specialist
   audience. Ask once and record the answer.

Record the decision in `<run>/voice.md`:

```markdown
# Voice
**Mode:** explanatory
**Register:** consultancy structure, scientific evidence handling
**Citation system:** house
**Audience:** founders and investors; no battery-chemistry background assumed
**Chosen:** 2026-08-15, by the user at drafting
**Profile:** .claude/voice/profile.md (rev 2026-08-15)
```

Three of those fields are decided once and read by every later round rather than
re-decided: the narration **mode**, the **register**
(`report/references/register.md`: scientific, consultancy, or hybrid narrative),
and the **citation system** (`house`, `mla`, `chicago-ad`, `chicago-notes`; see
`.claude/references/citation-style.md`). The citation system changes nothing in
`report.md`, which always cites `[E#]`; it decides what `/export` renders, and
recording it means a re-export a month later does not silently switch
convention.

A mode change after drafting is a rewrite of every section, not a pass over the
document. Declare it as such, and treat it with the blast-radius rules that any
document-wide edit gets.

---

## The author voice binds in both modes

`.claude/voice/profile.md` holds the author's stated rules and observed cadence.
It applies to `report.md` and to every exported copy. It does not apply to
`evidence.jsonl` quotes (verbatim by definition), to source titles, or to
internal working files.

The lint runs from a hook after every write, so its findings arrive without
being asked for. To see them without writing:

```bash
python3 .claude/scripts/gate.py <run>/report.md
```

A `VOICE` line is a defect and is fixed by rewriting the sentence, never by
deleting the sentence to silence the check. A `DRIFT` line is informational.

Every run's `voice.md` also carries an **`Interpretation:`** field, and it is
part of the voice contract rather than a note. `factual-only` is the default and
means the prose states what the sources support and stops. `licensed — <scope>,
approved <date>` is written only after the author has said so, and it names the
sections it covers. An agent that wants to interpret offers the step in chat and
writes the factual version in the meantime. Doctrine and the reasoning:
`.claude/voice/profile.md`, "Factual by default".

`SHAPE` lines flag sentence architectures that read as machine-written even when
every word is the author's: chiefly **defining a thing by naming something it is
not**. The full-clause and trailing forms of that move are hard bans and fail the
lint; the parenthetical foil and the abstract-subject colon reveal are advisory.
The test for the trailing form is mechanical: if cutting everything after the
comma leaves the sentence intact, the tail was decoration. See
`.claude/references/diction.md` §5b.

`ECHO`, `ECHO-NEAR`, `OPENER` and `DICTION` lines come from the repetition and
word-choice pass, which `lint` includes and which runs alone as
`voice.py echo <file>`. They are advisory and never fail the build, because a
term of art repeated eight times is correct writing and a script cannot tell it
from a lazy verb. Read every one, fix the real echoes, and record the deliberate
terms in `<run>/voice-terms.txt`. Doctrine: `.claude/references/diction.md`.

After the agent finishes writing:

```bash
python3 .claude/scripts/voice.py mark <run>/report.md
```

This stores what the agent wrote, so that the next manual edit by the author can
be told apart from it. Skipping `mark` breaks the learning loop silently, which
is why it belongs in the same close-out block as the guard snapshot.

---

## How the author's voice is learned

The author's manual edits are the only reliable sample of how they write. The
loop:

1. An agent writes or edits `report.md`, then runs `voice.py mark`.
2. The author edits the file by hand.
3. `voice.py learn <run>/report.md` diffs the file against the mirror and files
   the author's own passages into `.claude/voice/corpus/`.
4. `voice.py profile --rebuild` measures the corpus and moves the cadence bands
   toward it.
5. A human reviews `profile.md` and writes any new **stated rule** into it. This
   step is not automated: a rule the author would endorse is a judgement, and
   guessing one from a diff produces confident nonsense.

`/user-edits` runs steps 3 and 4 as part of its close-out. Anything the author
says about their own writing, in chat, is recorded in `profile.md` under
*Stated rules* with the date, because chat is lost and the profile is not.

What the corpus is **not** for: it is not a bank of sentences to paste, and no
passage from it is ever reused verbatim in a new report. It is evidence about
habits.
