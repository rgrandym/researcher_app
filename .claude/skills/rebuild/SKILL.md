---
name: rebuild
description: Build a new deck or document in the exact design of a supplied one (its fonts, colours, type scale, motifs, imagery and voice), carrying the author's accepted changes, or in a different design the author chooses. Use when the subject is a PDF that cannot be edited, when the author asks for a new deck from a template or an old deck, or for the same content in another style.
disable-model-invocation: true
---

# Rebuild

A new file that could sit beside the original unnoticed. Doctrine:
`.claude/references/revision.md`, especially **Form** and **Voice**.

Ask first whether the author has the source `.pptx` or `.docx`. Editing it with
`/revise` beats any rebuild.

## 1. What the new file says

The content is the original plus the accepted changes (`changes.py status`), and
nothing else. With no plan yet, run `/changes` first: the author accepts a
rebuild's content line by line, as for any revision. A new deck the author asks for
from scratch, with a template supplying only the design, gets its outline as the
plan: one `add_slide` change per slide, against the template's pages.

Write `deliverable/<slug>/outline.md`: every slide or section in order, marked
`kept`, `changed (C04, C07)`, `new (C12)` or `dropped (C09)`, with its text.

## 2. The design

Which design: **faithful** (the subject's, or a template's) unless the author named
another. For another house style, map `.claude/styles/<name>.json` into the theme;
for a new design, the author describes it and the theme records it.

```bash
python3 .claude/scripts/deck_kit.py theme <run> <slug>
```

Then **look at the original**: read at least four page images in
`subjects/<slug>/pages/` (title, a text slide, a data slide, a picture slide) and
correct `theme.json`. Fix the colour roles. Set the motifs in `style`:

- `title_bold`
- `kicker`: case, colour, a rule under it
- `header_band`
- `panel`
- `list`: bullets, numbered or plain
- `dividers`

Set the footer, the logo (from `images/`) and the type sizes. Every value must
come from `design.json`.

## 3. Build

Write `deliverable/<slug>/vN/build.py` using `deck_kit.Deck` (its docstring lists
the slide types), with text in the document's voice (`voice.md`) and citations in
its system. Run it. Overflow warnings mean too much text: cut words, never shrink
type.

## 4. Check

```bash
python3 .claude/scripts/changes.py fidelity <run> <slug> <run>/deliverable/<slug>/vN/<file>.pptx
python3 .claude/scripts/deck_kit.py preview <run>/deliverable/<slug>/vN/<file>.pptx <run>/deliverable/<slug>/vN/preview
```

Fidelity must `PASS`. Then compare each new slide with the nearest original page:
same weight of type, same palette in the same roles, same margins and motifs. Fix
the theme or the build, never by hand in PowerPoint.

## 5. Independent review and hand-over

Spawn `change-reviewer` in `DELIVERABLE` mode (rebuild) with the run, slug,
version and outline. It compares previews with original pages and every accepted
change with the new text, and writes `deliverable/<slug>/vN/review.md`. Repair,
rebuild, then hand over as `/revise` does. The build script stays in the version
folder, so the deck can be rebuilt after the next round of changes.
