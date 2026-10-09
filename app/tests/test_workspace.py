"""Workspace reads: commands from the real .claude/, runs and exports from a fixture
outputs/, and the checks that block a bad save."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REAL_ROOT, RUN

from backend import config, workspace


def test_commands_from_real_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "ROOT", REAL_ROOT)
    names = {c["name"]: c for c in workspace.commands()}
    for expected in (
        "research",
        "research-pipeline",
        "report",
        "verify",
        "critique",
        "repair",
        "export",
        "expand",
        "compose",
        "cv",
        "cover-letter",
        "answer",
        "develop",
        "polish",
        "user-edits",
        "narrator",
        "visualize",
        "voice-rule",
    ):
        assert expected in names, expected
        assert names[expected]["description"], expected
    assert names["cv"]["kind"] == "command" and names["research"]["kind"] == "skill"


def test_frontmatter() -> None:
    meta = workspace.frontmatter("---\nname: x\ndescription: >\n  folded\n  text\n---\nbody")
    assert meta == {"name": "x", "description": "folded text"}
    assert workspace.frontmatter("no frontmatter") is None
    assert workspace.frontmatter("---\nname: x\n") is None


def test_expand_command(root: Path) -> None:
    text, name = workspace.expand_command("/research lithium costs")
    assert (
        name == "research"
        and ".claude/skills/research/SKILL.md" in text
        and "lithium costs" in text
    )
    text, name = workspace.expand_command("/cv the posting")
    assert name == "cv" and "Target: the posting" in text and "$ARGUMENTS" not in text
    assert workspace.expand_command("plain question") == ("plain question", None)
    assert workspace.expand_command("/nonexistent x") == ("/nonexistent x", None)


def test_runs_and_exports(root: Path) -> None:
    runs = workspace.list_runs()
    assert [r["name"] for r in runs] == [RUN]
    assert runs[0]["kind"] == "research" and runs[0]["prompt"].startswith(
        "how much does battery-grade lithium"
    )
    detail = workspace.run_detail(RUN)
    stages = {s["stage"]: s["ok"] for s in detail["stages"]}
    assert stages["evidence"] and not stages["report"]
    assert detail["evidence_rows"] == 2  # the torn third line does not count
    exports = workspace.list_exports()
    assert [e["name"] for e in exports] == [
        "report.pdf"
    ]  # the _styled.md intermediate is not listed
    with pytest.raises(ValueError):
        workspace.run_file(RUN, "../../etc/passwd")
    with pytest.raises(ValueError):
        workspace.run_dir("../x")


def test_checks(root: Path) -> None:
    assert workspace.check(".claude/skills/new/SKILL.md", "---\nname: new\n---\nbody") == [
        "The frontmatter has no `description`."
    ]
    assert (
        workspace.check(".claude/skills/new/SKILL.md", "---\nname: new\ndescription: d\n---\nbody")
        == []
    )
    assert "missing or not closed" in workspace.check(".claude/commands/x.md", "no frontmatter")[0]
    settings = {
        "hooks": {
            "PostToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'python3 "${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/nope.py" --hook',
                        }
                    ]
                }
            ]
        }
    }
    problems = workspace.check(".claude/settings.json", json.dumps(settings))
    assert problems and "nope.py" in problems[0]
    settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"] = (
        'python3 "${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/run_check.py"'
    )
    assert workspace.check(".claude/settings.json", json.dumps(settings)) == []
    assert workspace.check(".claude/settings.json", "{not json")[0].startswith("Not valid JSON")
    assert workspace.check(".claude/scripts/x.py", "def broken(:\n")[0].startswith(
        "Python does not compile"
    )
    assert workspace.check(".claude/scripts/x.py", "print('ok')\n") == []


def test_editable_scope(root: Path) -> None:
    (root / "dossier").mkdir()
    for bad in ("dossier/cv.md", f"outputs/{RUN}/brief.md", "../outside.md", ".git/config"):
        with pytest.raises(ValueError):
            workspace.editable(bad)
    assert workspace.editable(".claude/skills/research/SKILL.md")
    assert workspace.editable(".claude/skills/brand-new/SKILL.md")  # a new skill from the template


def test_save_commits_only_that_file(root: Path, tmp_path: Any) -> None:
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        ).stdout

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("add", ".claude")
    git("commit", "-qm", "base")
    (root / ".claude/commands/cv.md").write_text(
        "---\ndescription: changed elsewhere\n---\n"
    )  # an unrelated edit
    result = workspace.save(
        ".claude/skills/research/SKILL.md",
        "---\nname: research\ndescription: new\n---\n",
        "Edit research skill: test",
    )
    assert result["ok"] and result["commit"]
    assert git("show", "--name-only", "--format=", "HEAD").split() == [
        ".claude/skills/research/SKILL.md"
    ]
    assert "cv.md" in git("status", "--short")  # left uncommitted
    history = workspace.history(".claude/skills/research/SKILL.md")
    assert history[0]["message"] == "Edit research skill: test"
    restored = workspace.restore(".claude/skills/research/SKILL.md", history[1]["rev"])
    assert (
        restored["ok"]
        and "Run a sourced" in (root / ".claude/skills/research/SKILL.md").read_text()
    )

    blocked = workspace.save(
        ".claude/skills/research/SKILL.md", "---\nname: research\n---\n", "bad"
    )
    assert not blocked["ok"] and "description" in blocked["problems"][0]
