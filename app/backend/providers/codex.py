"""Codex as an agent runtime, with the adapter that closes the gaps to Claude Code.

Codex reads `AGENTS.md` (which sends it to `CLAUDE.md` and the voice profile), runs the
workspace's `.codex/hooks.json` (gate and research monitor) because it runs in the
workspace root, and has native subagents. What the adapter adds:

- the preamble in `app/prompts/codex-preamble.md` on the first turn of each thread;
- workspace commands expanded by the app (`/name args` -> read the skill and follow it);
- trust for this one project and the sandbox, passed as `-c` overrides. The shared
  `~/.codex/config.toml` is never written, and an existing sign-in is never touched;
- web search switched off by override once the session's search cap is reached.

The binary is the one the VS Code ChatGPT extension ships; its folder moves with every
extension update, so it is resolved on each call, never cached.
"""

from __future__ import annotations

import asyncio
import glob
import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend import config, containment, keychain, usage, workspace
from backend.providers.base import (
    Billing,
    ConnectionStatus,
    Event,
    OnEvent,
    PermissionHandler,
    ProviderError,
    TurnOptions,
    TurnResult,
    UsageWindows,
    as_dict,
    end_reason,
    kill_process_tree,
    short,
)

STREAM_LIMIT = 64 * 1024 * 1024
TURN_TIMEOUT_S = 6 * 3600
PREAMBLE = config.PROMPTS / "codex-preamble.md"
# Skills whose steps run in isolated subagents (rule 4: the drafting thread never reviews).
ISOLATED_SKILLS = {"research", "research-pipeline", "verify"}


def codex_binary() -> str | None:
    """PATH first, then the newest copy in the VS Code or Cursor extension folders, then
    the Codex app. Resolved every time: the extension folder changes on update."""
    if found := config.binary("codex"):
        return found
    home = Path.home()
    patterns = [
        str(home / ".vscode/extensions/openai.chatgpt-*/bin/*/codex"),
        str(home / ".cursor/extensions/openai.chatgpt-*/bin/*/codex"),
        "/Applications/Codex.app/Contents/Resources/codex",
    ]
    candidates = {p for pat in patterns for p in glob.glob(pat)}
    return max(candidates, key=lambda p: Path(p).stat().st_mtime) if candidates else None


def _toml(value: str) -> str:
    return json.dumps(value)  # JSON string escapes are valid TOML basic strings


# ------------------------------------------------------------------ parsing


ITEM_TOOL = {
    "command_execution": "Shell",
    "file_change": "Edit",
    "web_search": "WebSearch",
    "todo_list": "Plan",
}


class CodexParser:
    """Normalises `codex exec --json` events into `Event`s."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.thread_id: str | None = None
        self.completed: dict[str, Any] | None = None
        self.failure: str = ""
        self.started: set[str] = set()
        self.files: set[str] = set()
        self.subagents = 0
        self.web = 0

    def _event(self, type_: Any, data: dict[str, Any], agent: str | None = None) -> Event:
        return Event(type=type_, data=data, agent=agent, provider=self.provider)

    def feed(self, msg: dict[str, Any]) -> list[Event]:
        kind = msg.get("type")
        if kind == "thread.started":
            self.thread_id = msg.get("thread_id")
            return [self._event("session", {"session_id": self.thread_id})]
        if kind == "turn.completed":
            self.completed = msg
            u = msg.get("usage") or {}
            return [
                self._event(
                    "usage",
                    {
                        "tokens_in": int(u.get("input_tokens") or 0),
                        "tokens_out": int(u.get("output_tokens") or 0),
                        "cached_in": u.get("cached_input_tokens"),
                    },
                )
            ]
        if kind in ("turn.failed", "error"):
            err = msg.get("error") if kind == "turn.failed" else msg
            text = err.get("message") if isinstance(err, dict) else str(err or "")
            self.failure = str(text or self.failure)
            return []
        if kind in ("item.started", "item.completed"):
            item = as_dict(msg.get("item"))
            return self._item(kind, item)
        return []

    def _item(self, kind: str, item: dict[str, Any]) -> list[Event]:
        itype = str(item.get("type") or "")
        iid = str(item.get("id") or "")
        if itype == "agent_message":
            text = str(item.get("text") or "")
            return (
                [self._event("assistant_text", {"text": text})]
                if kind == "item.completed" and text
                else []
            )
        if itype in ("reasoning", ""):
            return []
        if itype == "error":
            return [
                self._event("notice", {"kind": "codex", "text": short(item.get("message"), 400)})
            ]
        events: list[Event] = []
        if iid not in self.started:
            self.started.add(iid)
            events.append(self._call(itype, iid, item))
        if kind == "item.completed":
            events.append(self._result(itype, iid, item))
        return events

    def _call(self, itype: str, iid: str, item: dict[str, Any]) -> Event:
        name = ITEM_TOOL.get(itype) or (
            f"{item.get('server')}.{item.get('tool')}" if itype == "mcp_tool_call" else itype
        )
        files = [
            str(c.get("path"))
            for c in item.get("changes") or []
            if isinstance(c, dict) and c.get("path")
        ]
        self.files.update(files)
        summary = (
            item.get("command")
            or item.get("query")
            or (", ".join(files) if files else "")
            or short(json.dumps(item.get("arguments") or {}), 160)
        )
        data: dict[str, Any] = {"id": iid, "name": name, "summary": short(summary), "files": files}
        if itype == "web_search":
            self.web += 1
        if "agent" in itype or "collab" in itype or "spawn" in itype:
            # Codex's agent tools are one item type for every action: spawning an agent,
            # messaging it, waiting on it, listing them. Only a spawn starts an agent; the
            # rest are calls the main thread makes, named after the action.
            action = str(item.get("tool") or item.get("name") or item.get("action") or "")
            data["input"] = _trim_item(item)
            if "spawn" in action or (not action and "spawn" in itype):
                self.subagents += 1
                data["subagent"] = {
                    "type": str(item.get("agent_type") or item.get("role") or item.get("agent_role") or "subagent"),
                    "description": short(
                        str(item.get("prompt") or item.get("description") or item.get("message") or item.get("agent_path") or ""),
                        120,
                    ),
                }
            else:
                data["name"] = f"Agents: {action.replace('_', ' ')}" if action else "Agents"
                data["summary"] = short(str(item.get("prompt") or item.get("message") or ""), 160)
        return self._event("tool_call", data)

    def _result(self, itype: str, iid: str, item: dict[str, Any]) -> Event:
        status = str(item.get("status") or "")
        code = item.get("exit_code")
        failed = (
            status == "failed" or (isinstance(code, int) and code != 0) or bool(item.get("error"))
        )
        text = item.get("aggregated_output") or item.get("error") or item.get("result") or status
        data: dict[str, Any] = {
            "id": iid,
            "is_error": failed,
            "summary": short(text if isinstance(text, str) else json.dumps(text), 300),
        }
        if "agent" in itype or "collab" in itype or "spawn" in itype:
            data["subagent_done"] = True
        return self._event("tool_result", data)

    def outcome(self, code: int | None, stderr: str, stopped: bool) -> TurnResult:
        base = TurnResult(native_session=self.thread_id, files_touched=sorted(self.files))
        if stopped:
            return base.model_copy(update={"end_reason": "stopped"})
        if self.completed is not None and not self.failure:
            return base
        text = (
            self.failure
            or stderr.strip()[-1500:]
            or f"codex exec exited (code {code}) without finishing the turn."
        )
        return base.model_copy(
            update={
                "end_reason": end_reason(usage.classify(text)),
                "error": short(text, 1500),
                "resets_at": usage.reset_from_text(text),
            }
        )


# ------------------------------------------------------------------ the provider


class CodexProvider:
    runtime = "codex"

    def __init__(self, id_: str) -> None:
        self.id = id_
        self.billing: Billing = "key" if id_ == "codex-api" else "plan"
        self.label = "Codex (API key)" if self.billing == "key" else "Codex (ChatGPT plan)"
        self._models: tuple[float, list[dict[str, Any]]] | None = None

    def env(self) -> dict[str, str]:
        env = config.child_env()
        if self.billing == "key":
            key = keychain.get(self.id)
            if not key:
                raise ProviderError("No API key stored for Codex. Add one in Models.")
            # `codex exec` takes an API key from CODEX_API_KEY without a login, so the
            # shared ChatGPT sign-in in ~/.codex is left untouched.
            env["CODEX_API_KEY"] = key
            env["OPENAI_API_KEY"] = key
        else:
            env.pop("CODEX_API_KEY", None)
            env.pop("OPENAI_API_KEY", None)
        return containment.env(env)

    def command(self, binary: str, thread: str | None, options: TurnOptions) -> list[str]:
        root = str(config.ROOT)
        cmd = [binary, "exec", *(["resume"] if thread else []), "--json"]
        settings = {
            f'projects."{root}".trust_level': _toml("trusted"),
            "sandbox_mode": _toml("read-only" if options.read_only else "workspace-write"),
            "sandbox_workspace_write.network_access": "true",
            # Writable: the workspace only. Scratch files go to $TMPDIR, inside app/data.
            "sandbox_workspace_write.exclude_slash_tmp": "true",
            "sandbox_workspace_write.exclude_tmpdir_env_var": "true",
            "approval_policy": _toml("never"),
            "web_search": _toml("disabled" if options.web_off else "live"),
        }
        if options.effort:
            settings["model_reasoning_effort"] = _toml(options.effort)
        for key, value in settings.items():
            cmd += ["-c", f"{key}={value}"]
        if options.model:
            cmd += ["-m", options.model]
        return [*cmd, *([thread] if thread else []), "-"]

    def prompt(self, text: str, first: bool) -> tuple[str, str | None]:
        expanded, command = workspace.expand_command(text)
        if not first:
            return expanded, command
        try:
            preamble = PREAMBLE.read_text()
        except OSError:
            preamble = "Read CLAUDE.md and .claude/voice/profile.md before acting; they bind you."
        return f"{preamble.strip()}\n\n---\n\n{expanded}", command

    # ---- status

    def status(self) -> ConnectionStatus:
        binary = codex_binary()
        st = ConnectionStatus(
            id=self.id,
            label=self.label,
            runtime="codex",
            billing=self.billing,
            installed=bool(binary),
            path=binary,
        )
        if not binary:
            st.message = "Codex not found. Install the ChatGPT extension in VS Code."
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
            text = _run([binary, "login", "status"], stderr=True)
            lines = [
                ln.strip()
                for ln in text.splitlines()
                if ln.strip() and not ln.lower().startswith("warning")
            ]
            st.signed_in = any(ln.lower().startswith("logged in") for ln in lines)
            st.message = lines[0] if lines else "Status unknown."
        st.models = self.models(binary)
        return st

    def models(self, binary: str | None = None) -> list[dict[str, Any]]:
        """Models `codex debug models` lists, without a model call. Cached for ten minutes,
        because the router checks its choice against this list on every turn."""
        if self._models and time.time() - self._models[0] < 600:
            return self._models[1]
        binary = binary or codex_binary()
        if not binary:
            return []
        try:
            data = json.loads(_run([binary, "debug", "models"]) or "{}")
        except ValueError:
            return []
        found = [
            {
                "value": m.get("slug") or m.get("id"),
                "label": m.get("display_name") or m.get("slug"),
                "description": m.get("description", ""),
                "efforts": [
                    e.get("effort")
                    for e in m.get("supported_reasoning_levels") or []
                    if isinstance(e, dict)
                ],
            }
            for m in data.get("models", [])
            if isinstance(m, dict) and m.get("visibility", "list") == "list"
        ]
        self._models = (time.time(), found)
        return found

    def usage(self) -> UsageWindows | None:
        if self.billing == "key":
            return UsageWindows(note="Billed per token; no plan windows.")
        return usage.codex_usage(codex_binary())

    def start_login(self) -> None:
        binary = codex_binary()
        if not binary:
            raise ProviderError("Codex not found.")
        if self.status().signed_in:
            raise ProviderError("Codex is already signed in; the app does not sign in again.")
        subprocess.Popen(
            [binary, "login"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
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
        binary = codex_binary()
        if not binary:
            raise ProviderError("Codex not found.")
        text, command = self.prompt(prompt, first=native_session is None)
        turn_started = time.time()
        proc = await asyncio.create_subprocess_exec(
            *self.command(binary, native_session, options),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=config.ROOT,
            env=self.env(),
            limit=STREAM_LIMIT,
            start_new_session=True,
        )
        assert proc.stdin and proc.stdout and proc.stderr
        proc.stdin.write(text.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        parser = CodexParser(self.id)
        stopped = False

        async def watch() -> None:
            nonlocal stopped
            while proc.returncode is None:
                if cancelled():
                    stopped = True
                    kill_process_tree(proc)
                    return
                await asyncio.sleep(0.1)

        async def read() -> None:
            assert proc.stdout
            while line := await proc.stdout.readline():
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    for event in parser.feed(msg):
                        await on_event(event)

        watcher = asyncio.create_task(watch())
        stderr_task = asyncio.create_task(proc.stderr.read())
        try:
            await asyncio.wait_for(read(), TURN_TIMEOUT_S)
            await proc.wait()
        finally:
            watcher.cancel()
            if proc.returncode is None:
                kill_process_tree(proc)
        if parser.subagents == 0 and not stopped:
            # The stream leaves out the spawn; the subagents' own rollouts record it.
            for child in usage.codex_child_threads(parser.thread_id, turn_started - 5):
                parser.subagents += 1
                name = child["path"].rsplit("/", 1)[-1] or child["role"]
                call = {"id": f"spawn-{child['id']}", "name": "Agents: spawn", "files": [],
                        "summary": name,
                        "subagent": {"type": child["role"], "description": name}}
                await on_event(parser._event("tool_call", call))
                await on_event(parser._event(
                    "tool_result", {"id": call["id"], "is_error": False, "summary": "completed",
                                    "subagent_done": True}))
        if command in ISOLATED_SKILLS and parser.subagents == 0 and not stopped:
            await on_event(
                Event(
                    type="notice",
                    provider=self.id,
                    data={
                        "kind": "isolation",
                        "text": f"Reduced isolation: /{command} ran without a separate subagent, so the review steps shared the drafting thread.",
                    },
                )
            )
        return parser.outcome(
            proc.returncode, (await stderr_task).decode(errors="replace"), stopped
        )


def _run(cmd: list[str], stderr: bool = False) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, env=config.child_env()
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout + (out.stderr if stderr else "")


def _trim_item(item: dict[str, Any]) -> dict[str, Any]:
    """An agent item's fields, long values cut, so its exact shape can be read later."""
    return {k: (short(v, 200) if isinstance(v, str) else v) for k, v in item.items() if k != "id"}
