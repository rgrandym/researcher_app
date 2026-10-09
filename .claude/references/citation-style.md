# Citation style

Two audiences, two forms of the same citation.

**`report.md` cites by evidence ID.** `[E205]` is stable, never renumbered, and
resolves to a row in `evidence.jsonl`. That is the right form for the master:
it survives rewriting, it is machine-checkable, and `audit_citations.py` can
prove every marker resolves.

**A deliverable cites by author, date and material type.** `[E205]` tells a
reader nothing about whether a claim rests on a peer-reviewed paper, a
conference poster, a vendor datasheet or a marketing note, and those are not
interchangeable. A scientific reader weighs a claim partly by the class of
document behind it, and expects to see that class without turning to the back
of the report.

`references.py` renders the second from the first, at export time. `report.md`
is never modified.

Which reader-facing form it renders is a choice, made once per report:
the workspace house style, MLA, or either Chicago system.

```
[E205]  ->  (Halden Labs, product datasheet, 2026)
[E1200] ->  (Glögl et al., 2024, Science)
[E1309] ->  (Northwind Materials Ltd, white paper, 2025)
```

---

## Choosing a citation system

One system per report, chosen before the first line and held to the last. Mixing
author-page citations with numbered notes tells a reader the document was
assembled rather than written, and it is the fastest way to lose their trust in
everything else it says.

Record the choice in `<run>/voice.md` beside the narration mode, so every later
round renders the same way:

```
Citation system: chicago-notes
```

| System | In-text | List heading | Choose when |
|---|---|---|---|
| `house` | (Halden Labs, product datasheet, 2026) | `## References` | The default. The reader needs the material class in the sentence |
| `mla` | (Aussel 14), or (Aussel) unpaginated | `## Works Cited` | Humanities convention is expected, or the reader asked for MLA |
| `chicago-ad` | (Aussel 2022, 14) | `## References` | Chicago is expected and the reader wants dates visible in the text |
| `chicago-notes` | superscript¹ | `## Bibliography` | The prose should stay clean, and the sourcing belongs at the foot or the back |

```bash
python3 .claude/scripts/references.py render <styled.md> --run <run> \
    -o <out.md> --system chicago-notes --citemap map.json
```

**Pages are never invented.** MLA and Chicago both want a locator, and the
ledger supplies one only where the source actually carried it. A row with no
page renders author-only, which is correct MLA for unpaginated web material
rather than a degraded citation. The renderer reports how many sources cite
author-only so the number is visible rather than assumed.

**The master document is unaffected.** `report.md` always cites `[E#]` and always
ends in `## Sources`, whatever system the deliverable uses. The system is applied
to the derived copy at export, which is what makes restyling a report into
another convention one command rather than a rewrite.

---

## The two families

**Scholarly — author, year, venue.** Weight comes from peer review, so the
venue is the informative field and the type qualifier is only added when the
document is *not* a peer-reviewed article.

> Glögl M et al. (2024). *Target-conditioned diffusion generates potent TNFR
> superfamily antagonists and agonists.* Science. [peer-reviewed article]

**Commercial — author or company, document type, company, year.** Weight comes
from the issuer and from what kind of document it is, so the type is stated
first and always.

> Northwind Materials Ltd (2025). *NW-200 Information Sheet v250226.*
> [product datasheet] Supplied document, external_data/northwind/…

**Institutional** covers regulators, standards bodies, patent offices,
statistical agencies and databases. They are cited like scholarly work, but
their authority is jurisdictional rather than peer-conferred, so the type is
always stated.

Run `python3 .claude/scripts/references.py types` for the current vocabulary.
It is data in the script, not prose here, so this file cannot go stale.

---

## Why the type is stated in-text and not only in the list

A reader scanning a paragraph should be able to tell that

> …the cell retains ≥80% capacity after 2,000 cycles (Northwind Materials Ltd, application note, 2025)

is a vendor's own measurement, while

> …monovalent constructs do not activate signalling at all (Cao et al., 2022, Nature)

is not. Putting the class only in the back matter means nobody sees it. This is
the same reason the report attributes contested figures in-line rather than
relying on the source list.

**Labels must not flatter.** "Marketing material" does not become "technical
note". "Preprint, not peer reviewed" keeps its second clause. A conference
abstract is not a paper. If the honest label is unflattering to a claim the
report relies on, that is information the reader needs, not a presentation
problem to solve.

---

## Two rules the renderer will not break

**Nothing is invented.** No author, date, journal or document type is ever
written that is not in the ledger or derivable from it. A row without a
personal author is cited to its corporate author; a row without a date is cited
`n.d.`; a source whose class cannot be determined prints
`[source type unclassified]` rather than a guess. `references.py audit <run>`
counts all three so the gaps are visible.

**Evidence IDs are never renumbered, and never disappear.** Each reference entry
ends with the evidence rows drawn from it (`— E1200–E1217`), so the audit trail
from a rendered citation back to `evidence.jsonl` survives into the PDF.

---

## Tagging rows so they render well

The renderer reads `type` from each evidence row, falls back to URL and title
heuristics, and only then gives up. Three points of care:

- **`type` should record the material, not its role in the argument.**
  `primary`, `secondary` and `industry` describe how a source is being *used*.
  They tell the renderer nothing, and they fall through to heuristics. Prefer a
  vocabulary key: `datasheet`, `white_paper`, `press_release`, `preprint`,
  `poster`, `coa`, `trade_press`, `consultancy`, `regulatory`, `market_report`.
- **`note` is never read for classification.** It records how a source was
  fetched ("Abstract only; full text blocked"), and reading it as material
  class once demoted ten peer-reviewed papers to conference abstracts, which
  inverts the exact weighting this convention exists to convey.
- **Heuristics are deliberately conservative.** A pattern that would sometimes
  mislabel is left out and the source falls through to `unclassified`.
  Under-claiming a source type is recoverable; calling a marketing note a
  peer-reviewed article is not.

Run `references.py audit <run>` before an export. Zero unclassified is the
target, and the fix is to tag the rows, not to loosen the heuristics.

---

## Provenance does not upgrade credibility

An author-supplied vendor PDF is a vendor source, cited and graded as one. The
reference entry marks it *Supplied document* with its path, because a reader
outside the run folder cannot open it, and that limit belongs in `Limitations`
when a load-bearing claim rests on supplied material alone. See
`.claude/references/external-data.md`.
