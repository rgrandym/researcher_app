# Scout brief template

Fill every field. Vague briefs produce padded digests.

```
RUN DIR: outputs/<slug>/
NOTES FILE: outputs/<slug>/notes/<topic>.md
EVIDENCE IDs: E<start>–E<end>   (yours alone; never reuse)

SUB-QUESTION: <one question, answerable on its own>

MUST ESTABLISH:
- <specific fact / number / date / mechanism>
- <…>

SOURCE PREFERENCE: <e.g. filings + regulator publications > trade press > vendor blogs>
RECENCY: <e.g. nothing older than 2024 unless it is the origin of a still-cited figure>
BUDGET: <e.g. ≤12 fetches>

EXCLUDE: <what another scout is covering — do not touch it>

ALREADY ESTABLISHED (from kb.py search; omit if none): <run · E# · accessed · URL ·
the claim>. Do not re-search these. Re-cite one by copying it into this run's
ledger with a new ID after re-reading its quote in the library copy
(`library.py get "<url>" --grep "<words>"`); look for anything newer if it is a
figure.

EXISTING POSITION (extensions only): <the claim already in the report, with its
[E#]>. Say explicitly whether your evidence SUPPORTS, QUALIFIES, or CONTRADICTS it.

RETURN: ≤400 words. Findings only, each with its [E#]. State what you could not
find and why. No preamble, no methodology narration, no restating this brief.
```

## Report blocked sources — never silently drop them

A page you could not read is a finding, and it is one the report can act on. For
every source that a paywall, login, NDA, robots rule, or fetch failure kept you
from, record in the notes file and name in the digest:

- **what it would have contained** — the specific figure or fact you were after;
- **the exact access route** — "quote via the vendor's sales portal, account
  required", "IEA subscription", "annual PDF, 2025 edition not yet published";
- **anything you did establish around it** — a range from a secondary source, a
  prior-year figure, a competitor's equivalent.

That is what lets `/report` build the table with a `[NEEDS DATA — what · where]`
cell instead of quietly deleting the row. **Never guess the value, never infer it
from a URL slug or a page title, and never substitute a different vendor's number
to fill the cell.** Distinguish access-restricted from unpublished:
`.claude/references/gaps.md`.

## Splitting sub-questions well

Good splits are **orthogonal** — no scout needs another's output.

- By entity: one scout per company/jurisdiction/product.
- By question type: "what is the state" vs "what caused it" vs "who disputes it".
- By source class: one scout on primary/regulatory, one on critical/dissenting coverage.

Bad splits: "background" + "details" (overlapping), "part 1" + "part 2" of a chronology (sequential dependency).

## Always brief one dissent scout

For any contested topic, dedicate a scout to *the strongest case against* the emerging answer. Confirmation bias in research agents is a search-query problem: agents query the hypothesis, find it, and stop. Force the counter-query.
