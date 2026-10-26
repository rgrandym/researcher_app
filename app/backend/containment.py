"""The folders an agent may touch: the workspace and the app's own data, nothing else.

Agents search the web freely, but on disk they stay inside the project. Their scratch
space (`TMPDIR`, Claude Code's scratchpad) and their memory are folders in `app/data/`, so
ordinary work never leaves it. A tool call that reaches outside anyway is refused before it
reaches the author, with a message that tells the agent where to work instead.

System folders that hold programs (`/usr`, `/bin`, `/opt`, `/dev/null`) are not the
author's files and stay usable, so `python3` and `2>/dev/null` run as before. What is
fenced off is the home folder outside the project, other users, temporary folders and
mounted volumes.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

from backend import config

SCRATCH = config.DATA / "scratch"
MEMORY = config.DATA / "memory"

# Absolute prefixes that count as "outside" when a path is not under an allowed root.
FENCED = ("/Users", "/home", "/tmp", "/private", "/var", "/Volumes", "/root")

PATH_KEYS = ("file_path", "path", "notebook_path")

REFUSAL = (
    "Blocked: agents in this app work only inside the project folder ({root}). "
    "Use files in the project, its runs and their external_data; for scratch work use "
    "{scratch} (it is $TMPDIR). Do not ask the author for access to other folders."
)


def roots() -> list[str]:
    return [os.path.realpath(p) for p in (config.ROOT, config.DATA)]


def _inside(path: str, allowed: list[str]) -> bool:
    real = os.path.realpath(path)
    return any(real == r or real.startswith(r + os.sep) for r in allowed)


def _fenced(path: str) -> bool:
    real = os.path.realpath(path)
    return any(real == f or real.startswith(f + "/") for f in FENCED) or any(
        path == f or path.startswith(f + "/") for f in FENCED
    )


def outside(path: str, cwd: Path | None = None) -> bool:
    """True when `path` names a fenced folder outside the workspace."""
    if not path:
        return False
    path = os.path.expanduser(path.replace("$HOME", "~").replace("${HOME}", "~"))
    if not os.path.isabs(path):
        path = os.path.join(str(cwd or config.ROOT), path)
    return _fenced(path) and not _inside(path, roots())


def _bash_paths(command: str) -> list[str]:
    try:
        words = shlex.split(command, comments=True)
    except ValueError:
        words = command.split()
    found = []
    for word in words:
        # `--out=/tmp/x`, `2>/tmp/log`, `>~/x`: take the path after the last `=` or `>`.
        for part in re.split(r"[=>]", word):
            part = part.strip("'\"();")
            if part.startswith(("/", "~", "$HOME", "${HOME}")):
                found.append(part)
    return found


def violation(tool: str, args: dict[str, Any]) -> str | None:
    """The refusal message when this tool call reaches outside the project, else None."""
    paths = [str(args[k]) for k in PATH_KEYS if isinstance(args.get(k), str)]
    if tool == "Bash" and isinstance(args.get("command"), str):
        paths += _bash_paths(args["command"])
    if any(outside(p) for p in paths):
        return REFUSAL.format(root=config.ROOT, scratch=SCRATCH)
    return None


def env(env: dict[str, str]) -> dict[str, str]:
    """Point every temporary file an agent or its scripts make into the project."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for key in ("TMPDIR", "TMP", "TEMP", "CLAUDE_CODE_TMPDIR"):
        env[key] = str(SCRATCH)
    return env


def memory_dir() -> str:
    MEMORY.mkdir(parents=True, exist_ok=True)
    return str(MEMORY)
