# Data you could not obtain

Shared doctrine. `research`, `report`, `visualize`, `critique`, `repair` and the
scout brief all point here; do not restate it in a skill file.

## The rule

**Build the section anyway.** A vendor comparison, jurisdiction table, or cost
breakdown with three of five rows sourced is worth more than no comparison —
provided the holes are visible, labelled, and attributed to a reason.

Dropping the row is the real failure. It converts a partial answer into a
confident wrong one, because the reader cannot see what was ever in scope.

## The three kinds, and why the distinction is load-bearing

| Kind | Means | Reader's move |
|---|---|---|
| **Access-restricted** | Exists behind a paywall, login, or NDA | They can get it — an account, a call, a subscription |
| **Unpublished** | Nobody has this figure in public form | None. Do not imply a phone call would fix it |
| **Not searched** | You ran out of scope or budget | Say so plainly in Limitations |

Presenting *not searched* as either of the others is the one placeholder failure
that **misleads** rather than merely disappoints: it dresses a budget decision as
an epistemic limit.

## Register the source before you write the placeholder

A placeholder tells the reader a hole exists. It does not tell the author how to
close it, because it carries no URL and no failure reason. Both go in the
register, which is `<run>/blocked.jsonl`:

```bash
python3 .claude/scripts/wanted.py add <run> --wanted "…" --url "…" \
    --reason "…" --kind access-restricted|unpublished|not-searched
python3 .claude/scripts/wanted.py build <run>     # writes external_data/WANTED.md
```

`WANTED.md` is the author's shopping list: the exact page that failed, why it
failed, what is already known around it, and where the report needs it. The
author retrieves what they can, saves it anywhere under `<run>/external_data/`,
and the next `external_index.py scan` reports it as unread so an agent mines it.
Close the row with `wanted.py resolve <run> B3`.

The register is never `evidence.jsonl`: a source nobody could read backs no
claim.

## Syntax

**Table cell** — never `N/A`, never `—`, never blank. `N/A` means "does not
apply"; this means "we could not get it, and here is how you can". The pointer is
the useful half.

```markdown
[NEEDS DATA — <what exactly is missing> · <where a person would get it>]
```

**Chart** — the value is `null` and the spec carries a `data_gaps` note naming
what is missing and where to get it. The renderer draws a labelled hatched slot.
A `null` with no `data_gaps` is a validation error: a hole must always say what
fills it.

**Prose** — an unpublished figure is stated as unpublished in the sentence that
needed it. Do not leave a placeholder implying it is retrievable.

## Every report with holes carries `## Data still to obtain`

Built mechanically, never by hand:

```bash
python3 .claude/scripts/figures.py gaps outputs/<slug>/report.md
```

Each entry: the hole, which of the three kinds it is, and the specific step that
closes it. This section is what makes a partial report actionable rather than
merely incomplete — and it is the first thing a well-meaning conversion drops, so
it is checked on export.

## When a repair empties a cell

`FABRICATED` or `CONTRADICTED` data in a chart does not mean deleting the chart.
The value becomes `null`, `data_gaps` records what is now unsourced, and the
exhibit ships with a visible hole instead of a wrong bar. Same for a table cell.
A quiet deletion of the row hides the correction.
