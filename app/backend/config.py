"""Paths, port and settings for the Research app.

The app lives in `app/` inside the research workspace and always runs its agents
in the workspace root. Its own state (sessions, settings, locks, the port file)
lives in `app/data/`, which is git-ignored. `RESEARCH_APP_DATA` and
`RESEARCH_APP_ROOT` override both locations for tests.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("RESEARCH_APP_ROOT") or APP.parent).resolve()
DATA = Path(os.environ.get("RESEARCH_APP_DATA") or APP / "data").resolve()
PROMPTS = APP / "prompts"
WEB_DIST = APP / "web" / "dist"
SCRIPTS = ROOT / ".claude" / "scripts"
OUTPUTS = ROOT / "outputs"

DEFAULT_PORT = 8765
# Every REST and WebSocket call carries this token. The launcher (or dev.sh) sets it;
# a backend started by hand gets a random one and prints it.
TOKEN = os.environ.get("RESEARCH_APP_TOKEN") or secrets.token_urlsafe(24)

CONNECTIONS = ("claude-sub", "codex-plan", "claude-api", "codex-api")

DEFAULT_SETTINGS: dict[str, Any] = {
    "connections": {
        "claude-sub": {"model": "default", "effort": "high"},
        "claude-api": {"model": "default", "effort": "high"},
        "codex-plan": {"model": "", "effort": "medium"},
        "codex-api": {"model": "", "effort": "medium"},
    },
    "fallback_order": ["claude-sub", "codex-plan", "claude-api"],
    "default_connection": "claude-sub",
    "handover_threshold": 90,
    # Tool permissions the author granted with "Always allow" in the app: {"tool", "rule"}.
    "allow_rules": [],
    # Claude Code's permission mode for the author's turns. "auto", as in VS Code: a
    # classifier approves routine actions and asks only about risky ones. "default" asks
    # before every shell command and file write. Codex runs without prompts in its sandbox.
    "permission_mode": "auto",
    # Asked about whatever the mode: every way the agent deletes a file.
    "ask_rules": [
        "Bash(rm *)",
        "Bash(rmdir *)",
        "Bash(unlink *)",
        "Bash(trash *)",
        "Bash(shred *)",
        "Bash(git rm *)",
        "Bash(git clean *)",
        "Bash(find * -delete*)",
        "Bash(find * -exec rm *)",
    ],
    # /research-pipeline runs one stage per fresh conversation (gather, draft, review,
    # finish), the app starting each when the one before has left its files on disk.
    "staged_pipeline": True,
    # Interface preferences, kept here rather than in the browser: the backend takes a new
    # port at every launch, and a browser's storage is per port, so it would forget them.
    "ui": {
        "theme": "system",
        "agents_view": "cards",
        "sidebar_open": True,
        "activity_open": True,
        "run_panel_open": True,
    },
    # A hand edit saved to a run's master (here or in VS Code) starts /user-edits by itself,
    # once the file has been quiet this long and no agent is working on the run.
    "auto_user_edits": {"enabled": True, "quiet_seconds": 60},
    # Workspace commands this app does not offer: they leave the menu, and a typed one is
    # refused. Empty by default.
    "hidden_commands": [],
    # Model routing (backend/router.py): the command a turn starts with picks a tier and an
    # effort, and each runtime maps the tiers to its models. Off: the connection decides.
    "routing": {
        "enabled": True,
        # A typed command starts a fresh native session: it works from the run folder, so
        # it does not need, or pay to re-read, the conversation before it.
        "fresh": True,
        "tiers": {
            "claude": {"frontier": "opus", "workhorse": "sonnet", "fast": "haiku"},
            "codex": {"frontier": "gpt-6-astra", "workhorse": "gpt-6.1-sol", "fast": "gpt-6-luna"},
        },
        "commands": {
            # Medium effort by default (2026-10-10): good enough for the workspace's commands,
            # and faster and cheaper than high. Raise one command in Models -> routing if needed.
            **{
                name: ["frontier", "medium"]
                for name in (
                    "research",
                    "research-pipeline",
                    "expand",
                    "critique",
                    "report",
                    "repair",
                    "user-edits",
                    "narrator",
                    "polish",
                )
            },
            "figures": ["frontier", "medium"],
            "verify": ["workhorse", "medium"],
            "visualize": ["workhorse", "medium"],
            "voice-rule": ["workhorse", "medium"],
            "export": ["workhorse", "low"],
            "app": ["fast", "low"],
        },
        "chat": ["workhorse", "medium"],
    },
}


def data_dir(*parts: str) -> Path:
    path = DATA.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_settings() -> dict[str, Any]:
    path = DATA / "settings.json"
    try:
        stored = json.loads(path.read_text())
    except (OSError, ValueError):
        stored = {}
    out: dict[str, Any] = json.loads(json.dumps(DEFAULT_SETTINGS))
    for key, value in stored.items():
        if key == "connections" and isinstance(value, dict):
            for conn, conf in value.items():
                if isinstance(conf, dict):
                    out["connections"].setdefault(conn, {}).update(conf)
        elif key == "routing" and isinstance(value, dict):
            _merge_routing(out["routing"], value)
        else:
            out[key] = value
    return out


def _merge_routing(base: dict[str, Any], stored: dict[str, Any]) -> None:
    """A stored routing block overrides the defaults entry by entry, so a settings file
    that names one command or one tier keeps every other default."""
    for key, value in stored.items():
        if key == "tiers" and isinstance(value, dict):
            for runtime, tiers in value.items():
                if isinstance(tiers, dict):
                    base["tiers"].setdefault(runtime, {}).update(tiers)
        elif key == "commands" and isinstance(value, dict):
            base["commands"].update(value)
        else:
            base[key] = value


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    merged = load_settings()
    for key, value in settings.items():
        if key == "connections" and isinstance(value, dict):
            for conn, conf in value.items():
                if isinstance(conf, dict):
                    merged["connections"].setdefault(conn, {}).update(conf)
        elif key == "routing" and isinstance(value, dict):
            _merge_routing(merged["routing"], value)
        elif key in DEFAULT_SETTINGS:
            merged[key] = value
    data_dir()
    (DATA / "settings.json").write_text(json.dumps(merged, indent=2) + "\n")
    return merged


def resolved_paths() -> dict[str, str]:
    """Absolute binaries written by build_app.sh. An app started from the Dock does not
    get the shell's PATH, so it reads them from here."""
    try:
        data = json.loads((DATA / "paths.json").read_text())
        return {k: v for k, v in data.items() if isinstance(v, str)}
    except (OSError, ValueError):
        return {}


def binary(name: str) -> str | None:
    """A CLI by name: paths.json first, then PATH."""
    path = resolved_paths().get(name)
    if path and Path(path).exists():
        return path
    return shutil.which(name)


def python() -> str:
    return binary("python3") or "python3"


def child_env() -> dict[str, str]:
    """Environment for every child process, with the resolved binaries' folders on PATH
    so hooks that call `python3` find the workspace's interpreter."""
    env = dict(os.environ)
    folders = [str(Path(p).parent) for p in resolved_paths().values() if p]
    env["PATH"] = os.pathsep.join([*dict.fromkeys(folders), env.get("PATH", "")])
    env.pop("RESEARCH_APP_TOKEN", None)
    return env
