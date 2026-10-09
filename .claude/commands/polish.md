---
description: Rewrite text in the author's voice without changing what it claims
disable-model-invocation: true
---

Polish this text, in the author's voice: $ARGUMENTS

Read `.claude/voice/profile.md` and `.claude/references/diction.md` first. Then
rewrite for rhythm, precision and connective tissue only.

The constraint is that **no claim changes**: its strength, its scope and its
hedging all stay exactly where the author put them. If a sentence reads weaker
or stronger than they seem to have intended, say so in chat and leave it.

This is a Tier 0 job: the result goes in chat, and nothing is written to disk
unless the text came from a file, in which case edit that file in place and run
`python3 .claude/scripts/gate.py <file>` if it is a run master.

If the text is longer than a few paragraphs, or it is a piece the author will
send to a named reader, use the `compose` skill instead so it gets a review.
