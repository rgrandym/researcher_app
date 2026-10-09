---
name: research
description: Run a sourced research investigation on a question — decompose it, fan out parallel scout subagents to read sources in isolated contexts, and land verbatim evidence in a run directory. Use whenever the user asks you to research, investigate, find out about, gather sources on, do a literature/market/competitive/background review, or answer a question that needs current or citable facts. Produces evidence.jsonl + notes/, not prose.
disable-model-invocation: true
---

# Research

Gather evidence. Do **not** write the report here — that is `/report`.

## 0. Does this question need a run at all?

Check `.claude/references/response-scale.md` first. A fact, a definition, or a
question answerable from one authoritative source is **Tier 0–1**: search, fetch,
answer in chat in a few plain sentences with the link, and stop. Scaffolding a run
folder for it wastes the user's budget and buries their answer in ceremony.

Everything below applies from **Tier 2** — several sub-questions, a decision
riding on the answer, or a document the user asked for.

If you start at Tier 2 and the question collapses to one primary source, say so
and hand back the short answer rather than spending the rest of the budget
justifying the estimate.

## 0b. Has the workspace already covered this ground?

```bash
python3 .claude/scripts/kb.py runs "<the question>"
```

If an existing run overlaps heavily (half or more of the question's terms, on the
same subject rather than a shared word or two), ask the author one question before
scaffolding: extend that report with `/expand`, or start a new one? Name the run
and what it already covers. A new report that re-establishes a finished one's
evidence spends the whole research budget twice and leaves two documents to keep
in step. If the author says new, proceed, and treat the old run's evidence as a
head start (section 2c).

## 1. Scaffold the run, capture the prompt

```bash
bash .claude/scripts/new_run.sh "<short-slug>" "<the user's request, verbatim>"
```

This creates `outputs/YYYY-MM-DD-<slug>/` with `prompt.md`, `notes/`, `export/`, and an empty `evidence.jsonl`. Everything for this run goes in that folder — nothing elsewhere.

`prompt.md` records the request **word for word**, not your summary. If you ask a clarifying question, append the question and the answer to its Clarifications section; if you didn't ask, record the assumption you made instead. This is what makes a run reproducible and auditable.

## 2. Brief before searching

Write `<run>/brief.md` (≤25 lines):

```markdown
# <question>
**Decision it serves:** what changes based on the answer
**Sub-questions:** 3–6, each independently answerable
**Success criteria:** what "done" looks like
**Out of scope:** explicit exclusions
**Known unknowns:** what may not be findable
```

If the question is ambiguous in a way that changes which sources matter, ask **one** consolidated question. Otherwise state your reading and proceed.

## 2a. Read what the author already gave you

Before writing a single scout brief:

```bash
python3 .claude/scripts/external_index.py scan <run>
```

`<run>/external_data/` holds sources the author supplied by hand. Anything marked
`NEW` or `CHANGED` is unread, and it changes what still needs searching for: an
author who dropped in twelve datasheets has already answered part of the brief.
Delegate the reading to a scout with the explicit file list, never the folder,
and register each file once its rows are written. Files marked `INDEXED` are
already mined and must not be re-opened.

Doctrine, evidence-row conventions for local files, and how to treat a supplied
AI-generated report: `.claude/references/external-data.md`.

## 2b. Hunt the gaps the brief doesn't contain

**The brief is the user's model of their question, and it is reliably incomplete** — if they knew what was missing they would have asked for it. A run that answers only the stated sub-questions produces something true, narrow, and quietly useless.

Before spawning scouts, work `references/gap-hunt.md` Pass 1: sweep definitions, scope boundaries, source classes you are *not* planning to search, who has an incentive to be wrong, where the dissent is, and what the negative case looks like. Most rows won't apply; the ones that do usually decide whether the report gets follow-up questions.

Open `<run>/coverage.md` there and keep it current through the run. Fold the dimensions that landed into the sub-questions or into a scout's brief — a dimension you noticed and didn't assign is a gap you chose, and it gets written down as one.

## 2c. Start from what the workspace already holds

For each sub-question:

```bash
python3 .claude/scripts/kb.py search "<the sub-question's key terms>"
```

Rows from earlier runs are leads with a head start: the page is usually already in
the library, so confirming it costs a script call rather than a search. Put the
relevant ones in the scout's brief under ALREADY ESTABLISHED, with their run, ID,
URL and access date, and narrow the scout to what they do not cover. A scout that
re-cites one copies the row into this run's ledger under a new ID, re-reads the
quote in the library copy, and checks the date: a figure fetched months ago may
have been superseded, and that is a thing to search for.

## 3. Fan out, don't crawl

One `research-scout` subagent per sub-question, **all spawned in a single message** so they run in parallel. Cap: 6 concurrent.

Give each scout a brief built from `references/scout-brief.md`. Never give two scouts overlapping scope — duplicate work is duplicate tokens.

Scouts return ≤400 words. Their real output is on disk: `outputs/<slug>/notes/<topic>.md` plus appended `evidence.jsonl` rows, and the digest itself in `notes/digests/<topic>.md`.

**Do not read the notes files wholesale.** Work from the digests; grep notes only when a specific claim needs its quote.

The digests on disk are what lets every later stage start without this
conversation: the writer drafts from them, a fresh session picks the run up from
them, and an expansion round months later reads them to learn what each line of
enquiry found and missed.

## 4. Evidence protocol

Every row in `outputs/<slug>/evidence.jsonl` is one JSON object, one line:

```json
{"id":"E7","claim":"X grew 40% YoY in 2025","quote":"…verbatim…","url":"https://…","title":"…","publisher":"…","author":"…","published":"2025-03-11","accessed":"2026-08-12","type":"primary|secondary|aggregator|vendor|opinion","admiralty":"B2","note":"figure is company-reported, unaudited"}
```

IDs are globally sequential across the run. Scouts claim ranges (scout 1 → E1–E99, scout 2 → E100–E199) to avoid collisions.

**`published`, `author` and `publisher` are not optional for a scholarly source.**
They exist on the page you just read, and a row without them cites as
`PMC (n.d.)`, naming the archive rather than the authors. `publisher` holds the
journal, never the repository. A vendor page with no date leaves `published`
empty and renders `n.d.` correctly. Check with
`references.py audit <run>` before drafting rather than at export, when the fix
costs a re-fetch.

`type` matters more than reputation: a Reuters article *about* a study is `secondary`; the study is `primary`. Prefer primary.

## 5. Second pass — audit the coverage

After digests land, run `references/gap-hunt.md` Pass 2 and give every sub-question and swept dimension a status in `coverage.md`: `COVERED`, `THIN`, `CONTESTED`, `GAP`, or `OUT OF SCOPE` (with the reason, in writing).

Then act on it:

- **`THIN`** records that a claim rests on one source. That is not automatically a defect — re-scout when the claim is load-bearing *and* a second independent source plausibly exists; otherwise keep it and let the report attribute it in text (`.claude/references/attribution.md`).
- **`CONTESTED`** → spawn one scout to adjudicate; contradictions are findings, not noise. Establish whether the sources measured different things, different periods, or genuinely disagree.
- **`GAP`** → classify it as access-restricted, unpublished, or not-searched. The three mean different things to the reader: `.claude/references/gaps.md`.
- **Convergent citations** — several sources that all trace to one origin. Mark them; `/verify` will collapse them.

Then the two questions that end the research:

1. **What would an expert immediately ask that this run cannot answer?** If it's answerable, answer it.
2. **If the conclusion is wrong, what is the most likely reason?** Go look for that specific thing. It is the highest-yield search available and it never appears in a brief.

Restricted sources are not dead ends, and they are the gaps the author can
actually close. Register each one as it happens, with the exact URL and the
reason the fetch failed:

```bash
python3 .claude/scripts/wanted.py add <run> --wanted "the figure you were after" \
    --url "https://the-page-that-failed" --reason "paywall, account required" \
    --kind access-restricted --context "what you did establish around it"
python3 .claude/scripts/wanted.py build <run>    # writes external_data/WANTED.md
```

`WANTED.md` is the list the author works from. When they retrieve a document and
save it into `<run>/external_data/`, the next `external_index.py scan` reports it
as unread, a scout mines it, and the row closes with `wanted.py resolve`. A
placeholder naming what is missing but not the URL that failed leaves the author
nothing to act on. Kinds and doctrine: `.claude/references/gaps.md`.

## 5b. Settle the voice before anyone writes prose

Research produces no prose, so this costs nothing now and saves a rewrite later.
If `<run>/voice.md` does not exist, ask the one question in
`.claude/references/voice.md` and record the answer: **scientific** for
specialist readers, **explanatory** for technically literate non-specialists.
Fold it into the handoff.

## 6. Handoff

Report to the user: sub-question coverage, evidence count, contradictions found, gaps that stayed open and which kind each is. Then stop or continue to `/report`.

`coverage.md` ships with the run. It is what makes a gap *handled* rather than *missed*, and `/report` and `/critique` both read it.

## Cost rules

- Search queries are cheap; fetching pages is not. Scouts fetch only what a snippet suggests is load-bearing.
- Scouts fetch through `library.py` first (see `research-scout`): a page any run has read is served from `library/` without a request, and the stored text makes the later quote check mechanical.
- Never fetch the same URL twice in a run — `grep -c "<url>" evidence.jsonl` first.
- If a sub-question is answerable from a single authoritative primary source, one scout is the correct number, not four.
