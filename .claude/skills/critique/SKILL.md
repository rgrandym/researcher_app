---
name: critique
description: Red-team a draft report or plan — attack its reasoning, hidden assumptions, cherry-picked evidence, overreaching conclusions, and structural weaknesses, then rank findings by severity. Use when the user asks to critique, grill, stress-test, poke holes in, or review a report/plan/argument, or as the stage after /verify and before /repair. Complements /verify: verify checks facts, critique checks thinking.
disable-model-invocation: true
---

# Critique

**Which document.** When the run has more than one master (an audit and a revised
document), act on the one the request names, or ask; then read it wherever this
skill says `report.md`. A revised document keeps its own form and citations.
Doctrine: `.claude/references/masters.md`.

`/verify` asks "is this true?". The independent critic asks **"does this hold up?"** — true facts assembled into a wrong conclusion is the failure this stage catches.

**Spawn `report-critic` from `.claude/agents/report-critic.md` for every invocation,
including a standalone `/critique`.** Give it the run path, the current master
(`report.md` when present, otherwise `draft.md`), the author's requested section
or scope, and this skill. If the request refers to a hand edit, run
`saved_check.py` first and wait for the save when it reports one missing. The critic
reads the document from disk and writes `outputs/<slug>/critique.md` itself.
The thread that wrote the draft or repair must never conduct the critique, edit
its findings, or write `critique.md` on the critic's behalf. Wait for the critic
to finish, then check that the file exists and report its verdict. If spawning
fails, stop with the critique stage incomplete and tell the author why. Do not
produce a same-thread substitute.
Also check that the critic wrote `critique-questions.json` after the critique,
with an empty `questions` list when no author decision is needed. The app uses
this file to prepare the questions before repair.

The critic does not edit the article. Findings can be applied later with
`/repair`, after the author has read them.

## Attack surfaces

Work these in order; stop when you have the real problems, not a quota.

1. **Does the answer follow from the evidence?** Map each conclusion to the claims supporting it. Look for the gap where the argument jumps.
2. **Hidden assumptions.** What must be true, unstated, for the conclusion to hold? Name each one and whether the report tests it.
3. **Selection bias.** What evidence class is *absent*? Failures, non-adopters, dissenting jurisdictions, the years that don't fit the trend. Absence of counter-evidence is usually absent searching, not absent reality.
4. **Base rates and denominators.** Is a raw count doing the work of a rate? Is growth measured off a trivial base? Survivorship?
5. **Causation smuggled in as correlation.** Check every "because", "driven by", "led to", "as a result".
6. **Alternative explanation.** State the best rival hypothesis explicitly, and whether the evidence distinguishes it from the report's. If it doesn't, that's a finding.
7. **Confidence calibration.** Is the language stronger than the sourcing? Any `WEAK`/`CIRCULAR` claim carrying a conclusion? A single-sourced claim is a finding **only** when it is unattributed, load-bearing and written as settled, or when the source is an interested party — "only one source" is not by itself a finding (`.claude/references/attribution.md`).
8. **Coverage.** Read `coverage.md` against the report. Does every `GAP`, `THIN`, and `CONTESTED` row appear in the document? A gap the researcher recorded and the reader cannot see is a finding — the report is claiming a completeness it does not have.
9. **The angles nobody asked for.** Work `research/references/gap-hunt.md` Pass 1 against the finished draft, not the brief. What dimension would an expert in this field raise in the first thirty seconds — a definition, a segment, a jurisdiction, a second-order effect, a rival mechanism — that this report never mentions? An unexamined dimension is a finding even when the brief excluded it, because the reader is about to act on the document, not on the brief.
10. **Exhibits.** Does each chart's title claim what the data shows? Does any exhibit imply a comparison the evidence doesn't support — a truncated axis, a mismatched basis between series, a trend drawn through two points? Is any figure's number absent from `evidence.jsonl`?
11. **Placeholders.** Are `[NEEDS DATA]` holes honestly classified? Presenting an unsearched topic as unobtainable misrepresents the evidence — see `.claude/references/gaps.md`.
12. **Register and narrative.** Read the first paragraph and every heading aloud. Does it read as a scientific or consultancy report, or as a chat answer that grew headings? Does each section follow from the one before, or is this a list of findings in arbitrary order? See `report/references/register.md`.
13. **Voice.** Does this read as though a person wrote it, or as though a model did? Run `python3 .claude/scripts/voice.py lint <run>/report.md` and treat every hit as a finding. Beyond the mechanical list, look for the constructions a regex cannot catch: paragraphs built on an antithesis that the evidence does not actually contain, emphasis carried by adverbs rather than by content, transitions that announce a relation the sentences do not establish. Check the narration mode in `<run>/voice.md` is held evenly: a document that explains a term in section 2 and then uses three unglossed ones in section 5 has drifted, and a non-specialist reader falls off exactly there. Doctrine: `.claude/references/voice.md`.
14. **Diction and flow.** The same command prints `ECHO`, `ECHO-NEAR`, `OPENER` and `DICTION` lines: report the ones that are real, which means an ordinary word echoing inside a paragraph rather than a term of art doing its job. Then look for what the script cannot see: a synonym that quietly changed the strength of a claim ("reduced" where the source says "eliminated"), a term of art that drifted into three different words across a section, a paragraph opening on a subject nothing before it introduced, and a section whose paragraph openers read as a list rather than as an argument. Doctrine: `.claude/references/diction.md`.
14. **Pipeline leakage.** Does any internal filename, subagent, round, severity tag, or self-reference survive in the document? The reader gets a report, not a research log. `audit_citations.py` catches the common ones; you catch the paraphrased ones.
15. **Decision-usefulness.** Does it answer the question in `brief.md`? Could the reader act on it? What did they need that isn't here?

## Severity

- **Blocking** — conclusion doesn't survive. Answer changes.
- **Material** — conclusion holds but is overstated, under-qualified, or resting on one source.
- **Minor** — clarity, structure, missing context.

Rank blocking-first. Three blocking findings beat twenty minor ones; do not pad to look rigorous — a padded critique gets ignored wholesale.

## Format

```markdown
### [BLOCKING] Conclusion rests on shipments, but the question is about installed base
The answer generalises from [E7][E12], both shipment figures. Installs lag
shipments by 2–4 quarters in this sector and the report never bridges the gap.
**Fix:** either re-scope the answer to shipments, or source install data.
```

Every finding names the specific text and ends with a **Fix**. "This section is weak" is not a finding.

## Rules

- Attack the strongest version of the report's argument, not a strawman of it.
- No praise sections. If nothing is wrong with a section, say nothing about it.
- Say "no blocking findings" when that's true. Manufacturing objections to look thorough wastes the reader's judgment and your tokens.
- Do not re-verify facts here — read `verification.md` and build on it.
- A missing angle is a legitimate finding, but it must be *specific and material*. "Could cover more" is not a finding; "the report generalises from EU evidence and never states that the US regime differs on the load-bearing point" is.
