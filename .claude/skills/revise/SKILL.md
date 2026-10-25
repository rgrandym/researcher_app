---
name: revise
description: Apply the author's accepted changes to a copy of a supplied Word, PowerPoint, Excel or Markdown document, keeping its exact styles, fonts, colours, numbering and voice, then check and independently review the new version. Use after /changes once the author has accepted changes, or when the author asks to apply, implement or produce the revised document.
disable-model-invocation: true
---

# Revise

Apply what the author accepted; nothing else. Doctrine:
`.claude/references/revision.md`.

A Word or PDF document revised as a Markdown master (`runmeta.py <run> --documents`
names it) has no plan to apply: it is exported with `document.py export`, from the
app's **Revised document** view or by `/export`. Stop and say so.

## 1. Preconditions

```bash
python3 .claude/scripts/changes.py status <run> <slug>
```

- **No accepted changes:** stop and point the author to the Changes view.
- **Stale changes** (edited after the author decided): list them and ask the
  author to decide again. They are not applied meanwhile.
- **A PDF subject:** this is `/rebuild`'s work. Say so and stop.
- When the app started this command, read the request file it names
  (`deliverable/<slug>/request-*.json`) for the author's choices.

For a Word document, the author chooses **tracked changes** (every change visible
in Word's review pane, under their name) or a **clean copy**. Use the request
file's choice; otherwise ask once with `AskUserQuestion`, and ask for the name
tracked changes should carry.

## 2. Apply

```bash
python3 .claude/scripts/apply_changes.py <run> <slug> [--track --author "<name>"]
```

It writes `deliverable/<slug>/vN/` from the untouched original. A `REFUSED`
change names its reason (a `before` that no longer matches, a span across a
footnote marker, a table of the wrong width). Fixing it edits the plan, which
makes it stale: tell the author which change was corrected and why, and wait for
their decision. Use `--partial` only when the author agrees to ship without it.

## 3. Check

```bash
python3 .claude/scripts/changes.py check <run> <slug>
```

Must print `PASS`. A problem means the file differs from the original where no
accepted change says it should, uses formatting the original does not, links to
an unfetched URL, or carries a pipeline trace. Find the cause in the plan or the
donor parts (`like`), never by editing the deliverable by hand, and apply again:
each attempt is a new version.

For a deck, render the changed slides and look at them beside the originals:

```bash
python3 .claude/scripts/deck_kit.py preview <run>/deliverable/<slug>/vN/<file>.pptx <run>/deliverable/<slug>/vN/preview
```

## 4. Independent review

Spawn `change-reviewer` in `DELIVERABLE` mode with the run, slug and version, once.
The plan was reviewed and the check has proved every change landed, so this pass
looks at the result as a reader would: the seams, the form, the flow. It reads
`applied.json`, `check.json`, the new `text.md` and any previews, and writes
`deliverable/<slug>/vN/review.md`. A finding that needs different text becomes a
proposed change for the author (back to `/changes`); a mechanical defect is fixed
in the plan's donors and applied again as a new version.

## 5. Hand over

`python3 .claude/scripts/run_check.py <run> --deliver` should exit 0. Then give
the author the file path, the version, tracked or clean, how many changes were
applied, warnings, open items still wanted, and what changed in a few lines.
