# Gap hunt

The brief is the user's model of their question. It is reliably incomplete,
because if they knew what was missing they would have asked for it. A researcher
who answers only the stated sub-questions produces something true, narrow, and
quietly useless.

Two passes. The first runs **before** scouts go out and shapes what they look for.
The second runs **after** the digests land and decides whether the run is done.

Both write to `<run>/coverage.md`. That file is the ledger of what this
investigation looked at, what it found thin, and what it decided not to pursue —
and it is the difference between a gap that was handled and a gap that was
missed.

---

## Pass 1 — before searching: sweep the dimensions

Walk every row. Most will be irrelevant to a given question; that is fine and
takes seconds. The ones that land are usually the difference between a report the
reader acts on and one they have follow-up questions about.

### The question itself

- **Definition.** Is the key term contested? "Adoption", "cost", "safety",
  "market" mean different things to different sources, and a report that averages
  three definitions is measuring nothing. Find how the primary sources define it.
- **The real decision.** What will the reader *do* differently depending on the
  answer? If you cannot name the action, the question is underspecified — and the
  sub-questions will be too.
- **The implied comparison.** "Is X good?" always means "compared to what?" Name
  the alternative explicitly; if the brief doesn't, that is your first gap.
- **Magnitude vs direction.** Does the reader need to know *whether*, or *how
  much*? These need different sources and the second is far harder.

### Scope

- **Temporal.** What period does the answer cover, and is the most recent data
  point actually recent? Check for a regime change — a rule, a ruling, a merger,
  a technology shift — that makes older evidence inapplicable rather than merely
  old.
- **Geographic / jurisdictional.** Does the finding travel? Evidence from one
  regulatory regime routinely fails to generalise, and reports built on
  US-or-EU-only sources that read as global are a standing failure of this genre.
- **Population or segment.** Whose experience is this? Enterprise vs SMB, urban
  vs rural, incumbent vs entrant, early vs late adopter. An average across
  segments that behave differently describes nobody.
- **Unit and denominator.** Per what? A raw count doing a rate's job is the most
  common quantitative error in research writing.

### Evidence structure

- **Who would know?** Enumerate the classes of source that *could* answer this —
  regulator, standards body, trade association, academic literature, company
  filings, court records, procurement records, patents, job postings, incident
  databases. Then note which you actually plan to search. The unsearched classes
  are your known blind spots.
- **Who has an incentive to be wrong?** Vendor surveys, sponsored studies, trade
  bodies, and consultancies with a practice to sell all produce real data with a
  predictable lean. Identify the interested parties before reading them, not
  after.
- **Where is the dissent?** Every live question has informed people who disagree.
  If you cannot name them, you have not found the debate — you have found one
  side of it. Search explicitly for critiques, failed replications, regulatory
  objections, and dissenting minority opinions.
- **What does the negative case look like?** Failures, abandonments,
  non-adopters, jurisdictions that considered and declined. These are
  systematically under-published, so they must be searched for deliberately;
  absence of counter-evidence is almost always absent searching.
- **Is there a review?** A systematic review, meta-analysis, or regulator's
  impact assessment does months of this work for you and names the disagreements.
  Look for one before doing anything else.

### Disciplinary lenses

A question researched from one field's literature returns that field's answer.
Name the disciplines that have something to say about this question, then check
which you are actually about to search. The unsearched ones are blind spots, and
they are where the report's most surprising finding usually is.

The recurring set: **technical/scientific** (does it work, and by what
mechanism), **economic** (what it costs, who pays, what the market structure
does), **legal/regulatory** (what is permitted, what is mandated, what is
changing), **operational** (can it be deployed at scale, by whom, with what
lead time), **historical** (has this been tried, and what happened),
**social/behavioural** (who adopts it, who resists, and why), and
**ethical/political** (whose interests it serves).

Most questions are dominated by two or three. A question that looks purely
technical and turns out to be decided on regulatory or operational grounds is
the standard failure of a single-lens report — and a lens is cheap to sweep and
expensive to add after the draft exists.

### Hypotheses

- **State the hypothesis the question implies**, even when the user did not. "Is
  X causing Y?" is a hypothesis; so is "should we switch to X".
- **State what would falsify it** before searching. A hypothesis with no
  disconfirming observation defined is not being tested, it is being illustrated.
- **Search for the disconfirmation specifically.** Confirmation bias in research
  agents is a query problem: they query the hypothesis, find it, and stop.
- **Report the outcome either way.** A hypothesis that failed is a finding, and
  it goes in the report. Dropping it and writing up only what survived is the
  selection bias `critique` will find.

### Causation and mechanism

- **Mechanism.** If the report will claim X causes Y, can you state *how*? A
  correlation with no plausible mechanism and a mechanism with no evidence are
  both findings — different ones.
- **Rival explanation.** What else would produce this pattern? Name the best
  alternative now; you will need it in `critique` regardless.
- **Confounders and selection.** Who is in the sample and who dropped out?
  Survivorship is invisible unless you look for it.
- **Second-order effects.** What does the answer cause next? A finding that stops
  at first-order is where "the policy worked" hides "and the activity moved
  offshore".

### Practical

- **Cost, feasibility, timeline.** If the report implies an action, the reader
  needs the price and the lead time. These are almost never in the brief and
  almost always needed.
- **Legal and regulatory constraints** on the implied action.
- **Who bears the cost, and who captures the benefit?** Different parties, often.

---

## Pass 2 — after the digests: audit the coverage

For each sub-question and each dimension flagged in Pass 1, assign one status:

| Status | Test |
|---|---|
| `COVERED` | ≥2 independent sources, at least one primary, no live contradiction |
| `THIN` | One source, or all sources trace to one origin, or only vendor/opinion grade |
| `CONTESTED` | Sources disagree materially and the disagreement is unresolved |
| `GAP` | No usable source found |
| `OUT OF SCOPE` | Deliberately excluded — **with the reason, in writing** |

Then act:

- `THIN` on a **load-bearing** claim → re-scout with a narrower brief. Thin on a
  peripheral one → keep it and say so in the report.
- `CONTESTED` → a contradiction is a finding. Spawn one scout to adjudicate: find
  the primary sources behind each side and establish whether they measured
  different things, different periods, or genuinely disagree.
- `GAP` → classify it as **unpublished**, **access-restricted**, or **not
  searched**. The three mean different things to the reader and only one of them
  is a task they can complete: `.claude/references/gaps.md`.

**Every `GAP` and every `THIN` reaches the report.** A gap the researcher noticed
and the reader cannot see is worse than one nobody noticed, because the document
now claims completeness it does not have.

---

## coverage.md

```markdown
# Coverage — <run>

## Sub-questions
| # | Sub-question | Status | Sources | Note |
|---|---|---|---|---|
| 1 | What changed in the 2026 rules? | COVERED | E1–E9 (4 primary) | |
| 2 | What did compliance cost? | THIN | E22 only | single vendor survey; load-bearing → re-scouted r2 |
| 3 | Did adoption change? | CONTESTED | E7 vs E12 | shipments vs installs; adjudicating |

## Dimensions swept
| Dimension | Status | Note |
|---|---|---|
| Definition of "adoption" | COVERED | registry definition adopted; stated in report |
| Non-adopters / failures | GAP (not searched) | no source class identified; declared in Limitations |
| Dissenting view | COVERED | industry objection E31, regulator response E32 |
| Segment split (SMB vs enterprise) | GAP (unpublished) | no source segments below national level |
| Cost of the implied action | OUT OF SCOPE | user excluded pricing in brief |

## Decisions
- Excluded non-EU jurisdictions: brief scoped to EU. Flagged in report as a
  generalisation limit.
```

---

## The two questions to ask before declaring the research done

1. **What would an expert in this field immediately ask that this report cannot
   answer?** Write it down. If it is answerable, answer it. If it is not, it
   belongs in Limitations in those words.
2. **If the conclusion is wrong, what is the most likely reason?** Then go look
   for that specific thing. This is the single highest-yield search in any
   investigation, and it is the one that never appears in a brief.
