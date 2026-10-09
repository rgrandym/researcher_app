# Instructions for Codex and other agents

This workspace is set up for Claude Code; its rules apply to every agent that works
in it. Before acting, read these two files and treat them as binding:

- `CLAUDE.md`: the ten rules, the two lanes (research reports and the author's own
  writing), the run layout under `outputs/`, and the pipelines.
- `.claude/voice/profile.md`: the author's writing rules, for any prose you write.

The workspace commands (`/research`, `/report`, `/verify`, `/cv` and the rest) are
skills in `.claude/skills/<name>/SKILL.md` and commands in `.claude/commands/<name>.md`.
When the author invokes one, read that file and follow it. Never start one on your
own: a message that does not begin with a command is a chat question, answered
directly with a few searches at most, with no run folder and no subagents; when
it deserves more, name the command that would do it. Where a skill spawns an
agent from `.claude/agents/<name>.md`, run that step in a separate subagent with the
agent file as its instructions: the thread that wrote a draft never reviews it.

`.codex/hooks.json` runs the quality gate after each file write and the research
monitor on prompts and tool calls. Never disable or bypass them.
