# Anti-slop

Delete-on-sight list. Run this pass before any report ships.

Some of it is mechanically checkable, and the check is not optional:

```bash
python3 .claude/scripts/voice.py lint <run>/report.md    # must exit 0
```

The author's own stated rules live in `.claude/voice/profile.md` and take
precedence over anything here if the two ever disagree. Who the report is
written *for* is a separate decision, and it is in `.claude/references/voice.md`.

## Structural padding

- **Preamble.** "This report examines…", "In today's rapidly evolving landscape…". Start with the answer.
- **Restating the question** back at the reader. They wrote it.
- **Methodology narration.** "I searched several sources and found…". The reader wants findings; sourcing lives in the citations.
- **Section-opening summaries and section-closing summaries** of the same section. Pick zero.
- **"In conclusion" / "Overall" / "It is important to note that"** — always deletable with no loss.
- **Recap sections** that repeat the answer a third time.

## Sentence-level tells

- Empty intensifiers: *significant, substantial, robust, comprehensive, crucial, pivotal, key, vital, notable*. If the magnitude matters, give the number.
- Hedge stacks: "may potentially suggest that it could be possible". One hedge, correctly calibrated.
- The rule of three as reflex: "faster, cheaper, and more reliable" when only one is evidenced.
- "It's worth noting", "Interestingly", "Notably" — if it weren't worth noting you'd have cut it.
- "Not only… but also", "serves as a testament to", "plays a crucial role in", "the landscape of", "delve into", "underscores", "leverages".
- **Em-dashes, anywhere in prose.** The author does not use them and they are the
  single most reliable signal that a model wrote the paragraph. A colon, a
  semicolon, a comma, or parentheses is always available, and choosing between
  them is part of writing the sentence. The en-dash survives for numeric ranges
  only. Enforced by `voice.py lint`; the replacement table is in
  `.claude/voice/profile.md`.
- **The "matters" formula**: "what matters is", "the part that matters", "this
  matters because". Write the consequence instead.
- **The negative-parallel antithesis**: "it is not X, it is Y", "not only X but
  also Y". State Y. Correct X separately, with evidence, if it is a real
  misreading.
- Editorial adverbs: *crucially, importantly, notably, tellingly, strikingly,
  interestingly*.
- Rhetorical stiffeners: "make no mistake", "at its core", "the reality is",
  "here is the thing".
- Bold applied to whole sentences. Bold marks a term, not emphasis-in-general.

## Repetition and diction

Doctrine, with the fixes: `.claude/references/diction.md`. The delete-on-sight
half of it:

- **The same ordinary word three times in one paragraph**, or twice within a few
  words. Restructure the sentence first, use a pronoun second, reach for a
  synonym third.
- **A synonym that moves the claim.** "Reduced" for "eliminated", "linked to"
  for "causes". A style edit that changes strength is a factual error.
- **Elegant variation on a term of art.** Assay does not become test, then
  trial, then experiment. Terms of art repeat, on purpose.
- **Three sentences opening the same way**, or two consecutive sentences opening
  on the same word.
- **Ornate vocabulary**: utilise, myriad, plethora, realm, tapestry, journey,
  unveil, showcase, spearhead, bedrock, cornerstone, landscape as a metaphor,
  commence, facilitate, leverage. Use the plain word.
- **American spelling** in a British document: behavior, center, modeling,
  analyze, catalog. Keep the international scientific forms a field sets.
- **A paragraph opening on a subject the previous paragraph never introduced**,
  or a connection carried by "Additionally" instead of by the noun.

Advisory, and read rather than obeyed:

```bash
python3 .claude/scripts/voice.py echo <run>/report.md
```

## Substance tells

- **A paragraph with no `[E#]`.** Either it's unsourced fact (fix it) or it's filler (cut it).
- **Confident prose about the uncertain.** Fluency is not evidence.
- **Symmetric both-sidesing** where the evidence is lopsided. Report the imbalance.
- **Invented precision:** "approximately 47.3%" from a source saying "nearly half".
- **Vague attribution:** "experts say", "studies show", "it is widely believed". Name them or cut them.
- **Tables with one meaningful column** and four decorative ones.
- **Recommendations the evidence doesn't reach.** If the research didn't test it, don't advise it.

## The two tests

1. **Deletion test** — delete each sentence. If nothing is lost, it stays deleted.
2. **Wrongness test** — could this sentence be false? If not, it carries no information. "AI is transforming industries" cannot be wrong, and says nothing.

## What good looks like

Short declaratives. Numbers with units and periods. Named sources. Uncertainty stated once, precisely, where it matters. Headings that make an argument when read alone.
