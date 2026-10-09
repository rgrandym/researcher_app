# Scaling the response to the question

Shared doctrine. `research-pipeline`, `research`, `report` and `compose` point
here.

The workspace's failure mode in both directions is real and neither is cheap:

- **Over-answering.** A four-word question returns a run folder, six scouts, and a
  twelve-page document. The user wanted a number. This wastes their attention and
  your budget, and it buries the answer they asked for.
- **Under-answering.** A decision-grade question returns three confident sentences
  with no sourcing and no caveats. This is worse, because the user cannot see what
  is missing.

Judge the tier **before acting**, say which you picked in one line, and re-judge
as you learn more. The tier is a running estimate, not a commitment.

## The four tiers

| Tier | The question is | You produce | Run folder |
|---|---|---|---|
| **0 · Direct** | A fact, a definition, a "what is X", a yes/no you can source in one fetch | 1–4 sentences of plain language in chat, with the link | No |
| **1 · Short sourced** | A real question with one answer and a caveat or two | A few paragraphs in chat, cited, with the caveat stated | Only if you fetched enough to be worth keeping |
| **2 · Report** | Several sub-questions, or a decision rides on it, or the user asked for a document | The full pipeline and `report.md` | Yes |
| **3 · Deep** | Contested, high-stakes, or adversarial — someone will argue with the result | Pipeline plus dissent scout, two critics, two repair rounds | Yes |

**Running Deep on a Tier 0 question is the most expensive mistake available here.**
Producing Tier 0 for a Tier 2 question is the most damaging one.

## What decides the tier

Ask these in order and stop at the first that lands:

1. **Did the user ask for a document?** "Write me a report", "do a deep dive", "I
   need something to send" → Tier 2 minimum, regardless of how simple the topic
   looks. They named the deliverable; that is not yours to downgrade.
2. **Does an action or decision depend on the answer?** If they will spend money,
   commit to a design, or brief someone else → Tier 2.
3. **Is it contested, or would an informed person disagree?** → Tier 3 if the
   disagreement is the point; Tier 2 otherwise.
4. **Does answering it require more than one line of enquiry?** Count the genuinely
   independent sub-questions. Two or more → Tier 2.
5. **Otherwise → Tier 0 or 1**, split on whether the honest answer needs a caveat.

## Register at each tier

At Tiers 0 and 1 you are answering a person, not publishing. Write **plain,
direct, and short**: lead with the answer, use ordinary words, explain a technical
term the first time it appears, and skip the scaffolding entirely — no headings on
a three-sentence answer, no "Answer:" label, no confidence block, no limitations
section. A reader should get it in one pass without a glossary.

At Tiers 2 and 3 the *document* takes the scientific or consultancy register
(`report/references/register.md`) without exception. The chat message that
delivers it stays short: what you found, what it turns on, where the file is.

**Plain language never means lower standards.** Every tier obeys the
non-negotiables: nothing asserted that a source doesn't say, no citation written
from memory, no invented figure, uncertainty stated where it bears. A Tier 0
answer is shorter, not looser. If you cannot answer in four sentences without
overstating, that is the signal you are at Tier 1, not permission to guess.

## The compose lane

A request to write something the author signs (a CV, a letter, an answer, a
paragraph of theirs to develop) runs on the same logic with its own three
tiers, set out in the `compose` skill. Two of the questions above change:

- **"Did the user ask for a document?"** becomes "will a named reader receive
  this?" A letter that gets sent takes a run folder and an independent review,
  however short it is. Rewording one sentence does not.
- **"Does an action depend on the answer?"** is nearly always yes in this lane,
  and it decides depth rather than the existence of a folder. A job application
  is a decision the author is asking someone else to make about them.

Research inside a compose run is a separate judgement: it happens when the
author asks for a claim to be checked, and not on your own initiative.

## Re-judging mid-flight

The initial tier is a guess made before the evidence exists. Change it when the
evidence says so, and say that you did:

- **Escalate** when a "quick" question turns out contested, when the first search
  surfaces a live disagreement, or when the answer depends on something the user
  did not mention. Say *"this is less settled than it looked — going wider"* and
  continue.
- **De-escalate** when a question that sounded big resolves to one authoritative
  primary source. Say so and hand back the short answer. Do not spend the
  remaining budget to justify the initial estimate. A Tier 2 question that turns
  out to have a Tier 0 answer is a good outcome and reporting it as one is honest.

Escalating past Tier 2 without saying so spends real money on the user's behalf.
Announce it; one line is enough.

## Length is an output, never a target

Length comes from evidence and analysis. It is never added to signal effort, and
never cut to signal efficiency.

- A Tier 0 answer that needs a caveat gets the caveat, even at five sentences.
- A Tier 2 report that fully answers its brief in four pages is finished at four
  pages. Do not pad it to look thorough.
- A Tier 2 report needing twelve pages gets twelve. Do not trim substance to look
  efficient — that is the under-delivery failure in `report`, and the reader
  cannot see what you removed.

The test at every tier: **could this be shorter without losing information the
reader needs?** If yes, cut. **Is anything the reader needs missing?** If yes, add
it, whatever the tier said.
