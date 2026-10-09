---
description: Adapt the master CV to a posting or a target, selecting from the dossier
disable-model-invocation: true
---

Adapt the author's CV. Target: $ARGUMENTS

Read `.claude/skills/compose/SKILL.md` and follow it, with `kind = cv`. In short:

1. Scaffold: `bash .claude/scripts/new_piece.sh cv "<slug>" "<the request, verbatim>"`.
2. Read `dossier/cv/` for the record and `$run/source_material/` for the posting.
   If the posting is a URL, fetch it; if the author pasted it, write it to
   `source_material/` first so a later round can read it.
3. Select and reorder. Never write a role, date, title or figure the dossier
   does not carry, and never round a claim up to meet a requirement.
4. Fill `context.md`, draft `cv.md`, gate it, review it with `report-critic`.
5. Hand back the gaps between what the posting asks for and what the record
   supports. That list is the useful half of the output.

Ask before exporting. A CV usually ships as `.docx`.
