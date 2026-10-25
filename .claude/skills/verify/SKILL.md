---
name: verify
description: Adversarially fact-check a draft or set of claims before it ships — extract every checkable assertion, trace it to a primary source, grade sources on the Admiralty scale, and catch fabricated citations, circular reporting, and unsupported numbers. Use before publishing any report, when the user asks to fact-check, verify, audit, or sanity-check claims, or when a draft's sourcing is in doubt. Writes a verdict ledger, does not rewrite the draft.
disable-model-invocation: true
---

# Verify

**Which document.** When the run has more than one master (an audit and a revised
document), act on the one the request names, or ask; then read it wherever this
skill says `report.md`. A revised document keeps its own form and citations.
Doctrine: `.claude/references/masters.md`.

A quality gate, not an editor. You produce verdicts; `/repair` acts on them.

**Scope comes from the request.** Inside the pipeline, verify the whole draft.
Typed on its own against a finished run, with a claim, an `[E#]` or a section named
(`/verify <run> E42`, `/verify <run> §3`), check only that: `python3 .claude/scripts/section_map.py <run> --find E42` names
the sections citing a source and `--show "<heading>"` prints one section with line
numbers. Extract the claims there and send those to the verifiers. The
master is `report.md` once it exists (`runmeta.py` names it). The standard does not
change with the scope: every named claim is re-fetched exactly as in a full pass.
Append the result to `verification.md` under a heading that names the date and the
scope, so a later full pass sees what was already checked.

## 0. Run the mechanical audit first

```bash
python3 .claude/scripts/audit_citations.py outputs/<slug> draft.md
```

It finds dangling `[E#]` refs, malformed evidence rows, duplicate fetches, single-domain risk, and unsourced paragraphs — for zero model tokens. Fix what it reports before spending subagents on the rest.

Then check the quotes mechanically, against the library's stored copies:

```bash
python3 .claude/scripts/library.py check outputs/<slug> [--ids E4,E9 | --file <to-verify list>]
```

`MATCH` means the quote is verbatim in the page as a script fetched it on a recorded
date: the verifier does not re-fetch that row, and judges only whether the draft's
sentence says what the quote says (scope, qualifiers, causation, attribution, and
whether a newer figure supersedes it). `STALE`, `PARTIAL`, `ABSENT` and `NO-COPY`
rows are re-fetched exactly as before. Pass each batch its rows' results.

Then check what the author supplied:

```bash
python3 .claude/scripts/external_index.py scan outputs/<slug>
```

An unread file in `external_data/` can confirm a claim currently resting on a secondary source, or break one outright. It is checked here as well as during research because authors add files after reading a draft, which is exactly when a supplied primary is most likely to contradict something. Doctrine: `.claude/references/external-data.md`.

A claim sourced **only** to author-supplied material is verifiable inside the run folder and nowhere else. Verify it against the file, grade it normally, and record that limit — it belongs in the report's `## Limitations` when the claim is load-bearing.

## 1. Extract claims

Read the draft **once**. Extract every assertion that could be wrong into `outputs/<slug>/verification.md`:

- numbers, dates, percentages, rankings, superlatives
- causal claims ("X caused Y", "because of")
- attributions ("X said", "the study found")
- existence claims (a product, law, paper, person, feature)
- negative claims ("no jurisdiction requires…") — the most fragile kind

Skip: definitions, the author's own reasoning, hedged framing. Verifying opinion is wasted tokens.

## 2. Delegate the checking

Spawn `source-verifier` subagents in **one message**, batched ~10 claims each. Give each batch the claims, their `[E#]`s, and the run dir. They re-fetch and return verdicts.

The main thread must not re-fetch sources itself — that is what the isolation is for.

## 3. Verdicts

Each claim resolves to exactly one:

| Verdict | Meaning |
|---|---|
| `SUPPORTED` | Primary/reliable source states it; quote matches |
| `PARTIAL` | True with a material qualifier the draft omits |
| `WEAK` | Low-grade or unreliable sourcing — **not** merely singular |
| `CIRCULAR` | Multiple citations collapse to one origin |
| `UNSUPPORTED` | No cited source states it |
| `CONTRADICTED` | A better source says otherwise |
| `FABRICATED` | Cited source does not exist, or does not contain this |
| `STALE` | Was true; superseded |

**One sound source is not a defect.** A single A1 primary that plainly states the claim is `SUPPORTED`; the Fix line records that the draft must attribute it in text, not that the claim must be weakened. Reserve `CIRCULAR` for manufactured corroboration — several citations collapsing to one origin. See `.claude/references/attribution.md`.

`FABRICATED` and `CONTRADICTED` block publication. Escalate them in your summary to the user immediately, not just in the file.

## 4. Grade the sources

Apply the Admiralty scale in `references/admiralty.md` to each source. A report resting on `C3` or worse must say so in its limitations section.

## 5. Ledger format

Append to `outputs/<slug>/verification.md`:

```markdown
## C4 — "US installs grew 40% in 2025"
- **Verdict:** PARTIAL (B2)
- **Draft says:** grew 40% in 2025
- **Source says:** "shipments rose 40% in the twelve months to Q3 2025" [E7]
- **Gap:** shipments ≠ installs; window is trailing-twelve-month, not calendar
- **Fix:** restate as shipments, TTM to Q3 2025
```

Every entry gets a **Fix** line. A finding without a repair instruction is half a finding.

## 6. Summarize

Report counts by verdict, the blocking issues, and overall confidence (High/Medium/Low) with the reason. Never report "all verified" unless every claim was actually checked — say how many were checked out of how many extracted.

## Anti-patterns

- Marking a claim SUPPORTED because it *sounds* right, or because the model already believes it. Belief is not evidence.
- Accepting the draft's own citation as proof the source says it — re-read the source.
- Counting three articles citing one press release as three sources. That is `CIRCULAR`.
