You are changing one file that defines how the agents in this workspace behave.
The author asked for the change in plain words. Make it with the Edit tool on the
file named below, and on that file only. You may Read and Grep anything under
`.claude/` to understand the conventions first. You have no web tools.

The workspace's own conventions:

- Doctrine shared by several skills lives in `.claude/references/` and is
  pointed to from each skill, never restated in it. If the change is doctrine
  that belongs in a reference file, say so in your reply instead of copying it.
- A writing rule goes through the `/voice-rule` skill, which also tests any lint
  pattern it adds. If the request is a writing rule, say so in your reply and
  make no edit.
- Keep the file's frontmatter (`name`, `description`) valid.
- Change only what the request needs. Keep the surrounding wording.

When you finish, reply with two or three sentences on what you changed and why.

File to edit: {{path}}
(Its original lives at {{original}}; edit the copy named above.)

The author's request:

{{request}}
