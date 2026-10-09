# Diction

Doctrine for **word choice and repetition** inside a paragraph. Read by every
skill that writes or edits prose in `report.md`, alongside
`.claude/references/voice.md` (who the reader is) and `.claude/voice/profile.md`
(how the author writes).

Three rules, in priority order. When they collide, the earlier one wins.

```
1  A term of art never changes.        Precision outranks variety.
2  An ordinary word does not echo.     Vary it, or restructure the sentence.
3  A plain word beats an ornate one.   British professional register, not literary.
```

---

## 1. Terms of art are fixed

A word that names the thing under study is a label, not a stylistic choice.
Assay, potency, cohort, tariff, endpoint, gross margin, EC50, incumbent: each
keeps one form throughout the report. Swapping "assay" for "test", "trial",
"experiment" and "examination" across four sentences does not read as varied
writing, it reads as four different things, and a specialist will ask which one
was meant.

The test: **would a careful reader wonder whether the second word means the same
as the first?** If yes, repeat the first word. Elegant variation on a technical
term is a defect, and it is a worse one than repetition, because it damages the
claim rather than the prose.

The same discipline covers defined entities: a company, a regulation, a study
cohort, and a named dataset keep their names.

## 2. Ordinary words do not echo

Everything that is not a term of art is fair game for repetition, and repetition
inside one paragraph is the most common flaw in otherwise competent writing.
Verbs, abstract nouns, connectives, and evaluative adjectives are where it
shows: *show, suggest, provide, approach, factor, area, however, significant.*

What counts as an echo:

| Pattern | Example | Fix |
| --- | --- | --- |
| Same ordinary word three or more times in a paragraph | "provides… provides… provided" | Change two of the three, or merge the sentences |
| Same word twice within about fifteen words | "the approach taken here… this approach" | Second mention becomes "it", "the method", or is absorbed into the clause |
| Same word ending consecutive sentences, or opening them | "…across Europe. Across Europe, the…" | Restructure the second sentence |
| Same sentence opener three times running | "The study… The study… The results…" | Vary the subject position, not just the word |
| Same connective repeated in a paragraph | two "however"s | One goes; usually neither is needed |

Three ways out, and the first is usually best:

1. **Restructure.** The echo is often a symptom of two sentences built the same
   way. Merging them, or making the second sentence start from its object,
   removes the repeated word without needing a synonym at all.
2. **Pronoun or shorthand.** The second mention becomes "it", "these", "the
   latter", or a short definite phrase the reader already holds.
3. **Synonym**, only when it carries the same meaning exactly. See §3 for the
   ceiling on this.

A word repeated deliberately, for parallel structure across a list or a
comparison, is not an echo. Parallelism is a decision; drift is not.

## 3. The synonym ceiling

Synonyms are a repair, not a habit. Two limits:

- **No synonym that changes the claim.** "Reduced" is not "eliminated",
  "associated with" is not "causes", "most" is not "all". A word swapped for
  rhythm that shifts the strength of a finding is a factual error introduced by
  a style edit, and it is the failure mode this section exists to prevent.
- **No reaching.** If the plain word appears twice in a paragraph and no natural
  alternative exists, keep it twice and restructure instead. Two honest
  repetitions read better than one thesaurus word the author would never use.

## 4. Register: British, professional, not literary

The reader is a highly educated professional. The prose is plain, precise,
British, and unadorned.

- **British spelling and usage**: organise, analyse, behaviour, licence (noun),
  defence, programme (except a computer program), centre, modelling, per cent
  in prose. Keep the international scientific forms where a field uses them
  (sulfur, metre, litre as the field writes them) and stay consistent within
  the report.
- **Plain over ornate.** Prefer the short word that says it: *use* not
  *utilise*, *many* not *a myriad of*, *build* not *architect*, *start* not
  *commence*, *about* not *in the region of*, *helps* not *facilitates*.
- **No literary vocabulary.** Tapestry, realm, journey, unveil, herald, usher
  in, showcase, illuminate, bedrock, cornerstone, landscape as metaphor. A
  report is not written to be admired.
- **No metaphor doing analytical work.** A comparison the evidence did not make
  is an argument the evidence does not support.
- **Connective adverbs are the author's own** and are not downgraded to the
  plain ones. *Nevertheless*, *however*, *therefore*, *accordingly*,
  *moreover*, *furthermore* and *importantly* open paragraphs and join clauses
  in this register (profile, *Connective tissue*, and rule 3 as overturned
  2026-08-28). The one check they face is whether the relation they name is the
  relation the sentences actually have.

Concision is part of register. A sentence that has said its thing stops.

## 5. Flow between paragraphs

Cohesion comes from the order of ideas **and** from connective adverbs, which
this author uses deliberately (`.claude/voice/profile.md`, "Connective tissue").
The working habit:

- A paragraph opens on the subject it is about, and that subject is usually
  something the previous paragraph has just put in the reader's hands. Old
  information first in the sentence, new information last, so each paragraph
  hands the next one its starting point.
- **A connective adverb at the head of a paragraph is correct in this register.**
  *Nevertheless*, *however*, *therefore*, *accordingly* and *moreover* are the
  author's own connectors and are never stripped out or downgraded to *but* and
  *so*. The one check they face is whether the relation they name is the relation
  the sentences have: *however* between two sentences that agree is a logic
  error, not a style one, and the fix is the right connector rather than none.
- Each paragraph makes one point. When you cannot name it in a short phrase, it
  is two paragraphs.
- Read the section's paragraph openers in sequence, on their own. They should
  trace the argument. If they read as a list of unrelated subjects, the section
  has no line through it.

## 5b. Sentence architecture, and the shapes to avoid

Word choice is only half of what makes prose read as machine-written. The other
half is architecture: a handful of sentence shapes that models reach for by
default, and that a human writer uses once a document, if at all. A paragraph
can be entirely free of stock vocabulary and still read as generated because
every third sentence has the same skeleton.

The shape the author objects to most, and the one that must not appear:
**defining a thing by naming something it is not.**

| Shape | Written instead |
| --- | --- |
| "…as a platform, not a per-product achievement." | Say what the platform does. The reader was not thinking about per-product achievements. |
| "…lower the barrier for every group, not for one company." | Name who benefits: *a small academic lab and a large manufacturer start from the same place.* |
| "open standards require adoption, not just creation." | *Open standards only work if people adopt them.* |
| "building open capability, rather than another private platform, is the bet" | Two sentences. State the foil as a fact, then state the claim. |

The trailing forms are the ones that survive review, because the sentence has
already delivered something true before the negation arrives. The negated half
carries no information: it names an alternative nobody proposed, so the reader
can delete it and lose nothing. That is the test. **If cutting everything after
the comma leaves the sentence intact, the tail was decoration.**

The same test generalises past the negation, and this is the broader rule: **a
clause that has delivered its fact is finished.** Whatever is appended after the
comma is decoration more often than it is information, whichever carrier it uses:

| Carrier | Example | Verdict |
| --- | --- | --- |
| `, so …` result clause | "…usable by whoever picks them up, so a small lab and a large manufacturer start from the same place." | Restates the head. Delete. |
| `, making/ensuring/unlocking …` participle | "The programme publishes them, ensuring wide adoption." | Asserts a consequence nobody demonstrated. Delete, or make it a sentence and support it. |
| `, which …` relative | "…would scale predictably, which closes the gap between a demonstration and a manufacturable product." | Adds a fact. Keep. |

Ask what the reader gains from the tail. If the answer is the head sentence in
warmer words, cut it. If the answer is a second fact, give it a full sentence,
because a fact worth stating is worth a subject and a verb.

Both carriers are flagged as `SHAPE`, advisory, because the `, which …` row is
a normal English sentence and no script can tell restatement from addition.

Four further shapes. The first is a hard ban; the other three are reported as
`SHAPE` and advisory, because each is occasionally the sentence a passage
needs:

- **The pseudo-cleft**, and this one is banned rather than advisory. "What the
  buyer pays for is the guarantee the supplier offers." A *what*-clause
  takes the subject position, the verb of the sentence drops to a copula, and
  the reader waits a full clause for content the plain order delivers at once:
  *the buyer pays for the guarantee offered by the supplier*. Rebuild by
  promoting the noun inside the clause to subject and its verb to main verb.
  The fronting word varies (*what*, *all that*, *the reason why*, *the thing
  that*) and the repair does not. `voice.py lint` reports it as `VOICE`,
  clause-initial only, so questions are untouched. Profile, 2026-08-24.
- **The abstract-subject colon reveal.** "The benefit is broad by construction:
  defined raw materials lower the barrier." The subject is a nominalisation and
  the verb is a copula, so the first clause says nothing and the colon then
  delivers the actual sentence. Open on the content.
- **"less about X than about Y"**, and **"not because X, but because Y"**. Both
  build a foil to knock down. Give the reason.
- **The rule of three used as rhythm.** Three parallel items where the argument
  has two, or has five. Count them because they are the number, not because
  three sounds finished.

One escape, and it is narrow. The negation is legitimate when it corrects a
misreading the reader is genuinely about to make, and the negated half therefore
carries information: *the net saving is $41.86/L, not the $70.46/L a 1 mg-pack
comparison implies.* `voice.py lint` exempts a negated tail containing a digit
for this case. When the correction needs more than a clause, it gets its own
sentence.

## 6. The mechanical check

```bash
python3 .claude/scripts/voice.py echo <run>/report.md     # repetition and diction
python3 .claude/scripts/voice.py lint <run>/report.md     # includes the above, advisory
```

`SHAPE`, `ECHO`, and `DICTION` lines are **advisory and do not fail the lint**, because a
term of art repeated eight times is correct and a script cannot tell it from a
lazy verb. They are read, not obeyed: judge each one against §1, fix what is a
real echo, and exempt the terms of art.

A `VOICE` line is different: it fails the gate, and the way past it is to
rewrite the sentence. Where the construction is the permitted case (the negated
half corrects a misreading the reader is about to make, and the digit exemption
cannot see it), register the flagged fragment in `<run>/voice-allow.txt` with a
comment naming what it corrects. That file is the record of which bans were
overridden and why, so the override is visible rather than silent.

Exempt a run's vocabulary by listing it, one term per line, in
`<run>/voice-terms.txt`. That file is the record of which repeated words are
deliberate, so it is written rather than argued about a second time.

The script sees repetition and stock vocabulary. It does not see whether a
synonym changed a claim, whether a paragraph opens on the right subject, or
whether two paragraphs are in the wrong order. Those are §1 to §5, and they are
the writer's job.
