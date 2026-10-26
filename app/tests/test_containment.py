"""Agents stay inside the workspace: requests for other folders are refused, not asked."""

from __future__ import annotations

from backend import config, containment
from backend.providers.claude import ClaudeProvider


def blocked(tool: str, **args: str) -> bool:
    return containment.violation(tool, args) is not None


def test_project_files_pass() -> None:
    assert not blocked("Read", file_path=str(config.ROOT / "outputs/run/report.md"))
    assert not blocked("Read", file_path="outputs/run/external_data/a.pdf")
    assert not blocked("Write", file_path=str(containment.SCRATCH / "x/y.py"))
    assert not blocked("Grep", path=".claude/scripts")


def test_other_folders_are_refused() -> None:
    assert blocked("Read", file_path="/Volumes/usb/Documents/secret.docx")
    assert blocked("Write", file_path="~/.claude-other/projects/p/memory/a.md")
    assert blocked("Glob", path="/tmp/scout")
    assert blocked("Read", file_path="/private/tmp/scoutr1/x.csv")
    assert blocked("Read", file_path="../../other-project/notes.md")


def test_bash_paths() -> None:
    assert blocked("Bash", command="mkdir -p /tmp/rv5 && cd /tmp/rv5 && unzip -q x.docx")
    assert blocked("Bash", command="echo hi >> ~/.claude/memory/MEMORY.md")
    assert blocked("Bash", command="cp a.md $HOME/Desktop/a.md")
    assert blocked("Bash", command="python3 x.py --out=/tmp/out.json")
    assert not blocked("Bash", command="python3 .claude/scripts/gate.py outputs/r/report.md 2>/dev/null")
    assert not blocked("Bash", command="/usr/bin/env python3 -c 'print(1)'")
    assert not blocked("Bash", command=f"cd {config.ROOT} && ls outputs")
    assert not blocked("WebFetch", url="https://example.org/tmp/page")


def test_turns_use_project_scratch_and_memory() -> None:
    provider = ClaudeProvider("claude-sub")
    env = containment.env({})
    assert env["TMPDIR"] == env["CLAUDE_CODE_TMPDIR"] == str(containment.SCRATCH)
    from backend.providers.base import TurnOptions

    cmd = provider.command("claude", None, TurnOptions())
    settings = cmd[cmd.index("--settings") + 1]
    assert str(containment.MEMORY) in settings
