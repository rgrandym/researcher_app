# External data

`<run>/external_data/` holds sources the **author supplied by hand**: datasheets,
certificates of analysis, purchased reports, vendor PDFs, spreadsheets, internal
memos, scans. Nothing in the pipeline writes to it. The author drops files in,
in whatever folder structure suits them, at any point in a run's life.

They are sources, and they are read exactly like a fetched page: verbatim
extract into `notes/`, structured row into `evidence.jsonl`, citation in the
report. A fact from a PDF on disk is worth neither more nor less than the same
fact from a URL.

Two failures this folder is guarded against, and they pull in opposite
directions:

- **Never read.** The author supplies twelve datasheets and the report ships
  saying the figure could not be obtained. This has happened, and it is the
  worse failure: the author did the work of finding the source and the engine
  ignored it.
- **Read every time.** Forty PDFs re-opened on every round, in the main thread,
  burning the context budget that the whole workspace is built to protect.

The index resolves both. Read what is new; never re-read what is indexed.

---

## The index

`external_data/.index.json` records a content hash per file, plus the evidence
IDs and notes file produced from it. It is written only by
`.claude/scripts/external_index.py`.

```bash
python3 .claude/scripts/external_index.py scan <run>       # what is unread
python3 .claude/scripts/external_index.py status <run>     # one-line summary
```

`scan` classifies every file:

| State | Meaning | Action |
| --- | --- | --- |
| `NEW` | Never read | Read it |
| `CHANGED` | Hash differs from the index; the author replaced it | Re-read it, and check whether the rows it produced still hold |
| `INDEXED` | Already mined | Do not open it. Its facts are in `evidence.jsonl` |
| `MISSING` | Indexed, file since deleted | Leave the evidence rows alone; note it if a claim leans on the file |

`scan` exits 2 when anything is unread, so a stage can branch on it without
parsing the output.

After reading a file, mark it:

```bash
python3 .claude/scripts/external_index.py register <run> northwind/NW-200_SDS.pdf \
    --evidence E900-E907 --notes notes/external-northwind.md \
    --summary "NW-200 safety data sheet: composition, storage, hazard classification"
```

A file that turned out to hold nothing citable is still registered, with
`--nothing-usable` and a summary saying so. Otherwise the next round reads it
again and reaches the same dead end.

`register` refuses evidence IDs that are not yet in `evidence.jsonl`. Write the
rows first.

---

## When to scan

At **four** points, because files arrive whenever the author finds them:

1. At the start of `/research`, before writing scout briefs. Unread files change
   what needs searching for.
2. At the start of `/verify`. A user-supplied primary can confirm or break a
   claim that was sourced from a secondary.
3. At the start of `/expand` and `/user-edits`. An author who drops in a PDF and
   then asks for more depth has usually just answered their own question.
4. Whenever the author says they added something.

A `scan` costs no model tokens. Running it and finding nothing new is the
expected outcome, and it is cheap.

---

## Reading them

**Delegate the reading.** A `research-scout` subagent reads the unread files in
an isolated context, writes extracts to `notes/`, appends evidence rows, and
returns a digest. Raw PDF text never enters the main thread. This is the same
rule that governs fetched pages, and it applies with more force here, because a
local PDF has no snippet to triage against and gets read in full.

Give the scout the explicit file list from `scan`, never the folder. "Read
everything in external_data" is how forty files get opened.

For a large drop, one scout per subfolder is usually the right split: authors
group by vendor or by topic, and that grouping is already a sub-question.

## Evidence rows from a local file

Same schema as any other row. Two conventions:

```json
{"id":"E900","claim":"NW-200 is supplied as a coated powder, 25 kg per drum",
 "quote":"…verbatim from the PDF…",
 "url":"file://external_data/northwind/NW-200_information_sheet_v250226.pdf",
 "title":"NW-200 Information Sheet v250226","publisher":"Northwind Materials Ltd",
 "published":"2025-02-26","accessed":"2026-08-15","type":"vendor","admiralty":"B2",
 "origin":"external_data","note":"author-supplied PDF; vendor's own document"}
```

- `url` is the `file://external_data/<relative path>` form, so a reader can find
  the file in the run folder. If the document prints its own canonical URL, put
  that in `note`; do not put a URL in `url` that nobody fetched.
- `origin: "external_data"` marks the row as author-supplied, so a later round
  can tell at a glance which claims rest on material that is not on the web.

**Provenance does not upgrade credibility.** A vendor datasheet is a vendor
source whether it was downloaded by an agent or handed over by the author. Grade
it on `.claude/skills/verify/references/admiralty.md` like anything else, and
attribute it in text like anything else. The author choosing to supply a
document tells you what they think is relevant; it says nothing about whether
the document is right.

## `ai_reports/` is model output and is never a source

The folder layout carries one rule, and it is not a matter of judgement:

| Path | What it holds | Standing |
| --- | --- | --- |
| `external_data/ai_reports/**` | Model output: chatbot research summaries, generated business cases, AI-drafted memos | **Leads only.** Always unverified, whatever the document asserts about itself |
| `external_data/**` (everything else) | Documents from real sources: datasheets, certificates, filings, purchased reports, correspondence | Sources. Graded and cited normally |

A file under `ai_reports/` is read for **the claims it makes and the pointers it
contains**, and then every one of those claims is sourced independently from a
real document before it can appear in the report. The AI document supplies the
question; something else has to supply the answer.

This holds regardless of how plausible the file looks, how well cited it appears,
and how confidently it is written. A generated report that cites twelve sources
is twelve leads, not twelve citations: the citations themselves are unverified
until someone fetches them, and fabricated references are the characteristic
failure of the thing that wrote it.

`register` enforces this. It refuses `--evidence` for a path under `ai_reports/`
and tells you what to do instead:

```bash
python3 .claude/scripts/external_index.py register <run> ai_reports/business_case.pdf \
    --leads 9 --notes notes/leads-business-case.md \
    --summary "AI-drafted business case: 9 claims extracted for independent sourcing"
```

`--leads N` records how many claims came out of it for chasing. The notes file
holds those claims, each with the search that would settle it. Nothing else about
the file enters the evidence ledger.

**The one exception, and it is narrow.** An evidence row may cite an
`ai_reports/` file when the report is making a statement *about that document*:
what it claimed, what it got wrong, that the author was working from it. That
needs `--about-document`, and the text says plainly what the source is. A row
like *"the supplied business case assumes a 40% gross margin"* is legitimate; a
row like *"gross margin is 40%"* sourced to the same file is not.

**What to do when a lead cannot be sourced.** It does not quietly become true and
it does not quietly disappear. Record it in `coverage.md` as a `GAP`, and if the
report needs the claim, it ships as a visible hole with its provenance stated.
See `.claude/references/gaps.md`.

## Citing a file the reader cannot open

The `## Sources` entry says plainly where it came from:

```
[E900] NW-200 Information Sheet v250226 — Northwind Materials Ltd, 2025-02-26.
       Supplied document, external_data/northwind/NW-200_information_sheet_v250226.pdf (vendor, B2)
```

A reader outside the run folder cannot verify it, and that limit belongs in the
`## Limitations` section when a load-bearing claim rests on supplied material
alone.

## What a scan finding changes

An unread file is not merely new evidence; it can close an open hole or break a
shipped claim. After reading one, check both directions:

- Does it fill a `[NEEDS DATA — … ]` placeholder? Close the placeholder and
  update `## Data still to obtain`.
- Does it contradict a claim already in the report? That is a finding, and it is
  reconciled the way `/expand` reconciles contradicting evidence: the claim
  moves, and the change is declared. A supplied source that quietly disappears
  because it disagreed with the draft is the failure mode this workspace exists
  to prevent.
- Does it change a `coverage.md` row from `GAP` to `COVERED`? Update it.

## Files the workspace cannot open

Images, proprietary formats, password-protected PDFs, and scans with no text
layer are listed by `scan` and flagged. Do not guess at their contents from the
filename. Ask the author what is in the file, record their answer in the run's
`prompt.md` clarifications, and register the file with a summary of what they
said. An author's description of their own document is a legitimate source, and
it is attributed as one.
