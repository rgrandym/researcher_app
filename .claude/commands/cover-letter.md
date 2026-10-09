---
description: Write a cover letter for a posting, from the author's record
disable-model-invocation: true
---

Write a cover letter. Target: $ARGUMENTS

Read `.claude/skills/compose/SKILL.md` and follow it, with `kind = cover-letter`. Read
`references/kinds.md` in that skill before drafting: the letter connects the
author's record to this posting's actual problem, and no paragraph in it may be
sendable to a different employer unchanged.

Scaffold with `bash .claude/scripts/new_piece.sh cover-letter "<slug>" "<the request, verbatim>"`.

If a CV run for the same target already exists under `outputs/`, read its
`context.md` rather than re-deriving the brief, and say that you did.
