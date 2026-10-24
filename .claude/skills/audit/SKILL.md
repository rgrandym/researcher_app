---
name: audit
description: Research-grade assessment of a document the author supplied (business plan, investor deck, cash-flow model, two-pager), finding what is right, wrong, stale, unsupported, inconsistent or missing for its readers, and writing it up as a cited audit report. Use when the author asks to review, assess, audit, check or improve an existing document from external_data, before proposing changes with /changes.
disable-model-invocation: true
---

# Audit

Research the author's document the way `/research-pipeline` researches a
question. The question is: **what does this document need to be right, current
and complete for the people who will read it?** The output is `report.md`, an
audit with evidence. It changes nothing in the document; that is `/changes`.

Doctrine: `.claude/references/revision.md`. Read it first.

## 1. The run and the subject

The document lives in a run's `external_data/`. If the author named a run, use
it; if the file sits in one run, use that; otherwise scaffold one with
`new_run.sh` and ask the author to drop the file into its `external_data/`.
Record the request in `prompt.md` as usual.

Declare and extract every document the author wants assessed:

```bash
python3 .claude/scripts/subject.py add <run> "<file under external_data>" --role subject
python3 .claude/scripts/subject.py add <run> "<file>" --role template     # a design to copy, if any
python3 .claude/scripts/subject.py extract <run>
```

When the request is ambiguous about which files are subjects, ask one question
(`AskUserQuestion`, multi-select, listing the files). A PDF can be audited; it can
only be rebuilt, not edited, so ask in the same question whether the author has
its `.pptx` or `.docx`.

## 2. Read the subject into claims

Delegate when `text.md` is long (over about 4,000 words, or several subjects): a
`research-scout` reads `text.md` and writes the claims file, and returns a digest.

`subjects/<slug>/claims.md`, one row per checkable statement:

| Part | Claim (verbatim, short) | About | Load-bearing | Check |
| --- | --- | --- | --- | --- |
| P013 | cell-culture media USD 9.7bn in 2026 | world | yes | source and date |
| P015 | team: CSO with Cytiva, Adaptimmune roles | company | no | author's knowledge |

`About` is `world` (needs a source) or `company` (the author's knowledge, cited as
the document). Mark every figure, date, competitor, price, regulation and market
statement. With several subjects, add a **consistency** table: every figure that
appears in more than one document, with each document's value. Disagreements are
findings.

## 3. What the document should contain

Write `subjects/<slug>/checklist.md`: what a document of this kind must contain
for its audience (a pre-seed deck for UK angels, an SEIS/EIS business plan, a
lender's cash-flow forecast), and whether this one has each item, weakly or not
at all. The expectations themselves are researched and cited, never recited from
memory: what investors, HMRC or lenders actually ask for.

## 4. Brief and research

`brief.md` comes from the claims and the checklist:

- verify the load-bearing `world` claims, current figures first;
- source what the checklist found missing;
- anything the author asked for in the command.

Then run the research pipeline from its stage 1, reading
`.claude/skills/research-pipeline/SKILL.md`: gap hunt, scouts, coverage audit,
draft, verify, critique, repair. Scouts take the claims file as their
starting list. Existing runs' evidence is a head start (`kb.py runs`).

## 5. The audit report

`report.md` follows the report skill, with this spine:

1. **Verdict.** Is the document ready for its readers, and what most needs to change.
2. **What holds.** Claims the evidence confirms, briefly.
3. **What is wrong or stale.** Each with the document's text, what the evidence
   says, and the correction.
4. **What is missing.** From the checklist, in order of what the reader needs.
5. **What is weak.** Argument, structure, emphasis; claims stated more strongly
   than their support.
6. **Consistency across documents.** Figures that disagree between subjects.
7. **Recommended changes**, in priority order, each naming where in the document
   it lands.
8. **What only the author can supply.** Registered with `wanted.py`.

Locations are named as a reader would find them ("section 5, second paragraph",
"slide 4"), never by part ID: the report carries no trace of the pipeline.

## 6. Hand-over

Report the verdict in a few sentences, the counts (corrections, gaps, weak
points, inconsistencies), and the next step: `/changes` to turn the
recommendations into a change plan the author can accept line by line.
