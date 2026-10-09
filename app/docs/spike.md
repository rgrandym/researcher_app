# Phase 0 findings

Checked on 2026-10-09 against Claude Code 2.1.292 and codex-cli 0.162.0-alpha.2.
Live turns were the smallest that answer the question, with no web search. Items
marked **open** need the author: they could not be settled here without spending a
plan down, or the live check was refused in the build session.

## Claude Code

**Runtime.** The Agent SDK for Python is not installed in this environment. The SDK is
a wrapper over the `claude` CLI, and its wire protocol is simple: stream-json in and
out, with `--permission-prompt-tool stdio` so each permission the settings do not
already grant arrives as a `control_request` of subtype `can_use_tool`, answered with
a `control_response`. The app speaks that protocol directly
(`backend/providers/claude.py`), which keeps the permission callback and adds no
dependency. Confirmed live twice: once by hand, once through the app's own runner,
with a Bash permission request answered from the manager.

**Project skills, agents and settings load.** With the workspace as working directory
and `--setting-sources user,project,local`, the `init` message listed all thirteen
workspace skills, the five workspace commands among its slash commands, and the three
workspace agents (`research-scout`, `source-verifier`, `report-critic`). The project's
`PostToolUse` hook loads with the project settings; its run is not echoed in the stream
unless `--include-hook-events` is passed, so it was not observed directly. **Open:**
confirm in the transcript of a real run that `gate.py` fired after a write to a master.

**Slash commands.** They pass through as typed; the CLI lists the workspace commands
in `slash_commands`. **Open:** a real `/research` turn was not run, to avoid spending
web searches.

**Plan windows.** Recorded: every turn carries a `rate_limit_event` whose
`rate_limit_info.unifiedWindows` gives `five_hour` and `seven_day` utilisation and
reset times (fixture `tests/fixtures/claude_turn.jsonl`, with the account details
removed).

**Limit and auth expiry.** **Open.** Neither can be produced without spending a plan
down or signing out. The classifier treats a `rate_limit_event` with
`status: "rejected"` as the authoritative signal and also matches the known message
forms ("You've hit your limit", "usage limit reached|<epoch>", "credit balance is too
low", 429, "Invalid API key · Please run /login", expired OAuth token). The fixtures
`claude_limit.jsonl` and `claude_auth.jsonl` are constructed, and say so. The first
time either happens for real, the `error` event in the session's `transcript.jsonl`
carries the message text; add it to the classifier tests.

**Research monitor.** `.claude/skills/research-monitor/` does not exist yet (the copy in
Appendix A is the author's step). The app passes it in `CLAUDE_CODE_PLUGIN_DIRS` when
it is present, and the transcript notes "research monitor not loaded" until then.

**Models.** The CLI's `initialize` handshake returns the model list and each model's
effort levels without a model call; the Models view uses it.

## Codex

**Installed copy.** The VS Code ChatGPT extension's binary, not on `PATH`:
`~/.vscode/extensions/openai.chatgpt-26.1002.51308-darwin-arm64/bin/macos-aarch64/codex`,
version 0.162.0-alpha.2 (it has updated since the spec was written; two extension
versions sit side by side). The backend resolves it on every call: `PATH`, then the
newest extension copy, then `/Applications/Codex.app`. Signed in with a ChatGPT Plus
plan; `codex login status` and `codex debug models` answer without a model call.

**Plan usage.** `codex app-server` returns the windows: on 2026-10-09 the 5-hour window
was at 0 % and the 7-day at 40 %, for both apps sharing the plan.

**Instructions.** `AGENTS.md` at the workspace root sends Codex to `CLAUDE.md` and the
voice profile. `~/.codex/AGENTS.md` is empty, so nothing global conflicts.

**Trust and hooks.** This workspace is not in the trusted projects of
`~/.codex/config.toml`. The app passes `projects."<root>".trust_level="trusted"` as a
`-c` override on each run instead of editing the shared file. **Open:** confirm that
`.codex/hooks.json` fires under that override (look for "Checking the report against
the gates" in a run that writes a master). If it does not, trust the project once as
Appendix A describes.

**Skills.** Codex has a `skill_search` feature over its own skill folders but does not
read `.claude/skills`. The app expands `/name args` itself, as the spec's default.

**Subagents.** `multi_agent` is a stable, enabled feature in this version, so the
preamble asks Codex to run each review step in its own subagent with the agent file as
instructions. The adapter marks a turn "reduced isolation" when `/research`,
`/research-pipeline`, `/verify` or `/critique` finishes with no subagent item in the
stream. **Open:** the item type Codex emits for a spawned subagent has not been
recorded; the parser matches any non-message item whose type names an agent.

**Live turn.** **Open.** The build session's permission classifier refused a live
`codex exec` turn, so the Codex fixtures are built from the documented `codex exec --json` event shapes (`thread.started`, `item.started` / `item.completed`,
`turn.completed`, `turn.failed`, `error`). The limit message in `codex_limit.jsonl` is
constructed. Three overrides want confirming on the first live turn:
`web_search="live"` / `"disabled"` (the key that switches web search off),
`sandbox_workspace_write.network_access=true`, and `CODEX_API_KEY` for the API-key
connection (it keeps the shared ChatGPT sign-in untouched).

**Permissions.** `codex exec` cannot ask: it runs with `approval_policy="never"` inside
the workspace-write sandbox, which is the sandbox, not a bypass.

## The smallest checks for the author

1. `bash app/scripts/dev.sh`, then send "list the files in `.claude/skills`" on Claude
   Code. Expect a permission prompt or none, a reply, and cost in Activity.
2. Pick Codex in the status line and send the same. Expect a handoff card, then the
   reply. This confirms the Codex event shapes and the trust override.
3. After the first real limit, copy the message from the `error` event in
   `app/data/sessions/<id>/transcript.jsonl` into `tests/test_parsers.py`, so the
   classifier stays tested against it.
