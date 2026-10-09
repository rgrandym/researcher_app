---
description: Answer a specific application or form question, to its word limit
disable-model-invocation: true
---

Answer this question: $ARGUMENTS

Read `.claude/skills/compose/SKILL.md` and follow it, with `kind = answer`, and read `references/kinds.md`
in that skill.

Before drafting, establish three things and state them back in one line: the
exact question, the word limit, and which incident or piece of work from
`dossier/` the answer is built on. A behavioural answer takes a real incident
from the record; there is no version of this task where one is invented.

For a single short answer with the material already to hand, stay at Tier 0:
write it in chat, no run folder. Scaffold only when the form has several
answers or the author wants it kept.

Report the word count when you hand it over.
