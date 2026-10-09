# Continuing a session from another agent

You are taking over a session in this workspace. The previous agent
({{provider}}, {{model}}) stopped at {{time}} because {{reason}}. Read CLAUDE.md
before acting; its rules bind you.

## The author's requests, verbatim

{{requests}}

## Runs touched

{{runs}}

## What the previous agent did last

{{tool_calls}}

The previous agent's last message:

{{last_message}}

## Files changed in the interrupted turn

{{files}}

## Your instructions

1. Check the flagged files first and repair any truncated write.
2. Do not redo a stage that run_check reports complete.
3. Do not search again for a sub-question whose notes file or evidence rows
   already exist. Searching is the most expensive step; reuse what is on disk.
4. Resume at: {{resume_at}}.
5. Tell the author in one line where you are resuming before you continue.
