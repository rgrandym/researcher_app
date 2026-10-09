"""Shared fixtures. Every test runs offline: providers replay recorded JSON lines, and the
workspace is a temporary copy with the scripts the app calls."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from backend import config  # noqa: E402
from backend.providers.base import (  # noqa: E402
    ConnectionStatus,
    OnEvent,
    PermissionHandler,
    PermissionRequest,
    TurnOptions,
    TurnResult,
    UsageWindows,
)
from backend.providers.claude import ClaudeParser  # noqa: E402
from backend.providers.codex import CodexParser  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
REAL_ROOT = APP.parent
RUN = "2026-01-15-lithium-costs"


def lines(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (FIXTURES / name).read_text().splitlines() if line.strip()]


class FakeProvider:
    """A provider that replays a fixture through the real parser. Records every prompt."""

    def __init__(self, id_: str, fixtures: list[str], stderr: str = "") -> None:
        self.id = id_
        self.runtime = "codex" if id_.startswith("codex") else "claude"
        self.billing = "key" if id_.endswith("-api") else "plan"
        self.label = {
            "claude-sub": "Claude Code (subscription)",
            "codex-plan": "Codex (ChatGPT plan)",
        }.get(id_, id_)
        self.fixtures = list(fixtures)
        self.stderr = stderr
        self.prompts: list[tuple[str, str | None]] = []
        self.options: list[TurnOptions] = []
        self.windows = UsageWindows()

    def status(self) -> ConnectionStatus:
        return ConnectionStatus(
            id=self.id,
            label=self.label,
            runtime=self.runtime,
            billing=self.billing,
            installed=True,
            signed_in=True,
        )  # type: ignore[arg-type]

    def usage(self) -> UsageWindows:
        return self.windows

    async def run_turn(
        self,
        prompt: str,
        native_session: str | None,
        on_event: OnEvent,
        cancelled: Callable[[], bool],
        permission: PermissionHandler,
        options: TurnOptions,
    ) -> TurnResult:
        self.prompts.append((prompt, native_session))
        self.options.append(options)
        fixture = self.fixtures.pop(0) if len(self.fixtures) > 1 else self.fixtures[0]
        parser: Any = CodexParser(self.id) if self.runtime == "codex" else ClaudeParser(self.id)
        for msg in lines(fixture):
            if msg.get("type") == "control_request":
                req = msg["request"]
                await permission(
                    PermissionRequest(
                        id=msg["request_id"],
                        tool=req["tool_name"],
                        summary=req.get("description", ""),
                        input=req.get("input", {}),
                        rules=[
                            {"tool": r["toolName"], "rule": r.get("ruleContent", "")}
                            for s in req.get("permission_suggestions", [])
                            for r in s.get("rules", [])
                        ],
                    )
                )
                continue
            for event in parser.feed(msg):
                await on_event(event)
        result: TurnResult = parser.outcome(
            0 if parser.__class__ is CodexParser else 1, self.stderr, cancelled()
        )
        if result.native_session is None:
            result.native_session = native_session
        return result


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "data"
    path.mkdir()
    monkeypatch.setattr(config, "DATA", path)
    return path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: Path) -> Path:
    """A workspace with one research run that got as far as evidence, whose evidence file
    was cut off mid-write, and one export."""
    ws = tmp_path / "ws"
    shutil.copytree(
        REAL_ROOT / ".claude/scripts",
        ws / ".claude/scripts",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(REAL_ROOT / ".claude/styles", ws / ".claude/styles")
    _write(
        ws / ".claude/monitor.json",
        json.dumps(
            {
                "searchCap": 400,
                "fetchCap": 700,
                "warnEvery": 100,
                "raise": {"searches": 100, "fetches": 150},
            }
        ),
    )
    _write(
        ws / ".claude/skills/research/SKILL.md",
        "---\nname: research\ndescription: >\n  Run a sourced\n  investigation.\n---\n\n# Research\n",
    )
    _write(
        ws / ".claude/commands/figures.md",
        "---\ndescription: Improve the figures\n---\n\nImprove the figures. Target: $ARGUMENTS\n",
    )
    run = ws / "outputs" / RUN
    _write(
        run / "prompt.md",
        "# Request\n\n## Verbatim prompt\n\nhow much does battery-grade lithium cost per tonne in 2026\n",
    )
    _write(
        run / "brief.md", "# Brief\n\nQuestion: lithium costs. Sub-questions: SQ1 market prices.\n"
    )
    _write(run / "voice.md", "explanatory\n")
    _write(
        run / "coverage.md",
        "| Sub-question | Status |\n| --- | --- |\n| SQ1 market prices | covered |\n",
    )
    _write(run / "notes/sq1.md", "# SQ1\n\nNotes.\n")
    _write(
        run / "evidence.jsonl",
        '{"id": "E1", "claim": "a"}\n{"id": "E2", "claim": "b"}\n{"id": "E3", "cla',
    )
    _write(run / "export/meridian/report.pdf", "%PDF")
    _write(run / "export/meridian/_styled.md", "intermediate")
    for mod in ("ws_runmeta", "ws_monitor"):
        sys.modules.pop(mod, None)
    monkeypatch.setattr(config, "ROOT", ws)
    monkeypatch.setattr(config, "OUTPUTS", ws / "outputs")
    from backend import activity, workspace

    monkeypatch.setattr(workspace, "_runmeta", None)
    monkeypatch.setattr(activity, "_monitor", None)
    workspace._stage_cache.clear()
    return ws
