# Register

A finished report reads as one of three documents: **a scientific report**, **a
consultancy report**, or **a hybrid narrative article**. Not a blog post, not a
chat answer. Pick one at the start of the draft, say which you picked, and hold
it to the last line: they mix badly, because they make different promises about
what the reader is supposed to do next.

## Which one

| | Scientific | Consultancy | Hybrid narrative |
|---|---|---|---|
| **Choose when** | The question is empirical; the reader needs to judge the evidence themselves | The question serves a decision; the reader needs to act | The answer is an argument that has to be followed from start to finish, for a reader who will read the whole thing |
| **Reader wants** | Whether to believe it, and how strongly | What to do, by when, at what cost | To understand how the pieces fit, and to be persuaded |
| **Opens with** | The finding and its confidence | The recommendation and what it turns on | An abstract, then a thesis the article goes on to earn |
| **Argues by** | Method, evidence, alternative explanations tested | Implication, option, trade-off | Sustained exposition across thematic sections |
| **Stance** | Impersonal. The evidence is the subject | Direct. The decision is the subject | Authored. The argument is the subject |
| **Structure** | Question → approach → findings → interpretation → limitations | Answer → why → what it means → what to do → what would change it | Abstract → introduction → thematic sections → conclusion |
| **Numbers** | With interval, n, and basis | With magnitude, timeframe, and sensitivity | With interval and basis, carried in the prose |
| **Ends with** | What remains unresolved | What to do next and what to watch | A synthesis that says what the argument adds up to |

**Register is not narration mode, and the two are chosen separately.** Register
decides what kind of document this is; narration decides who is reading it, and
how much of each mechanism has to be built for them. A consultancy-register
report can be narrated for specialists or for technically literate
non-specialists, and both carry the same claims, citations, caveats and
confidence. See `.claude/references/voice.md`, and record the mode in
`<run>/voice.md` before drafting.

Default to **consultancy** when the brief names a decision, **scientific** when it
names a phenomenon, and **hybrid narrative** when the brief asks for an article,
an essay, a piece of writing to be read straight through, or a case that has to
be built rather than reported. When genuinely both a decision and a phenomenon,
as in a technical due-diligence or a regulatory assessment, write consultancy
structure with scientific evidence handling, and say so in one line under the
title.

The hybrid is the one to choose deliberately rather than by default. It asks the
reader for a sustained read, so it earns its place when the argument genuinely
has to be followed in order. A reader who wants to act on a finding and stop is
badly served by it, and that reader gets consultancy register.

## What every register requires

These are not stylistic preferences. A document that breaks them is not a report.

- **Every quantity carries its basis.** Unit, period, population, and source
  definition. "€42.50" is not a figure; "€42.50 per unit, list price, Germany,
  2025 [E22]" is.
- **Uncertainty is stated once, precisely, where it bears.** Not hedged into every
  sentence, not omitted. A confident sentence about an uncertain thing is the
  worst available error; a sentence hedged four ways is the second worst.
- **Contested and single-sourced claims are attributed in-line.** "The trade
  association reports…", "one study reports…", "in the only located comparison…"
  — never "the market saw…". The narrator's voice is reserved for what multiple
  independent primaries agree on. Resting on one source is normal and carries no
  apology; presenting it in the plain declarative is the error.
  See `.claude/references/attribution.md`.
- **Derivations are shown.** If a number is computed, the inputs and the operation
  appear — in a note, a caption, or a parenthesis. An unexplained derived figure
  is unverifiable and will be quoted anyway.
- **Nothing is asserted that the evidence does not reach.** Including
  recommendations: if the research did not test it, it is not advised.

## Scientific register — specifics

- **Impersonal, but not passive-by-reflex.** "Three of five vendors do not publish
  pricing" beats "it was found that pricing was not published by three of five
  vendors". Impersonality is about removing the researcher as a character, not
  about removing agency from the sentence.
- **Method appears where it bears on belief, and nowhere else.** How the sample
  was constrained, what a source excludes, why one figure was preferred over
  another — that is interpretation and belongs in the text. "I then searched for…"
  is narration and is banned.
- **Alternative explanations are stated and addressed**, not left for the reader
  to raise. A finding presented without its best rival reads as advocacy.
- **Negative and null results are reported** with the same weight as positive
  ones. This is most of what separates a research report from marketing.
- **Limitations are specific and consequential.** "Data were limited" says
  nothing. "Install figures exist only at national level, so the SMB/enterprise
  split in §3 is inferred from shipment mix and should not be relied on below
  ±10pp" is a limitation.

## Consultancy register — specifics

- **Answer-first, and the answer is a claim.** The title is the finding. The
  first paragraph is the whole argument in four sentences. A reader who stops
  there must be correctly informed, not merely intrigued.
- **Headings make the argument when read alone.** Reading only the headings must
  reproduce the logic. `## Adoption stalled after the 2025 rule change` — never
  `## Market analysis`.
- **Every section ends in a "so what".** Evidence, then implication. A section
  that presents data and stops has handed the reader homework.
- **Options are comparable and costed.** If you present a choice, each option
  gets the same treatment: what it costs, what it wins, what it forecloses, and
  the condition under which it is right.
- **Recommendations are specific enough to refuse.** "Improve compliance
  processes" cannot be acted on or argued with. "Move Netherlands filings in-house
  before the March deadline; the external fee exceeds two FTE-months [E22]" can be
  both.
- **Exhibits do work.** In this register a chart is expected to carry a finding on
  its own, and the reader will look at exhibits before prose. See `visualize`.

## Hybrid narrative — specifics

The structure of a scholarly article in the humanities and the softer sciences,
carrying this workspace's evidence standards unchanged.

**The parts, in order.**

- **Title.** A main title, and a subtitle where the main title alone would be
  cryptic: `Title: Subtitle`. The main title may be evocative; the subtitle
  states the subject plainly.
- **Abstract.** 150–200 words, standing alone before the main text. It gives the
  thesis, the main lines of argument, and the conclusion. Someone who reads only
  the abstract must come away with the argument, not a teaser for it. It carries
  no citations and introduces nothing the article does not develop.
- **Introduction.** Sets the stage, states the thesis, gives the background the
  argument needs, and previews the shape of what follows. It takes a plain
  heading or none at all; where the article opens straight into the introduction,
  no heading is used and the abstract is what separates it from the title.
- **Thematic sections.** The body is divided by topic, not by research apparatus.
  `Historical context of the reagent market`, `Where the variability actually
  originates`, `Comparative economics`. Never `Methods`, `Results`, or
  `Discussion`: the hybrid's whole point is that the argument, rather than the
  procedure, provides the skeleton.
- **Conclusion.** Synthesises what the sections together establish and states
  what the thesis amounts to for the field. **It does not summarise the article
  section by section.** A conclusion that recapitulates is the commonest failure
  in this register, and it is the reason the section exists to be written last
  and hardest.
- **Notes**, when the citation system uses them.
- **Works Cited** or **Bibliography**, per the citation system.

**Headings carry the argument, and here they are topics rather than claims.**
This is the one place the hybrid diverges from consultancy register, where a
heading is a finding stated as a sentence. A thematic heading names the territory
a section covers and lets the prose make the claim. Reading the headings alone
should reproduce the *route* of the argument even though it will not reproduce
the argument itself.

**Transitions do real work.** Custom headings give the reader no template to
navigate by, so each section has to hand off to the next. A section that could be
moved elsewhere without anything reading oddly is a section that has not been
placed, and that is a structural defect rather than a stylistic one.

**One citation system, chosen before the first line and held throughout.** See
`.claude/references/citation-style.md`.

**Heading hierarchy is consistent and shallow.** One level for thematic sections,
one for subsections within them, and no third level. Mixed depth reads as a draft.

**What it does not license.** The hybrid is a shape, not a relaxation. Every
quantity still carries its basis, every contested claim is still attributed
in-line, uncertainty is still stated where it bears, and the limitations and the
data that could not be obtained still appear. An article that reads beautifully
and drops the caveats is the failure this register is most prone to, because the
prose rewards flow and the caveats interrupt it. They go in anyway.

## All three registers ban

The full list is in `anti-slop.md`, and the mechanically checkable half is
enforced by `voice.py lint`. The ones that specifically break register:

- **Chat voice.** "Great question", "Let's dive in", "Here's what I found", "I
  hope this helps", addressing the reader as "you" about the research process.
- **Meta-commentary on the document.** "This section will examine…", "As
  discussed above…", "Before we continue…". A report does not narrate itself.
- **Rhetorical questions as headings or transitions.** "So what does this mean?"
- **Essay throat-clearing.** "In an era of…", "It has long been understood
  that…". Start with the finding.
- **Emoji, exclamation marks, and second-person imperatives** outside a
  recommendations list.
- **Marketing adjectives** — *transformative, game-changing, cutting-edge,
  robust, comprehensive*. If magnitude matters, give the number.
- **Confidence borrowed from fluency.** A well-turned sentence about a `D2` source
  is a lie told well.

## The read-aloud test

Read the first paragraph and every heading aloud, in order. You should hear a
complete, specific argument, and you should be able to say which of the three
documents you are reading within about ten words. If it sounds like a chat reply
that grew section headings, the register is wrong and no amount of local editing
will fix it; restructure.

In the hybrid the test is different, because thematic headings do not state the
claims: read the abstract and then the headings. The abstract must already
contain the argument, and the headings must trace the order in which it is
built. If the headings could be shuffled without loss, the article has not
decided what it is arguing.
