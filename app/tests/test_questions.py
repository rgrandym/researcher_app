"""AskUserQuestion requests (Claude's own questions, and mods' such as launch-codes)
reach the author as questions, and the answers go back to Claude Code."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.providers.base import PermissionDecision, PermissionRequest, TurnOptions
from backend.providers.claude import ClaudeParser, _ControlSession

QUESTION = {
    "subtype": "can_use_tool",
    "tool_name": "AskUserQuestion",
    "input": {
        "questions": [
            {
                "question": 'Launch codes required: git push --force. Type the 4-character code from the RED ALERT pane under "Other" to arm it.',
                "header": "LAUNCH CODE",
                "options": [
                    {"label": "ABORT", "description": ""},
                    {"label": "ABORT and find a safer way", "description": ""},
                ],
                "multiSelect": False,
            }
        ]
    },
}


class _Stdin:
    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []

    def write(self, data: bytes) -> None:
        self.lines.append(json.loads(data))

    async def drain(self) -> None:
        return None

    def is_closing(self) -> bool:
        return False


class _Proc:
    def __init__(self) -> None:
        self.stdin = _Stdin()
        self.returncode = None


def _run(decision: PermissionDecision) -> tuple[PermissionRequest, dict[str, Any]]:
    seen: list[PermissionRequest] = []

    async def ask(req: PermissionRequest) -> PermissionDecision:
        seen.append(req)
        return decision

    async def on_event(_: Any) -> None:
        return None

    proc = _Proc()
    session = _ControlSession(proc, ClaudeParser("claude-sub"), on_event, ask, TurnOptions())  # type: ignore[arg-type]
    asyncio.run(session._permission("r1", QUESTION))
    return seen[0], proc.stdin.lines[0]["response"]["response"]


def test_question_is_recognised_and_answered() -> None:
    question = QUESTION["input"]["questions"][0]["question"]  # type: ignore[index]
    req, body = _run(PermissionDecision(allow=True, answers={question: "K7XA"}))
    assert (
        req.kind == "question" and req.questions[0]["header"] == "LAUNCH CODE" and req.rules == []
    )
    assert body["behavior"] == "allow"
    assert body["updatedInput"]["answers"] == {question: "K7XA"}
    assert body["updatedInput"]["questions"] == QUESTION["input"]["questions"]  # type: ignore[index]


def test_skipped_question_denies() -> None:
    _, body = _run(PermissionDecision(allow=False, message="The author chose not to answer."))
    assert body["behavior"] == "deny"
