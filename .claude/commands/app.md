---
description: Answer a question about the app or the workspace, from the guides
disable-model-invocation: true
---

Answer this question about the Research app or this workspace: $ARGUMENTS

The answer comes from the guides, never from memory:

- `USERGUIDE.md` covers the workspace, its commands and the pipelines.
- `app/README.md` covers the app: running, building, testing and how it is made.

Both are long. Grep for the terms in the question first, then read only the
matching sections. If the guides do not answer it, look at the code or the
script they point to before saying so.

Reply in chat, in a few plain sentences, and name the file and section the answer
came from so the author can read further. Nothing is written to disk. Start no
research and no subagents.

If the question turns out to be about the world rather than the tools, say that
`/research` is the command for it and stop.
