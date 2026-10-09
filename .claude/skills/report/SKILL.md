---
name: report
description: Write a research report from gathered evidence — scientific or consultancy register, answer-first structure, tables and charts as numbered exhibits, every claim carrying its evidence ID, calibrated confidence language, visible placeholders for data that could not be obtained, and no filler. Use when turning research notes or evidence.jsonl into a written deliverable, drafting or rewriting a report/memo/brief/summary, or when the user asks for findings written up. Enforces the anti-slop rules; pairs with /verify and /critique before shipping.
disable-model-invocation: true
---

# Report

Inside `/research-pipeline` this skill runs in a `report-writer` agent, so the
draft never enters the orchestrating thread. Typed on its own, it runs here.

You are writing for a reader who will act on this and has no patience. Assume they
read the first paragraph, the headings, and the exhibits.

The output is **a scientific report, a consultancy report, or a hybrid narrative
article**, never a chat answer with headings. Read `references/register.md` and
pick one before the first sentence; it decides structure and how numbers are
presented. Say which you picked when you hand the draft over.

**Then settle the voice, before the first sentence and not after it.** Register
decides what kind of document this is; narration decides who is reading it, and
the author's profile decides how a sentence is built. Read
`.claude/references/voice.md`, comply with `<run>/voice.md` if it exists, and
invoke `/narrator` to choose and record the mode if it does not. The two modes,
`scientific` and `explanatory`, carry identical claims, citations, caveats and
confidence; they differ in how much of the mechanism is built for the reader.

Rewriting a finished report into the other mode is expensive, and choosing the
mode after drafting is the most common way that cost gets incurred.

## Structure

```markdown
# <Specific claim as title, not a topic label>

**Answer:** 2–4 sentences. The finding, the confidence, and the one caveat that
could change it. A reader who stops here must not be misled.

## <Finding as a sentence>
Evidence, then implication. [E7][E12]

## <Finding as a sentence>
…

## What would change this
The specific observation that would overturn the answer, and where to watch for it.

## Limitations
Coverage gaps, weakest load-bearing source (Admiralty grade), unresolved
contradictions, and every angle in coverage.md marked GAP or THIN.

## Data still to obtain
Each hole, why it is missing, and the specific step that closes it.
Omit this section only when there are none.

## Sources
[E7] Title — Publisher, 2025-03-11. https://… (primary, B2)
```

Headings are **findings, not topics**, in scientific and consultancy register.
`## Adoption stalled after the 2025 rule change` beats `## Market analysis`.
Reading only the headings must reproduce the argument. The hybrid narrative
register inverts this: its headings are thematic and the prose carries the
claims. See below.

### Hybrid narrative article

When `register.md` selects the hybrid, the shape is an article rather than a
report:

```markdown
# <Main title>: <Subtitle stating the subject plainly>

## Abstract

150–200 words, standing alone. The thesis, the lines of argument, and the
conclusion. No citations. Nothing that the article does not go on to develop.

<Introduction: no heading, or a plain one. The stage, the thesis, the background
the argument needs, and the shape of what follows.>

## <Thematic heading naming the territory, not the claim>
Sustained exposition. Evidence carried in the prose. [E7][E12]

## <Thematic heading that follows from the one before>
…

## Conclusion
What the sections together establish, and what it amounts to. Never a
section-by-section recap.

## Limitations
Coverage gaps, weakest load-bearing source, unresolved contradictions, and every
angle in coverage.md marked GAP or THIN.

## Data still to obtain
Each hole, why it is missing, and the step that closes it.

## Sources
[E7] Title — Publisher, 2025-03-11. https://… (primary, B2)
```

Three things this shape does not change. The master still cites by `[E#]` and
still ends in `## Sources`: the citation system the reader sees is applied at
export, and `## Works Cited` or `## Bibliography` is what `references.py`
writes into the derived copy. `## Limitations` and `## Data still to obtain`
survive into the article unchanged, because an article that reads well and drops
its caveats is the specific failure this register invites. And the abstract is
written last, from the finished piece, never first from the plan.

Order sections by decision-relevance, never chronologically by how you researched.
Nobody wants your research narrative.

**Where the question contained a hypothesis** — the user's, or one the research
raised — the report states it, states what would have falsified it, and reports
the outcome. A hypothesis that failed is a finding and ships as one; quietly
dropping it and writing up only what survived is the selection bias `critique`
exists to catch.

**The document is a narrative, not a list of findings.** Each section follows from
the one before it, and the reader can state the argument after one pass. Sections
that could be reordered at random are a symptom that the report has not decided
what it is arguing.

## Citation discipline

- Every sentence with a fact carries `[E#]` at its end. Multiple facts → multiple IDs.
- No evidence ID → the sentence is either your labelled inference ("this
  suggests…") or marked `[UNVERIFIED]`. Those are the only three states.
- **Never write a citation you have not verified exists** in `evidence.jsonl`.
  Check with grep, don't recall.
- Attribute contested claims in-line: "according to <source>, …". Never launder a
  vendor's number into the narrator's voice.
- **Charts cite too.** Every figure's `source` field carries `[E#]`, and every
  number plotted traces to those rows.

## Calibrated language

Match the word to the evidence, and never upgrade:

| Evidence | Language |
|---|---|
| Multiple independent primaries agree | "X is" |
| One primary, uncontested | "Chen et al. report X", "one study reports X" |
| Indirect / partial | "the available evidence suggests" |
| Contested | "sources disagree: A reports…, B reports…" |
| Absent | "no source found; this remains open" |

Silence about uncertainty is a form of inaccuracy. State it once, plainly, and
move on — don't hedge every sentence.

**A claim resting on one source is not a defective claim** — it is the normal
state of evidence, and it ships with the attribution in the sentence rather than
a hedge or an apology. The bare declarative is reserved for what multiple
independent sources agree on. Forms and cases: `.claude/references/attribution.md`.

## Exhibits

Quantities that have a *shape* — a ranking, a trend, a gap, a composition — go in
a chart. Everything else goes in a table, and tables are the default: they are
searchable, quotable, and survive every export intact.

Charts are written as ```figure blocks holding their data as JSON, so the numbers
stay auditable and the report re-renders in any style. Read the `visualize` skill
before writing the first one — it covers which findings earn an exhibit, the spec
fields, exhibit numbering, and `[[F2]]` cross-references.

Every exhibit is referenced from prose, and the prose states the finding. A reader
who skips the figures must lose nothing.

## Data you could not obtain

Build the section anyway, with the holes visible and labelled. Syntax, the three
kinds of hole, and the `## Data still to obtain` section: `.claude/references/gaps.md`.

## Is a report the right output?

A report is the deliverable for a question with several parts, a decision riding
on it, or an explicit request for a document. For anything smaller, the correct
output is **a short plain answer in chat and no document at all** — see
`.claude/references/response-scale.md`.

This is the one place the two scales must not be confused. When a report *is*
warranted, it takes the full register and the full structure; there is no
lightweight or simplified report in this workspace. A document that hedges toward
chat voice because the question felt small is the register failure
`references/register.md` exists to prevent.

## Length and completeness

Default to **complete**: every sub-question in `brief.md` answered, every
dimension in `coverage.md` accounted for, every material caveat stated, every
contradiction surfaced, every gap named. Do not drop a finding because the report
is getting long. Condense only when the user asks for a brief, a summary, or a
length limit.

Completeness is coverage, not word count. The two failure modes are opposite and
both real:

- **Under-delivery** — a sub-question quietly unanswered, a contradiction omitted
  because it complicated the story, a caveat left out. This is the worse failure:
  the reader can't see what's missing.
- **Padding** — preamble, restatement, methodology narration, filler prose.
  Detectable, because padding is the prose with no `[E#]`.

Cut padding to zero; cut substance never. A well-evidenced ten-page report is
correct if the question needed ten pages.

## The document contains no trace of the pipeline that made it

The reader gets a report, not a research log. Nothing below ever appears in the
deliverable — not in the body, not in a footnote, not in the confidence statement:

- Internal filenames — `draft.md`, `coverage.md`, `evidence.jsonl`,
  `verification.md`, `critique.md`, `repair-log.md`, `rounds/`.
- The machinery — scouts, subagents, digests, batches, rounds, passes, prompts,
  "the audit script", tool names.
- Severity tags and subagent return formats — `[BLOCKING]`, `VERDICT:`, `CHECKED n`,
  `FINDINGS`, `NOT FOUND`.
- Self-reference — "I searched", "my analysis found", "this report will".
- Round-shaped headings. The document has no rounds.

The **findings** of that machinery do ship, stated as facts about the evidence:
*"the install figures rest on a single vendor survey"*, never *"verification.md
graded this D2"*. Confidence, coverage, and limitations are the report's own
claims about its own evidence — write them that way.

## Before finishing

The mechanical checks run themselves: the hook calls `gate.py` after every write
and hands back anything it catches. What is left here is the judgement a script
cannot make.

1. Read `references/register.md` and check the draft still reads as the document
   you chose. This is the check that catches a report drifting into chat voice.
2. Read `references/anti-slop.md` and strip anything it names.
3. Work the repetition and diction pass the gate prints as `ECHO`, `ECHO-NEAR`,
   `OPENER` and `DICTION`. These fail nothing, because only a reader can tell a
   term of art from a lazy verb, and a drafting thread writes the same verb four
   times in a paragraph without noticing. Terms of art stay fixed and go into
   `outputs/<slug>/voice-terms.txt`; ordinary echoes are removed by restructuring
   the sentence, and only then by a synonym that carries the same meaning
   exactly. Doctrine: `.claude/references/diction.md`.
4. Open `coverage.md` and confirm every `GAP`, `THIN`, and `CONTESTED` row appears
   somewhere in the report. A gap the researcher saw and the reader cannot is
   worse than one nobody noticed.
5. Every source you could not read is registered, so the author can go and fetch
   it:

   ```bash
   python3 .claude/scripts/wanted.py check outputs/<slug>
   python3 .claude/scripts/wanted.py build outputs/<slug>
   ```

   A `[NEEDS DATA]` hole with no row naming the URL and the reason it failed is
   a hole the author cannot close. Doctrine: `.claude/references/gaps.md`.
6. `python3 .claude/scripts/external_index.py scan outputs/<slug>` — a file the
   author supplied and nobody read is a hole in the draft, not a housekeeping
   item. Doctrine: `.claude/references/external-data.md`.

If you need the gate verdict without writing to the file, run it directly:

```bash
python3 .claude/scripts/gate.py outputs/<slug>/draft.md
```

## draft.md is not the deliverable

`report.md` is the single master document and always holds the latest state.
`draft.md` is a working file that stops being read the moment `/repair` finishes.

The promotion happens **once**, at the end of the first repair pass:
`cp <run>/draft.md <run>/report.md`, then every later edit — repair, expand,
correction — is made to `report.md` in place. Never regenerate `report.md` from
`draft.md` after that: `draft.md` is stale by definition, and the sample failure
this prevents is auditing or exporting a superseded file.

## Numbers

Report figures at source precision — no rounding that changes meaning, no invented
precision. Always carry the unit, the period, and the basis ("shipments, TTM to Q3
2025, global"). A bare number is a future error.

Derived figures show their derivation — inputs cited, operation stated. An
unexplained computed number is unverifiable and will be quoted anyway.
