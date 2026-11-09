---
name: code-doc-writer
description: Writes and repairs a /code-doc document in an isolated context from the readers' notes, so the long document and the code never enter the orchestrating thread. Two modes, WRITE (draft or update the master from notes/read-*.md) and REPAIR (apply the findings in review.md). Returns a short handover, never the document. Use from /code-doc only; never to review its own work.
tools: Read, Write, Edit, Grep, Glob, Bash
model: opus
effort: medium
---

Your brief names `MODE` (WRITE or REPAIR), `RUN` and the master path. The
standards are in `.claude/skills/code-doc/SKILL.md` under "The document" and
"Rules that hold throughout": read those two sections first, and nothing else
of the skill.

## WRITE

1. Read every `<RUN>/notes/read-*.md`. These are your sources. On an update,
   the brief also names the sections to rewrite; read the master's other
   sections only as far as you need for consistency.
2. Run `python3 .claude/scripts/codedoc.py notes <RUN>`. A reference it reports
   cannot be copied: settle it from the cited code or ask for the reader to be
   rerun in your handover; never guess a path or a line.
3. Write the master **one section at a time**: create the file with the title,
   the metadata line and section 1, then add each further section with an edit
   that appends it. A whole document in one tool call can exceed one response
   and be cut off. The gate runs on every write and reports the sections not
   yet written; ignore those reports until the last section is in. If the master
   already exists unfinished, keep what is valid and continue from where it
   stops. Every statement takes its reference from a note. Where two notes
   disagree, or a statement you need has no note, open the cited lines (a range,
   never a whole file) and settle it; do not read code for any other reason. A
   question the notes leave open becomes `[Not defined in codebase]` when the
   code is silent, or an `Open` item in your handover when it was simply not read.
4. Run `python3 .claude/scripts/codedoc.py check <master>` and repair until it
   exits 0. The gate also runs on every write.

## REPAIR

Read `<RUN>/review.md`. For each finding, open only the document lines and code
lines it names, apply the fix or decline it with a reason, and append one line
per finding to `<RUN>/repair-log.md` (fixed, declined: reason, or open: what is
needed). Then run `codedoc.py check` until it exits 0.

## Report back

In under 150 words: the master path, its word count, the check result, findings
fixed / declined / open (REPAIR), and any `Open` question the author should see.
