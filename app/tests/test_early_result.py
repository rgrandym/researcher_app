"""A resumed Claude session can report a result for its queued notices before it reads the
new prompt. That early result must not end the turn: the real reply follows it."""

import asyncio
import json
from typing import Any

from backend.providers.base import TurnOptions
from backend.providers.claude import ClaudeParser, _ControlSession


class _Stdin:
    def __init__(self) -> None:
        self.closed = False

    def write(self, data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def is_closing(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class _Stdout:
    def __init__(self, msgs: list[dict[str, Any]]) -> None:
        self.lines = [(json.dumps(m) + "\n").encode() for m in msgs]

    async def readline(self) -> bytes:
        return self.lines.pop(0) if self.lines else b""


class _Proc:
    def __init__(self, msgs: list[dict[str, Any]]) -> None:
        self.stdin = _Stdin()
        self.stdout = _Stdout(msgs)
        self.returncode = None


def _drive(msgs: list[dict[str, Any]]) -> tuple[ClaudeParser, _Proc, list[Any]]:
    seen: list[Any] = []

    async def on_event(ev: Any) -> None:
        seen.append(ev)

    async def ask(_req: Any) -> Any:
        raise AssertionError("no permission expected")

    proc = _Proc(msgs)
    parser = ClaudeParser("claude-sub")
    session = _ControlSession(proc, parser, on_event, ask, TurnOptions())  # type: ignore[arg-type]
    asyncio.run(session.loop("go"))
    return parser, proc, seen


READY = {"type": "control_response", "response": {"subtype": "success", "request_id": "init"}}
EARLY = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0, "num_turns": 0, "session_id": "s"}
REPLY = {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [{"type": "text", "text": "On it."}]}}
FINAL = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.5, "num_turns": 3, "session_id": "s"}


def test_early_result_does_not_end_the_turn() -> None:
    parser, proc, seen = _drive([READY, EARLY, REPLY, FINAL])
    assert parser.result is not None and parser.result["total_cost_usd"] == 0.5
    assert any(e.type == "assistant_text" for e in seen)
    assert proc.stdin.closed


def test_error_result_still_ends_at_once() -> None:
    failed = {**EARLY, "is_error": True, "subtype": "error_during_execution"}
    parser, _, _ = _drive([READY, failed, REPLY, FINAL])
    assert parser.result is not None and parser.result["is_error"] is True
