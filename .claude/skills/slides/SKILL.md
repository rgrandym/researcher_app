---
name: slides
description: Critique and redesign a PowerPoint deck as an expert slide designer - hierarchy, type scale, grid and alignment, colour and contrast, density and consistency - then apply the changes the author accepts to the deck's editable master, check the result by looking at every slide, and have it independently reviewed. Use when the author asks to improve, restyle, tidy, rebrand or redesign slides, or types /slides.
disable-model-invocation: true
---

# Slides

A deck that looks designed by someone who knows slides, with every word, figure and
source it had before unless the author accepted a change. Doctrine:
`.claude/references/slide-design.md`. Read it before looking at the deck.

The deck is edited through its master, `<run>/<slug>.md`: the same file the app's
Palette and layout and Edit tabs save. What the author does there by hand and what
this skill does are one history, so the author can stop, adjust a box, and run
`/slides` again.

## 0. The deck and the author's saved work

1. Run `python3 .claude/scripts/saved_check.py <run>` and stop on exit 1.
2. Find the deck. A run has a deck master when `<slug>.md` starts with
   `<!-- office-master:1 -->` and its office block says `"format": "pptx"`.
   - No master yet, deck in `external_data/`: `python3 .claude/scripts/subject.py
     add <run> <file>.pptx`, then `python3 .claude/scripts/document.py start <run>
     <slug>`.
   - Continuing from a delivered version: add the supplied original as above, then
     `document.py start <run> <slug> --from deliverable/<slug>/vN/<file>.pptx`.
   - More than one deck and the request does not say which: ask.
3. **The author's hand edits stand.** If `subjects/<slug>/slides-applied.md` exists,
   compare it with the master: every box, style or theme value that differs was set
   by the author after the last round. Leave it as they set it. The plan may suggest
   changing it only as a separate item marked *overrides your edit*.

## 1. Look at every slide

```bash
python3 .claude/scripts/deck_render.py <run>/<slug>.md <run>/subjects/<slug>/slides/rN-before
python3 .claude/scripts/slides.py inspect <run>/<slug>.md
```

Read every picture. For a deck over 30 slides, read them in batches and write what
you see per slide to `subjects/<slug>/slides-notes.md` as you go, so the main thread
holds the notes and not the images. The inspection measures sizes, fonts, edges,
density and contrast; your eye judges hierarchy, balance, grouping, imagery and
whether the slide makes one point.

## 2. The brief

Settle three things, asking only what the request and the deck leave open (one
question, defaults recommended):

- **Brand:** keep the deck's own colours and fonts (default), tighten them (merge
  near-duplicates, fix the type scale), or a new look the author describes.
- **Medium:** shared as a PDF and read alone (denser text allowed) or presented
  (larger type, fewer words).
- **Off-limits:** slides or elements the author wants left alone.

## 3. The plan

Write `subjects/<slug>/slides-plan.md`, ranked by how much each change improves the
deck, most first:

- **Deck-wide** first: the type scale (each current size mapped to a scale step),
  the palette (colours kept, merged or replaced), the typefaces, the grid (margins,
  title position, columns).
- **Per slide** next, one item per change: `D07 · slide 4 · <what is wrong, with the
  doctrine section> · <the change, in concrete terms: which box, from what to what>`.
- **Words** separately, marked *wording*: a title rewritten as its point, a slide
  split. Never a figure, a unit, a name or a source (doctrine §8).
- **Beyond the editor**, separately: what the master cannot do (new shapes, new
  pictures, chart internals, slide backgrounds and layouts). Say how it could be done:
  by hand in PowerPoint, or `/rebuild` for a new design.

Then summarise in chat: the five changes that do most, the counts, and the question:
accept all, all except some IDs, or design only (no wording). Wait for the answer.
Nothing reaches the master before it.

## 4. Apply

Turn the accepted items into operations (the `slides.py` docstring lists them) in
`subjects/<slug>/slides-ops-rN.json` and run:

```bash
python3 .claude/scripts/slides.py edit <run>/<slug>.md <run>/subjects/<slug>/slides-ops-rN.json
```

`edit` validates before it writes and changes nothing on `REFUSED`; fix the
operation, never the master by hand. Deck-wide merges use `swap_color` and
`swap_font`; a type scale is a `style` operation per box whose size changes.

## 5. Look again

Render to `slides/rN-after`, run `inspect`, and read every changed slide beside its
before picture. Look for what a script cannot see: text clipped by a smaller box,
boxes now overlapping, a slide that lost its hierarchy, an accent that now competes.
Fix those within the accepted items and render again.

## 6. Independent review

Spawn `slide-reviewer` with the run, the slug, the round, the plan, the accepted IDs
and the before and after folders. Repair what it finds within the accepted scope;
anything that needs a new decision goes to the author as a question. Rerender after
repairs. Record the round in `subjects/<slug>/slides-log.md`: accepted IDs, operations
file, review result, what was left for the author.

## 7. Hand over

1. `cp <run>/<slug>.md <run>/subjects/<slug>/slides-applied.md`, so the next round can
   tell the author's later edits from this one's.
2. Export only when the author asks: `python3 .claude/scripts/document.py export
   <run> <slug>` writes the next `deliverable/<slug>/vN/`. Delivered versions are
   never overwritten.
3. Tell the author what changed, what the review found, and that the deck is open in
   the app: the HTML tab's **Palette and layout** moves, resizes and restyles any box
   by hand, and the Edit tab changes the words.
