# Research

A local app over this research workspace: a prompt bar that takes questions and every
workspace command, a live transcript with permission prompts and a Stop button, the
guide, the run folders and their exports, the files that define how the agents behave,
and continuation on another provider when a plan runs out.

The app adds no research logic. It drives an agent runtime (Claude Code, or Codex as
the fallback) in the workspace root, so `CLAUDE.md`, the skills, the subagents and the
`gate.py` hook apply exactly as they do in VS Code. VS Code keeps working unchanged;
the app is a second door into the same folder.

## Run it

Development, with reload on both sides:

```bash
bash app/scripts/dev.sh              # backend :8765, front end :5174, opens the app window
bash app/scripts/dev.sh --no-update  # skip the CLI version check
bash app/scripts/dev.sh --stop
```

Both scripts run in the app's own conda env, `research_app`, through
`scripts/env.sh`: it creates the env on first use, re-syncs it whenever
`requirements.txt` changes (the backend, plus matplotlib and weasyprint for the
workspace's figure and PDF scripts), and updates Claude Code and Codex through the
install each came from when a newer release exists. The app opens as a Chrome app
window; closing it stops the backend and the front end about 15 seconds later (if an
agent turn is running, you are asked first). Ctrl-C also stops both.

The macOS app:

```bash
bash app/mac/build_app.sh          # writes ~/Applications/Research.app
```

Or double-click `Build Research App.command`. Then drag Research to the Dock. The first time it opens, macOS asks whether Research may access your Desktop folder, where this workspace lives: click OK. If you clicked Don't Allow, turn it on in System Settings > Privacy & Security > Files and Folders > Research. It opens as a Chrome app window
on its own profile (no tabs, your usual Chrome untouched), and the backend stops about
20 seconds after you close the window, unless a turn is running, when it asks first.
The build records the absolute paths of `python3`, `claude`, `node`, `code` and
`pandoc` in `app/data/paths.json`, because an app
started from the Dock does not get the shell's `PATH`; rebuild after moving any of them.
Codex is found at each start instead, since its folder moves with every VS Code
extension update.

Outside the env, the app needs conda, Node 20+ and pandoc (Homebrew's), and Chrome for
the app window. The Dock app runs the same env step at every launch.

## Test it

All tests run offline, on recorded or constructed fixtures. None makes a model call.

```bash
conda activate research_app && cd app && python -m pytest -q
uvx ruff check backend tests mac && uvx ruff format --check backend tests mac
uvx --with pydantic --with fastapi --with uvicorn mypy --strict backend
cd web && npm run typecheck && npm run lint && npm run build
```

## How it is built

```text
app/
  backend/
    main.py            FastAPI: REST for the views, /api/ws/session for live turns, serves web/dist
    turns.py           one running turn per session; permissions, run locks, limits, handoffs
    router.py          the model and effort for a turn, from the command it starts with
    providers/claude.py  the claude CLI over the Agent SDK's wire protocol (stream-json + stdio permissions)
    providers/codex.py   codex exec --json, with the adapter (preamble, command expansion, overrides)
    handoff.py         the handoff packet, built from the transcript and the run folders
    sessions.py        app/data/sessions/<id>/: session.json, transcript.jsonl, handoffs/
    workspace.py       commands, runs, exports, the guide; checked and committed Workspace saves
    activity.py        agents, progress, cost and web caps for the Activity panel
    render.py          HTML, figures and PDF of a run's master, by the workspace's export scripts
    usage.py           plan windows and the error classifier
    keychain.py        API keys in the macOS Keychain
  prompts/             the Codex preamble, the handoff templates, the "Improve" instructions
  web/                 React 18, TypeScript, Vite, Tailwind, Zustand, TanStack Query
  mac/                 launcher.py, build_app.sh, icon.png
  tests/               fixtures/ and the offline suite
  docs/spike.md        what was confirmed on the installed versions, and what is still open
```

Every REST and WebSocket call carries a per-launch token, and the server binds to
127.0.0.1 and checks the Host header. API keys live in the Keychain. The app writes to
`.claude/` and the root rule files only when you save in the Workspace view (one
commit per save, never pushed), to `.claude/monitor.json` when you change the web
caps, into a run's `external_data/` when you attach a file, to a run's Markdown when
you save it from the Edit tab, and into `<run>/export/<style>/` when you export. Removing
a project moves its run folder to the macOS Trash.

## Reports: Markdown, HTML, figures, PDF

A run opens on its master rendered as Markdown. The HTML tab renders it with the
workspace's own export chain (`figures.py`, `references.py`, `style.py`, pandoc) in any
style from `.claude/styles/`, with citations as author and year or as evidence IDs; the
figures appear beside it as PNG and SVG downloads. Export HTML and Export PDF write into
`<run>/export/<style>/` and run `check_export.py`. The Edit tab edits the Markdown, the
source of every format; a save is refused if the file changed on disk meanwhile, and
the HTML re-renders from the saved file. No model call is involved in any of this.

## Cost

Each turn's model and effort follow the command it starts with (`backend/router.py`).
Research, drafting, critique and repair run on the frontier tier (Opus, `gpt-6-astra`);
`/verify`, `/export` and plain chat on the workhorse tier (Sonnet, `gpt-6.1-sol`);
`/app` questions on the fast tier (Haiku, `gpt-6-luna`). The maps are in Models
and in `app/data/settings.json` under `routing`; turning routing off returns every turn
to the connection's own model and the effort meter. Each turn's route shows as a faint
line in the transcript.

A typed command also starts a fresh conversation with the agent, because every command
works from its run folder; the prompt names the session's run. A reply without a command
continues that conversation on the command's tier. Both behaviours are switches in Models.

A project's **Chat** tab holds a conversation tied to that run (`project` on the session):
each new agent conversation in it is told the run and its master, so nothing needs naming.
`POST /api/runs/{name}/chat` returns the project's latest conversation, or a new one with
`{"new": true}`.

With `staged_pipeline` on (Models), `/research-pipeline` runs one stage per fresh
conversation: gather, draft, review, finish. When a turn ends, `turns.py` checks the run's
files through `run_check.py`; a complete stage starts the next, an incomplete one waits for
the author. The session's `pipeline` field records where it is.

Commands listed under `hidden_commands` in `app/data/settings.json` leave the command
menu and are refused if typed; the list is empty by default.

The app spends model tokens only when you send a turn. Titles, listings, stage status,
handoff packets and limit detection are built by code. "Test" on a connection checks
the binary and the sign-in; only "Send a test message" makes a model call. The app
never switches provider by itself and never retries after a limit.
