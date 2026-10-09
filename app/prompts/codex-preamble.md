# Working in the research workspace

You are running in the research workspace. Before acting, read `CLAUDE.md` and
`.claude/voice/profile.md`. Treat both as binding: they are the rules every agent
in this folder follows, whichever model it runs on.

How this workspace maps onto your tools:

- **Commands.** The author's `/name` commands are skills in
  `.claude/skills/<name>/SKILL.md` or commands in `.claude/commands/<name>.md`.
  When a message says a command was invoked, read that file and follow it,
  together with the files it points to.
- **Subagents.** Where a skill tells you to spawn an agent (a scout, a verifier,
  a critic), spawn a separate subagent and give it the definition in
  `.claude/agents/<name>.md` as its instructions, with only the inputs the skill
  names. The thread that wrote a draft never reviews it, so a review step must
  run in its own subagent and never in this thread.
- **Tool names.** Where a skill names Claude Code tools, use your equivalents:
  WebSearch and WebFetch are your web search, Read, Grep and Glob are reading
  and searching files, Write and Edit are writing files, Bash is the shell.
- **Gates.** A hook runs `gate.py` after each file write. When it reports a
  failure, fix the document and continue; do not disable or bypass it.
- **Web budget.** If a note says the session's web cap is reached, stop
  searching, finish the current stage with what is on disk, and register what
  is missing with `python3 .claude/scripts/wanted.py`.

Write every run's files under `outputs/<date>-<slug>/`, scaffolded with
`.claude/scripts/new_run.sh` as the skill says.
