"""The provider protocol and the provider-neutral events both runtimes normalise into.

The UI and the session store only ever see `Event`s. A provider is an agent runtime
(Claude Code, Codex) that runs its own loop with file, shell, web and subagent tools in
the workspace root; the app feeds it prompts and watches it work.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

EventType = Literal[
    "user",  # the author's message (written by the app, never by a provider)
    "session",  # the provider opened or resumed its native session
    "assistant_text",
    "tool_call",
    "tool_result",
    "permission_request",
    "permission_answer",
    "usage",
    "notice",  # cap reached, reduced isolation, stale configuration, gate result
    "error",
    "done",
    "handoff",  # a packet was sent to a new provider
]
ErrorKind = Literal["limit", "auth", "context", "network", "other"]
EndReason = Literal["done", "limit", "auth", "context", "network", "error", "stopped"]


class Event(BaseModel):
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)
    # The subagent that produced the event (its spawning tool call id); None = main thread.
    agent: str | None = None
    provider: str | None = None


class ConnectionStatus(BaseModel):
    id: str
    label: str
    runtime: Literal["claude", "codex"]
    billing: Literal["plan", "key"]
    installed: bool
    path: str | None = None
    version: str | None = None
    signed_in: bool = False
    message: str = ""
    models: list[dict[str, Any]] = Field(default_factory=list)
    account: str | None = None  # the email a subscription is signed in as
    removable: bool = False  # an extra Claude account the author added in Models


class UsageWindow(BaseModel):
    name: str  # "5h", "7d"
    used_percent: float | None = None
    resets_at: float | None = None  # epoch seconds
    status: str | None = None  # "allowed", "allowed_warning", "rejected"


class UsageWindows(BaseModel):
    windows: list[UsageWindow] = Field(default_factory=list)
    updated_at: float | None = None
    note: str = ""


class TurnResult(BaseModel):
    native_session: str | None = None
    end_reason: EndReason = "done"
    error: str = ""
    resets_at: float | None = None
    cost_usd: float | None = None
    files_touched: list[str] = Field(default_factory=list)


class PermissionRequest(BaseModel):
    id: str
    tool: str
    summary: str
    input: dict[str, Any] = Field(default_factory=dict)
    # Rules that "Always allow" would add, as the provider proposes them.
    rules: list[dict[str, str]] = Field(default_factory=list)
    agent: str | None = None
    # "question": an AskUserQuestion call (the model's own, or a mod's, such as the
    # launch-codes check) that the author answers rather than allows.
    kind: Literal["permission", "question"] = "permission"
    questions: list[dict[str, Any]] = Field(default_factory=list)


class PermissionDecision(BaseModel):
    allow: bool
    always: bool = False
    message: str = ""
    # The author's answers to a question request, keyed by question text.
    answers: dict[str, str] | None = None


OnEvent = Callable[[Event], Awaitable[None]]
PermissionHandler = Callable[[PermissionRequest], Awaitable[PermissionDecision]]


class TurnOptions(BaseModel):
    model: str = ""
    effort: str = ""
    web_off: bool = False  # Codex: hard stop once the search cap is reached
    # Restrict the turn ("Improve with an agent"): allowed tools and an editable path.
    tools: list[str] | None = None
    edit_path: str | None = None
    system_append: str = ""
    # Claude Code's permission mode for the turn; empty means "default" (ask for each
    # action). Turns started by the author use the app setting, which matches VS Code.
    permission_mode: str = ""
    # Ask rules passed to Claude Code for this turn (`--settings`); they prompt even in
    # auto mode. The app uses them to ask before anything is deleted.
    ask_rules: list[str] = Field(default_factory=list)


class Provider(Protocol):
    id: str
    label: str

    def status(self) -> ConnectionStatus: ...

    def usage(self) -> UsageWindows | None: ...

    async def run_turn(
        self,
        prompt: str,
        native_session: str | None,
        on_event: OnEvent,
        cancelled: Callable[[], bool],
        permission: PermissionHandler,
        options: TurnOptions,
    ) -> TurnResult: ...


class ProviderError(Exception):
    pass


def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """End a CLI and its tool children. Providers launch each CLI in its own process group."""
    if proc.returncode is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass


Billing = Literal["plan", "key"]


def as_dict(value: Any) -> dict[str, Any]:
    """`value` when it is a JSON object, else an empty one."""
    return value if isinstance(value, dict) else {}


def end_reason(kind: ErrorKind) -> EndReason:
    """The turn's end reason for a classified provider error."""
    return "error" if kind == "other" else kind


def short(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def tool_summary(name: str, args: dict[str, Any]) -> tuple[str, list[str]]:
    """A one-line summary of a tool call and the files it names."""
    files = [str(args[k]) for k in ("file_path", "path", "notebook_path") if args.get(k)]
    for key in ("command", "url", "query", "pattern", "description", "prompt", "skill"):
        if args.get(key):
            lead = files[0] if files and key != "command" else ""
            return short(f"{lead} {args[key]}".strip()), files
    if files:
        return short(files[0]), files
    return short(", ".join(f"{k}={v}" for k, v in list(args.items())[:3])), files
