"""Claude Code as an agent runtime.

The app drives the `claude` CLI over the same wire protocol the Claude Agent SDK uses:
stream-json in and out, with `--permission-prompt-tool stdio` so every permission the
project's settings do not already grant arrives as a `can_use_tool` control request the
author answers in the UI. Running in the workspace root with user, project and local
setting sources loads `CLAUDE.md`, `.claude/skills`, `.claude/agents` and the `gate.py`
hook exactly as a VS Code session does. Slash commands pass through as typed.

`ClaudeParser` turns stream-json messages into neutral events and is shared with the
offline tests, which replay recorded fixtures through it.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend import config, keychain, usage
from backend.providers.base import (
    Billing,
    ConnectionStatus,
    Event,
    OnEvent,
    PermissionDecision,
    PermissionHandler,
    PermissionRequest,
    ProviderError,
    TurnOptions,
    TurnResult,
    UsageWindows,
    as_dict,
    end_reason,
    short,
    tool_summary,
)

STREAM_LIMIT = 64 * 1024 * 1024  # one JSON line can carry a whole tool result
TURN_TIMEOUT_S = 6 * 3600  # a full pipeline run is long; Stop is the real control
# A `result` that comes before the model has said anything for this prompt is not this
# turn's end: a resumed session first drains what it had queued (notices of tasks a closed
# process left behind) and reports a result for that. The real reply gets this long to start.
EARLY_RESULT_GRACE_S = 120
AGENT_TOOLS = ("Agent", "Task")
MONITOR_MOD = config.ROOT / ".claude" / "skills" / "research-monitor"
STRIP_FOR_PLAN = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def claude_binary() -> str | None:
    if found := config.binary("claude"):
        return found
    home = Path.home()
    for p in (
        home / ".claude/local/claude",
        home / ".local/bin/claude",
        Path("/opt/homebrew/bin/claude"),
    ):
        if p.exists():
            return str(p)
    return None


# ------------------------------------------------------------------ parsing


class ClaudeParser:
    """Normalises one turn's stream-json messages into `Event`s."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.session_id: str | None = None
        self.result: dict[str, Any] | None = None
        self.limit_resets: float | None = None
        self.limit_rejected = False
        self.agents: dict[str, dict[str, Any]] = {}  # Agent tool_use id -> subagent info
        self.files: set[str] = set()
        self._seen_usage: set[str] = set()
        self.context_tokens = 0

    def _event(self, type_: Any, data: dict[str, Any], agent: str | None = None) -> Event:
        return Event(type=type_, data=data, agent=agent, provider=self.provider)

    def feed(self, msg: dict[str, Any]) -> list[Event]:
        kind = msg.get("type")
        agent = msg.get("parent_tool_use_id") or None
        if kind == "system":
            return self._system(msg)
        if kind == "assistant":
            return self._assistant(msg, agent)
        if kind == "user":
            return self._user(msg, agent)
        if kind == "rate_limit_event":
            return self._rate_limit(msg)
        if kind == "result":
            self.result = msg
            self.session_id = msg.get("session_id") or self.session_id
            return [self._result_usage(msg)]
        return []

    def _system(self, msg: dict[str, Any]) -> list[Event]:
        sub = msg.get("subtype")
        if sub == "init":
            self.session_id = msg.get("session_id")
            plugins = [p.get("name") for p in msg.get("plugins") or [] if isinstance(p, dict)]
            return [
                self._event(
                    "session",
                    {
                        "session_id": self.session_id,
                        "model": msg.get("model"),
                        "permission_mode": msg.get("permissionMode"),
                        "skills": len(msg.get("skills") or []),
                        "agents": msg.get("agents") or [],
                        "plugins": plugins,
                        "monitor_loaded": any("research-monitor" in str(p) for p in plugins),
                    },
                )
            ]
        if sub == "compact_boundary":
            return [
                self._event(
                    "notice", {"kind": "compact", "text": "The conversation was compacted."}
                )
            ]
        return []

    def _assistant(self, msg: dict[str, Any], agent: str | None) -> list[Event]:
        message = msg.get("message") or {}
        events: list[Event] = []
        mid = str(message.get("id") or "")
        u = message.get("usage") or {}
        if u and mid not in self._seen_usage:  # one message arrives once per content block
            self._seen_usage.add(mid)
            tokens_in = sum(
                int(u.get(k) or 0)
                for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            )
            if agent is None:
                self.context_tokens = tokens_in
            events.append(
                self._event(
                    "usage",
                    {
                        "tokens_in": tokens_in,
                        "tokens_out": int(u.get("output_tokens") or 0),
                        "context_tokens": tokens_in if agent is None else None,
                    },
                    agent,
                )
            )
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                events.append(self._event("assistant_text", {"text": block["text"]}, agent))
            elif block.get("type") == "tool_use":
                name = str(block.get("name") or "")
                args = as_dict(block.get("input"))
                summary, files = tool_summary(name, args)
                self.files.update(files)
                data: dict[str, Any] = {
                    "id": block.get("id"),
                    "name": name,
                    "summary": summary,
                    "files": files,
                    "input": _trim(args),
                }
                if name in AGENT_TOOLS:
                    info = {
                        "type": args.get("subagent_type") or "general-purpose",
                        "description": str(args.get("description") or ""),
                    }
                    self.agents[str(block.get("id"))] = info
                    data["subagent"] = info
                events.append(self._event("tool_call", data, agent))
        return events

    def _user(self, msg: dict[str, Any], agent: str | None) -> list[Event]:
        content = (msg.get("message") or {}).get("content")
        if not isinstance(content, list):
            return []
        events = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            text = _result_text(block.get("content"))
            tid = str(block.get("tool_use_id") or "")
            data = {"id": tid, "is_error": bool(block.get("is_error")), "summary": short(text, 300)}
            if tid in self.agents:
                data["subagent_done"] = True
            if "research-monitor" in text and ("cap" in text.lower() or "budget" in text.lower()):
                events.append(
                    self._event("notice", {"kind": "cap", "text": short(text, 400)}, agent)
                )
            events.append(self._event("tool_result", data, agent))
        return events

    def _rate_limit(self, msg: dict[str, Any]) -> list[Event]:
        info = msg.get("rate_limit_info") or {}
        if not isinstance(info, dict):
            return []
        windows = usage.record_claude_limit(info)
        if info.get("status") == "rejected":
            self.limit_rejected = True
            if info.get("resetsAt"):
                self.limit_resets = float(info["resetsAt"])
        return [self._event("usage", {"windows": [w.model_dump() for w in windows.windows]})]

    def _result_usage(self, msg: dict[str, Any]) -> Event:
        window = None
        for info in (msg.get("modelUsage") or {}).values():
            if isinstance(info, dict) and info.get("contextWindow"):
                window = int(info["contextWindow"])
        percent = (
            round(100 * self.context_tokens / window, 1) if window and self.context_tokens else None
        )
        return self._event(
            "usage",
            {
                "cost_usd": msg.get("total_cost_usd"),
                "context_tokens": self.context_tokens or None,
                "context_window": window,
                "context_percent": percent,
                "web": (msg.get("usage") or {}).get("server_tool_use"),
            },
        )

    def outcome(self, code: int | None, stderr: str, stopped: bool) -> TurnResult:
        res = self.result
        base = TurnResult(native_session=self.session_id, files_touched=sorted(self.files))
        if stopped:
            return base.model_copy(update={"end_reason": "stopped"})
        if res is None:
            text = stderr.strip()[-1500:] or f"Claude Code exited (code {code}) without a result."
            return self._failed(text, base)
        cost = res.get("total_cost_usd")
        if res.get("is_error") or res.get("subtype") not in (None, "success"):
            errors = res.get("errors")
            text = (
                "; ".join(map(str, errors))
                if errors
                else str(res.get("result") or res.get("api_error_status") or res.get("subtype"))
            )
            return self._failed(text, base.model_copy(update={"cost_usd": cost}))
        return base.model_copy(update={"cost_usd": cost})

    def _failed(self, text: str, base: TurnResult) -> TurnResult:
        kind = usage.classify(text)
        if self.limit_rejected and kind == "other":
            kind = "limit"  # the stream already said a window was rejected
        resets = self.limit_resets or usage.reset_from_text(text)
        return base.model_copy(
            update={"end_reason": end_reason(kind), "error": short(text, 1500), "resets_at": resets}
        )


def _trim(args: dict[str, Any]) -> dict[str, Any]:
    """Tool input for the expanded row, without whole file bodies."""
    return {
        k: (short(v, 2000) if isinstance(v, str) else v)
        for k, v in args.items()
        if k not in ("content", "new_string", "old_string")
    }


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
    return ""


# ------------------------------------------------------------------ the provider


class ClaudeProvider:
    runtime = "claude"

    def __init__(self, id_: str) -> None:
        self.id = id_
        self.billing: Billing = "key" if id_ == "claude-api" else "plan"
        self.label = (
            "Claude Code (API key)" if self.billing == "key" else "Claude Code (subscription)"
        )
        self._models: tuple[float, list[dict[str, Any]]] | None = None

    # ---- environment

    def env(self) -> dict[str, str]:
        env = config.child_env()
        if self.billing == "plan":
            for key in STRIP_FOR_PLAN:
                env.pop(key, None)
        else:
            secret = keychain.get(self.id)
            if not secret:
                raise ProviderError("No API key stored for Claude Code. Add one in Models.")
            env["ANTHROPIC_API_KEY"] = secret
        if (MONITOR_MOD / ".claude-plugin" / "plugin.json").exists():
            env["CLAUDE_CODE_PLUGIN_DIRS"] = str(MONITOR_MOD)
        env["CLAUDE_PROJECT_DIR"] = str(config.ROOT)
        # A turn ends when the main thread's result arrives, and the process is then closed:
        # a background subagent would be killed mid-task and show as done at launch. With
        # this set, the Agent tool has no background option and the turn waits for its agents.
        env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
        # The research-live mod (.claude/skills/research-live) loads here too; the app does
        # its jobs itself (backend/autoedits.py, the HTML tab), so the mod stands aside.
        env["RESEARCH_APP"] = "1"
        return env

    def command(self, binary: str, native_session: str | None, options: TurnOptions) -> list[str]:
        cmd = [
            binary,
            "--output-format",
            "stream-json",
            "--verbose",
            "--input-format",
            "stream-json",
            "--permission-prompt-tool",
            "stdio",
            "--permission-mode",
            options.permission_mode or "default",
            "--setting-sources",
            "user,project,local",
        ]
        if native_session:
            cmd += ["--resume", native_session]
        else:
            cmd += ["--session-id", str(uuid.uuid4())]
        if options.model and options.model != "default":
            cmd += ["--model", options.model]
        if options.effort:
            cmd += ["--effort", options.effort]
        if options.tools is not None:
            cmd += [
                "--tools",
                ",".join(options.tools),
                "--disallowedTools",
                "WebSearch,WebFetch,Bash,Write",
            ]
        if options.ask_rules:
            cmd += ["--settings", json.dumps({"permissions": {"ask": options.ask_rules}})]
        if options.system_append:
            cmd += ["--append-system-prompt", options.system_append]
        return cmd

    # ---- status

    def status(self) -> ConnectionStatus:
        binary = claude_binary()
        st = ConnectionStatus(
            id=self.id,
            label=self.label,
            runtime="claude",
            billing=self.billing,
            installed=bool(binary),
            path=binary,
        )
        if not binary:
            st.message = "Claude Code not found. Install it from https://claude.com/claude-code."
            return st
        st.version = _run([binary, "--version"]).strip() or None
        if self.billing == "key":
            st.signed_in = keychain.has(self.id)
            st.message = (
                "API key stored in the Keychain. Bills per token."
                if st.signed_in
                else "No API key stored."
            )
        else:
            try:
                info = json.loads(
                    _run([binary, "auth", "status", "--json"], env=self._plan_env()) or "{}"
                )
            except ValueError:
                info = {}
            st.signed_in = bool(info.get("loggedIn")) and info.get("authMethod") == "claude.ai"
            plan = info.get("subscriptionType")
            st.message = (
                f"Signed in with Claude {str(plan).capitalize()}."
                if st.signed_in and plan
                else "Signed in with a Console account, which bills per token."
                if info.get("loggedIn")
                else "Not signed in."
            )
        st.models = self.models()
        return st

    def _plan_env(self) -> dict[str, str]:
        env = config.child_env()
        for key in STRIP_FOR_PLAN:
            env.pop(key, None)
        return env

    def models(self) -> list[dict[str, Any]]:
        """Models the CLI reports in its initialize handshake. The handshake starts the CLI
        but sends no prompt, so it costs nothing. Cached for ten minutes."""
        if self._models and time.time() - self._models[0] < 600:
            return self._models[1]
        binary = claude_binary()
        if not binary:
            return []
        found: list[dict[str, Any]] = []
        try:
            proc = subprocess.Popen(
                [
                    binary,
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--input-format",
                    "stream-json",
                    "--setting-sources",
                    "",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                cwd=config.ROOT,
                env=self._plan_env(),
            )
            assert proc.stdin and proc.stdout
            proc.stdin.write(
                json.dumps(
                    {
                        "type": "control_request",
                        "request_id": "init",
                        "request": {"subtype": "initialize", "hooks": None},
                    }
                )
                + "\n"
            )
            proc.stdin.flush()
            deadline = time.time() + 20
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("type") == "control_response":
                    models = ((msg.get("response") or {}).get("response") or {}).get("models") or []
                    found = [
                        {
                            "value": m.get("value"),
                            "label": m.get("displayName"),
                            "description": m.get("description"),
                            "efforts": m.get("supportedEffortLevels") or [],
                        }
                        for m in models
                        if isinstance(m, dict)
                    ]
                    break
            proc.kill()
        except OSError:
            return []
        self._models = (time.time(), found)
        return found

    def usage(self) -> UsageWindows | None:
        if self.billing == "key":
            return UsageWindows(note="Billed per token; no plan windows.")
        return usage.claude_usage()

    def start_login(self) -> None:
        binary = claude_binary()
        if not binary:
            raise ProviderError("Claude Code not found.")
        subprocess.Popen(
            [binary, "auth", "login", "--claudeai"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=self._plan_env(),
        )

    # ---- one turn

    async def run_turn(
        self,
        prompt: str,
        native_session: str | None,
        on_event: OnEvent,
        cancelled: Callable[[], bool],
        permission: PermissionHandler,
        options: TurnOptions,
    ) -> TurnResult:
        binary = claude_binary()
        if not binary:
            raise ProviderError("Claude Code not found.")
        proc = await asyncio.create_subprocess_exec(
            *self.command(binary, native_session, options),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=config.ROOT,
            env=self.env(),
            limit=STREAM_LIMIT,
        )
        assert proc.stdin and proc.stdout and proc.stderr
        parser = ClaudeParser(self.id)
        session = _ControlSession(proc, parser, on_event, permission, options)
        stderr_task = asyncio.create_task(proc.stderr.read())
        watcher = asyncio.create_task(session.watch(cancelled))
        try:
            await session.send(
                {
                    "type": "control_request",
                    "request_id": "init",
                    "request": {"subtype": "initialize", "hooks": None},
                }
            )
            await asyncio.wait_for(session.loop(prompt), TURN_TIMEOUT_S)
        finally:
            watcher.cancel()
            for task in session.pending.values():
                task.cancel()
            if proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except TimeoutError:
                    proc.kill()
        stderr = (await stderr_task).decode(errors="replace")
        return parser.outcome(proc.returncode, stderr, session.stopped)


class _ControlSession:
    """The stdin/stdout conversation with one CLI process."""

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        parser: ClaudeParser,
        on_event: OnEvent,
        permission: PermissionHandler,
        options: TurnOptions,
    ) -> None:
        self.proc = proc
        self.parser = parser
        self.on_event = on_event
        self.permission = permission
        self.options = options
        self.lock = asyncio.Lock()
        self.pending: dict[str, asyncio.Task[None]] = {}
        self.stopped = False

    async def send(self, obj: dict[str, Any]) -> None:
        stdin = self.proc.stdin
        if stdin is None or stdin.is_closing():
            return
        async with self.lock:
            try:
                stdin.write((json.dumps(obj) + "\n").encode())
                await stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass

    async def loop(self, prompt: str) -> None:
        assert self.proc.stdout
        sent = False
        answered = False  # the model has replied on the main thread since the prompt went in
        early = False  # a result came before any reply: wait a while for the real one
        while True:
            try:
                line = await (
                    asyncio.wait_for(self.proc.stdout.readline(), EARLY_RESULT_GRACE_S)
                    if early
                    else self.proc.stdout.readline()
                )
            except TimeoutError:
                break  # nothing followed the early result: the turn really did nothing
            if not line:
                break
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            kind = msg.get("type")
            if kind == "control_response" and not sent:
                sent = True
                await self.send(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": prompt},
                        "parent_tool_use_id": None,
                        "session_id": "default",
                    }
                )
            elif kind == "control_request":
                self._control(msg)
            elif kind == "control_cancel_request":
                task = self.pending.pop(str(msg.get("request_id")), None)
                if task:
                    task.cancel()
            else:
                if sent and kind == "assistant" and not msg.get("parent_tool_use_id"):
                    answered, early = True, False
                for event in self.parser.feed(msg):
                    await self.on_event(event)
                if kind == "result":
                    failed = msg.get("is_error") or msg.get("subtype") not in (None, "success")
                    if not answered and not failed:
                        early = True  # the drain of a resumed session's queue, not our turn
                        continue
                    if self.proc.stdin and not self.proc.stdin.is_closing():
                        self.proc.stdin.close()
                    break

    def _control(self, msg: dict[str, Any]) -> None:
        rid = str(msg.get("request_id"))
        req = msg.get("request") or {}
        if req.get("subtype") == "can_use_tool":
            self.pending[rid] = asyncio.create_task(self._permission(rid, req))
        else:
            asyncio.create_task(
                self.send(
                    {
                        "type": "control_response",
                        "response": {
                            "subtype": "error",
                            "request_id": rid,
                            "error": f"unsupported: {req.get('subtype')}",
                        },
                    }
                )
            )

    async def _permission(self, rid: str, req: dict[str, Any]) -> None:
        tool = str(req.get("tool_name") or "")
        args = as_dict(req.get("input"))
        rules = [
            {"tool": str(r.get("toolName")), "rule": str(r.get("ruleContent") or "")}
            for s in req.get("permission_suggestions") or []
            if isinstance(s, dict) and s.get("type") == "addRules"
            for r in s.get("rules") or []
            if isinstance(r, dict)
        ]
        if self.options.tools is not None:
            decision = self._restricted(tool, args)
        else:
            summary, _ = tool_summary(tool, args)
            question = tool == "AskUserQuestion" and isinstance(args.get("questions"), list)
            request = PermissionRequest(
                id=rid,
                tool=tool,
                summary=str(req.get("description") or summary),
                input={} if question else _trim(args),
                rules=[] if question else rules,
                agent=req.get("agent_id") or None,
                kind="question" if question else "permission",
                questions=[q for q in args.get("questions", []) if isinstance(q, dict)]
                if question
                else [],
            )
            try:
                decision = await self.permission(request)
            except asyncio.CancelledError:
                return
        if decision.allow:
            updated = (
                {**args, "answers": decision.answers} if decision.answers is not None else args
            )
            body: dict[str, Any] = {"behavior": "allow", "updatedInput": updated}
            if decision.always and rules:
                body["updatedPermissions"] = [
                    {
                        "type": "addRules",
                        "behavior": "allow",
                        "destination": "session",
                        "rules": [
                            {
                                "toolName": r["tool"],
                                **({"ruleContent": r["rule"]} if r["rule"] else {}),
                            }
                            for r in rules
                        ],
                    }
                ]
        else:
            body = {
                "behavior": "deny",
                "message": decision.message or "The author denied this action.",
            }
        await self.send(
            {
                "type": "control_response",
                "response": {"subtype": "success", "request_id": rid, "response": body},
            }
        )
        self.pending.pop(rid, None)

    def _restricted(self, tool: str, args: dict[str, Any]) -> PermissionDecision:
        """An "Improve with an agent" turn: reading is free, editing only the one copy."""
        if tool in ("Read", "Grep", "Glob"):
            return PermissionDecision(allow=True)
        if (
            tool in ("Edit", "MultiEdit")
            and self.options.edit_path
            and os.path.realpath(str(args.get("file_path", "")))
            == os.path.realpath(self.options.edit_path)
        ):
            return PermissionDecision(allow=True)
        return PermissionDecision(
            allow=False, message="Only the open file may be edited in this turn."
        )

    async def watch(self, cancelled: Callable[[], bool]) -> None:
        while self.proc.returncode is None:
            if cancelled():
                self.stopped = True
                await self.send(
                    {
                        "type": "control_request",
                        "request_id": "stop",
                        "request": {"subtype": "interrupt"},
                    }
                )
                await asyncio.sleep(2)
                if self.proc.returncode is None:
                    self.proc.kill()
                return
            await asyncio.sleep(0.3)


def _run(cmd: list[str], env: dict[str, str] | None = None) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=20, env=env or config.child_env()
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
