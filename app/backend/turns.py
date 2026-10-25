"""Running turns: one at a time per session, streamed to every open window.

The manager owns the live state the session store does not: the running task, the
permission requests waiting for the author, and the run locks. Every event a provider
emits is appended to the session's transcript and published to subscribers.

Limits: when a turn ends because a plan ran out, the segment closes and the session
waits for the author; a spent plan is never switched on its own. A turn its account could
not run at all (signed out, sign-in refused, network down) moves to the next signed-in
plan in the order of use, each account tried once per message.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend import activity, config, handoff, router, sessions, usage, workspace
from backend.providers.base import (
    Event,
    PermissionDecision,
    PermissionRequest,
    Provider,
    ProviderError,
    TurnOptions,
    TurnResult,
    short,
)
from backend.providers.claude import ClaudeProvider
from backend.providers.codex import CodexProvider
from backend.sessions import Segment, Session

Publish = Callable[[str, dict[str, Any]], Awaitable[None]]
RECENT_EXTERNAL_S = 300


PIPELINE = ("gather", "draft", "review", "finish")
STAGE_ARG = re.compile(r"\bstage=(\w+)")
RUN_ARG = re.compile(r"\brun=(?:outputs/)?([\w.-]+)")
STAGED_NOTE = (
    "\n\n(Staged run: the app runs each stage of this pipeline in a fresh conversation. "
    "Do the gather stage only, as the skill's section on staged runs describes, and end "
    "your turn when it is complete.)"
)


def stage_missing(run: str, stage: str) -> list[str]:
    """What a stage has not yet left on disk; empty when it is complete."""
    rows = {r["stage"]: bool(r["ok"]) for r in workspace.stages(run, max_age=0)}
    need = {
        "gather": ["brief", "voice", "coverage", "evidence"],
        "draft": [],
        "review": ["verify", "critique"],
        "finish": ["report", "repair"],
    }[stage]
    missing = [k for k in need if not rows.get(k)]
    if stage == "draft":
        path = workspace.run_dir(run)
        if not ((path / "draft.md").is_file() or rows.get("report")):
            missing.append("draft")
    return missing


def project_note(run: str) -> str:
    """What a new agent conversation opened from a project's Chat tab is told."""
    master = ""
    with contextlib.suppress(ValueError, FileNotFoundError):
        master = workspace.run_meta(workspace.run_dir(run)).get("primary") or ""
    doc = f" Its master document is outputs/{run}/{master}." if master else ""
    return (
        f"\n\n(This conversation is inside the project outputs/{run}.{doc} Questions and "
        "commands are about this project unless the author says otherwise; a command "
        "that takes a run acts on it. Read its files as the question needs, by grep and "
        "range rather than whole.)"
    )


def make_providers() -> dict[str, Any]:
    providers: dict[str, Any] = {
        "claude-sub": ClaudeProvider("claude-sub", email=str(config.load_settings().get("claude_default_email") or "")),
        "claude-api": ClaudeProvider("claude-api"),
        "codex-plan": CodexProvider("codex-plan"),
        "codex-api": CodexProvider("codex-api"),
    }
    for a in config.claude_accounts():
        providers[a["id"]] = _account_provider(a)
    return providers


def _account_provider(a: dict[str, str]) -> ClaudeProvider:
    return ClaudeProvider(a["id"], a["config_dir"], a.get("label", ""), a.get("email", ""))


@dataclass
class Running:
    task: asyncio.Task[None] | None = None
    stop: bool = False
    permissions: dict[str, asyncio.Future[PermissionDecision]] = field(default_factory=dict)
    started: float = field(default_factory=time.time)
    gate_repaired: bool = False
    # Set the moment the turn announces it has stopped, which is a little before its task
    # returns: a client refreshing on that announcement must already be told it is over.
    ended: bool = False
    request: str = ""  # the author's words for this turn, carried to a failover account


class Hub:
    """WebSocket subscribers per session."""

    def __init__(self) -> None:
        self.queues: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self.everyone: set[asyncio.Queue[dict[str, Any]]] = set()

    async def publish(self, session_id: str, message: dict[str, Any]) -> None:
        for q in list(self.queues.get(session_id, ())) + list(self.everyone):
            q.put_nowait({**message, "session": session_id})


# Resuming a model's own earlier conversation is cheap only while its prompt cache is warm.
# After that, the first call re-writes the whole history into the cache (66k tokens on
# 2026-10-09, resuming after two hours) and every later call carries it. Past this age the
# app starts a fresh conversation with the handover packet instead: a few thousand tokens.
RESUME_WARM_S = 3600


class TurnManager:
    def __init__(self, providers: dict[str, Any] | None = None, hub: Hub | None = None) -> None:
        self.providers: dict[str, Any] = providers if providers is not None else make_providers()
        self.hub = hub or Hub()
        self.running: dict[str, Running] = {}
        self.locks: dict[str, str] = {}  # run name -> session id
        self.last_turn_end: dict[str, float] = {}
        self.failover_tried: dict[str, set[str]] = {}  # session -> accounts that failed

    # ------------------------------------------------------------------ queries

    def is_running(self, session_id: str) -> bool:
        r = self.running.get(session_id)
        return bool(r and r.task and not r.task.done() and not r.ended)

    def any_running(self) -> bool:
        return any(self.is_running(s) for s in self.running)

    def provider(self, connection: str) -> Provider:
        if connection not in self.providers:
            self.sync_accounts()
        if connection not in self.providers:
            raise ProviderError(f"Unknown connection: {connection}")
        return self.providers[connection]  # type: ignore[no-any-return]

    def sync_accounts(self) -> None:
        """Match the Claude account providers to settings after an account is added or
        removed. A provider whose account was removed stays while a turn still uses it."""
        settings = config.load_settings()
        wanted = {a["id"]: a for a in config.claude_accounts(settings)}
        default = self.providers.get("claude-sub")
        expected = str(settings.get("claude_default_email") or "")
        if isinstance(default, ClaudeProvider) and default.email != expected:
            self.providers["claude-sub"] = ClaudeProvider("claude-sub", email=expected)
        for conn, prov in list(self.providers.items()):
            if getattr(prov, "config_dir", "") and conn not in wanted:
                if not any(self.runs_on(sid, conn) for sid in self.running):
                    del self.providers[conn]
        for conn, a in wanted.items():
            prov = self.providers.get(conn)
            same = prov is not None and (prov.config_dir, prov.email) == (
                a["config_dir"],
                a.get("email", ""),
            )
            if not same:
                self.providers[conn] = _account_provider(a)

    def _verify_claude_account(self, provider: ClaudeProvider) -> None:
        """Refuse a turn if two plan connections resolve to the same Claude login."""
        email = provider.verified_email()
        for other in self.providers.values():
            if other is provider or not isinstance(other, ClaudeProvider) or other.billing != "plan":
                continue
            try:
                other_email = other.verified_email(check_expected=False)
            except ProviderError:
                continue  # a signed-out or unverifiable alternative cannot run this turn
            if email == other_email:
                order = list(self.providers)
                if order.index(other.id) < order.index(provider.id):
                    raise ProviderError(
                        f"{provider.label} and {other.label} are both signed in as {email}. "
                        "Sign this connection out and sign in with a different Claude account."
                    )

    def runs_on(self, session_id: str, connection: str) -> bool:
        if not self.is_running(session_id):
            return False
        seg = sessions.load(session_id).current()
        return seg is not None and seg.provider == connection

    # ------------------------------------------------------------------ sending

    async def send(self, session_id: str, text: str, connection: str | None = None) -> None:
        """The author's message. Continues the open segment, or opens the first one; a
        message for a different connection goes through a handoff."""
        if self.is_running(session_id):
            raise ProviderError("A turn is already running in this session.")
        self.failover_tried.pop(session_id, None)
        settings = config.load_settings()
        name = router.command_of(text)
        if name and name in (settings.get("hidden_commands") or []):
            raise ProviderError(
                f"/{name} is not part of this app; it is still available in VS Code."
            )
        session = sessions.load(session_id)
        current = session.current()
        target = connection or (
            current.provider if current else settings.get("default_connection", "claude-sub")
        )
        self.provider(target)
        if current and current.provider == target and not session.stale:
            await self._start(session, current, text, user_text=text)
        elif not session.segments:
            seg = self._segment(target, settings)
            session.segments.append(seg)
            if session.title == "New session":
                session.title = sessions.title_from(text)
            sessions.save(session)
            await self._start(session, seg, text, user_text=text)
        else:
            reason = (
                "config" if session.stale and current and current.provider == target else "switch"
            )
            await self.switch(session_id, target, pending=text, reason=reason)

    async def switch(
        self,
        session_id: str,
        target: str,
        pending: str | None = None,
        reason: str = "switch",
        echo: bool = True,
    ) -> None:
        """Close the open segment, build the packet, and open a segment on `target`."""
        if self.is_running(session_id):
            raise ProviderError("Stop the running turn before switching.")
        self.provider(target)
        session = sessions.load(session_id)
        events = sessions.transcript(session_id)
        settings = config.load_settings()
        current = session.current()
        if current:
            current.ended = time.time()
            current.end_reason = current.end_reason or reason
        last = session.segments[-1] if session.segments else None
        prior = session.last_for(target)
        resume = None
        files: list[dict[str, Any]] = []
        packet = ""
        if last is None:
            packet, files = "", []
        elif (
            last.provider == target
            and last.native_session_id
            and reason != "config"
            and time.time() - (last.ended or time.time()) < RESUME_WARM_S
        ):
            # The same provider after its window reset: its own session remembers everything.
            packet, files = "", []
            resume = last.native_session_id
        elif (
            prior
            and prior is not last
            and prior.native_session_id
            and reason != "config"
            and time.time() - (prior.ended or time.time()) < RESUME_WARM_S
        ):
            other = last.provider if last else "another agent"
            packet, files = handoff.build_return(
                session,
                events,
                prior.ended or prior.started,
                self.providers[other].label if other in self.providers else other,
            )
            resume = prior.native_session_id
        else:
            from_label = (
                self.providers[last.provider].label
                if last.provider in self.providers
                else last.provider
            )
            packet, files = handoff.build(
                session, events, from_label, last.model, last.end_reason or reason, last.ended
            )
        seg = self._segment(target, settings)
        seg.native_session_id = resume
        # A research conversation continued on another provider stays on the research tier.
        seg.route_key = last.route_key if last else ""
        session.segments.append(seg)
        session.stale = False
        name = sessions.write_handoff(session, packet) if packet else None
        sessions.save(session)
        if packet:
            ev = Event(
                type="handoff",
                provider=target,
                data={
                    "name": name,
                    "from": last.provider if last else None,
                    "to": target,
                    "reason": reason,
                    "resumed": bool(resume),
                    "flagged": [f["path"] for f in files if f.get("flag")],
                    "packet": packet,
                },
            )
            await self._emit(session_id, ev)
        prompt = handoff.with_pending(packet, pending) if packet else (pending or "")
        if not prompt:
            return
        # A failover carries words already shown in the transcript: route on them, unechoed.
        await self._start(
            session, seg, prompt, user_text=pending if echo else None, route_text=pending
        )

    def _segment(self, connection: str, settings: dict[str, Any]) -> Segment:
        conf = settings.get("connections", {}).get(connection, {})
        return Segment(
            provider=connection, model=conf.get("model", ""), effort=conf.get("effort", "")
        )

    async def stop(self, session_id: str) -> None:
        r = self.running.get(session_id)
        if r:
            r.stop = True
            for fut in r.permissions.values():
                if not fut.done():
                    fut.set_result(
                        PermissionDecision(allow=False, message="The author stopped the turn.")
                    )

    async def stop_all(self) -> int:
        """Request cancellation of every active turn, including turns in other sessions."""
        active = [sid for sid in self.running if self.is_running(sid)]
        for sid in active:
            await self.stop(sid)
        return len(active)

    async def answer(
        self, session_id: str, request_id: str, decision: str, answers: dict[str, str] | None = None
    ) -> None:
        r = self.running.get(session_id)
        fut = r.permissions.get(request_id) if r else None
        if fut is None or fut.done():
            return
        if decision == "answer":
            fut.set_result(PermissionDecision(allow=True, answers=answers or {}))
            return
        fut.set_result(
            PermissionDecision(
                allow=decision in ("once", "always"),
                always=decision == "always",
                message="The author chose not to answer." if decision == "skip" else "",
            )
        )

    # ------------------------------------------------------------------ the turn

    async def _start(
        self,
        session: Session,
        seg: Segment,
        prompt: str,
        user_text: str | None,
        route_text: str | None = None,
    ) -> None:
        conflict = self._take_locks(session)
        if conflict:
            await self._emit(
                session.id, Event(type="error", data={"kind": "other", "text": conflict})
            )
            return
        running = Running()
        self.running[session.id] = running
        if user_text is not None:
            await self._emit(
                session.id, Event(type="user", data={"text": user_text}, provider=seg.provider)
            )
        await self._warn_external(session)
        # The route follows the author's own words; a handoff packet wrapped around them
        # does not change which command they typed.
        route_text = route_text or (user_text if user_text is not None else prompt)
        running.task = asyncio.create_task(self._run(session.id, prompt, running, route_text))
        await self.hub.publish(session.id, {"type": "state", "running": True})

    async def _run(
        self, session_id: str, prompt: str, running: Running, route_text: str = ""
    ) -> None:
        session = sessions.load(session_id)
        seg = session.current()
        assert seg is not None
        provider = self.provider(seg.provider)
        running.request = route_text or prompt
        # Model and effort as set now, so a change between turns (Models, the routing
        # table, the effort meter) applies to the next turn on either provider.
        picked = await self._route(provider, seg.provider, route_text, seg.route_key)
        seg.model, seg.effort = picked.model, picked.effort
        # A typed command starts a fresh native session, unless the author's words arrive
        # inside a handoff packet: that packet is the context the new agent needs.
        native = seg.native_session_id
        fresh = (
            picked.command
            and route_text == prompt
            and bool((config.load_settings().get("routing") or {}).get("fresh"))
        )
        if picked.command:
            seg.route_key = picked.key
        if fresh and native:
            native = None
            if session.runs and not session.project:
                runs = ", ".join(f"outputs/{r}" for r in session.runs)
                prompt += (
                    f"\n\n(This app session has worked on {runs}. "
                    "Use it if the command names no run.)"
                )
        if session.project and native is None and route_text == prompt:
            prompt += project_note(session.project)
        if picked.command and picked.key == "research-pipeline":
            prompt = self._stage_pipeline(session, route_text, prompt)
        sessions.save(session)
        if picked.key:
            label = "Chat" if picked.key == "chat" else f"/{picked.key}"
            if picked.key != "chat" and not picked.command:
                label += " (continued)"
            at = f" at {picked.effort} effort" if picked.effort else ""
            text = picked.notice or f"{label}: {picked.tier} tier, {picked.model}{at}"
            if fresh and seg.native_session_id:
                text += ", new conversation"
            await self._emit(
                session_id,
                Event(
                    type="notice",
                    provider=seg.provider,
                    data={"kind": "route", "text": text, "tier": picked.tier},
                ),
            )
        options = TurnOptions(
            model=seg.model,
            effort=seg.effort,
            permission_mode=str(config.load_settings().get("permission_mode") or ""),
            ask_rules=[str(r) for r in config.load_settings().get("ask_rules") or []],
        )
        if seg.provider.startswith("codex") and seg.native_session_id and activity.cap_reached(seg):
            options.web_off = True
        started = time.time()
        result: TurnResult
        try:
            if isinstance(provider, ClaudeProvider) and provider.billing == "plan":
                await asyncio.to_thread(self._verify_claude_account, provider)
            result = await provider.run_turn(
                prompt,
                native,
                lambda ev: self._on_event(session_id, ev),
                lambda: running.stop,
                lambda req: self._permission(session_id, req),
                options,
            )
        except ProviderError as exc:
            result = TurnResult(
                native_session=seg.native_session_id,
                end_reason="auth" if "key" in str(exc).lower() else "error",
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001  a crashed turn must still end cleanly
            result = TurnResult(
                native_session=seg.native_session_id,
                end_reason="error",
                error=f"{type(exc).__name__}: {exc}",
            )
        critique_ready: dict[str, str] | None = None
        if router.command_of(route_text) == "critique" and result.end_reason == "done":
            launched = any(
                event.type == "tool_call" and event.data.get("subagent")
                for event in sessions.transcript(session_id) if event.ts >= started
            )
            current = sessions.load(session_id)
            named_runs = sorted(workspace.runs_in(route_text))
            run_name = named_runs[0] if len(named_runs) == 1 else current.project or (current.runs[-1] if current.runs else "")
            run_path = config.OUTPUTS / run_name if run_name else None
            fresh = bool(run_path and any(
                file.stat().st_mtime >= started for file in run_path.glob("critique*.md")
            ))
            questions_fresh = False
            question_file = run_path / "critique-questions.json" if run_path else None
            if question_file and question_file.is_file() and question_file.stat().st_mtime >= started:
                try:
                    questions_fresh = isinstance(json.loads(question_file.read_text()).get("questions"), list)
                except (OSError, ValueError, AttributeError):
                    pass
            if not launched or (run_path and (not fresh or not questions_fresh)):
                reason = ("did not launch an independent report-critic" if not launched
                          else "did not write a fresh critique file" if not fresh
                          else "did not write the author questions file")
                result = result.model_copy(update={
                    "end_reason": "error",
                    "error": f"Critique {reason}. The review stage is incomplete; rerun /critique.",
                })
                if run_path and run_path.is_dir():
                    (run_path / ".critique-isolation-failed").write_text(reason + "\n")
            elif run_path:
                (run_path / ".critique-isolation-failed").unlink(missing_ok=True)
                newest = max(run_path.glob("critique*.md"), key=lambda f: f.stat().st_mtime)
                critique_ready = {"run": run_name, "path": newest.name}
        await self._finish(session_id, result, started, running)
        if critique_ready:
            # The transcript offers the author's three choices: apply every finding, apply
            # with their answers and direction, or pass (POST /api/runs/{run}/apply-critique).
            await self._emit(
                session_id,
                Event(
                    type="notice",
                    data={
                        "kind": "critique_ready",
                        **critique_ready,
                        "text": f"The critique of outputs/{critique_ready['run']} is ready "
                        f"in {critique_ready['path']}.",
                    },
                ),
            )

    async def _failover(
        self, session_id: str, seg: Segment | None, result: TurnResult, started: float
    ) -> str | None:
        """The next signed-in plan for a turn its account could not run (signed out, sign-in
        refused, network) and which did nothing yet. Per-token connections are skipped, and
        a spent plan is not failed over: the author keeps that switch in their own hands."""
        if (
            seg is None
            or result.end_reason not in ("auth", "network")
            or not self._did_nothing(session_id, started)
        ):
            return None
        tried = self.failover_tried.setdefault(session_id, set())
        tried.add(seg.provider)
        order = [c for c in config.load_settings().get("fallback_order", []) if c in self.providers]
        if seg.provider in order:
            i = order.index(seg.provider)
            order = order[i + 1 :] + order[:i]
        for conn in order:
            prov = self.providers[conn]
            if conn in tried or getattr(prov, "billing", "") != "plan":
                continue
            try:
                st = await asyncio.to_thread(prov.status)
            except Exception:  # noqa: BLE001  an account that cannot report is not a target
                continue
            if st.installed and st.signed_in:
                return conn
        return None

    @staticmethod
    def _did_nothing(session_id: str, started: float) -> bool:
        events = [e for e in sessions.transcript(session_id) if e.ts >= started]
        return not any(e.type in ("assistant_text", "tool_call") for e in events)

    async def retry(self, session_id: str, connection: str | None = None) -> None:
        """Retry the last prompt from the current state. Re-sending a slash command
        verbatim could duplicate work already recorded in its run folder."""
        if self.is_running(session_id):
            raise ProviderError("A turn is already running in this session.")
        events = sessions.transcript(session_id)
        prefix = "The author clicked Retry for the previous prompt."
        old_prefix = "Carry on with the task from before; its last attempt ended before it finished."
        last = next(
            (
                e for e in reversed(events)
                if e.type == "user"
                and not str(e.data.get("text") or "").startswith((prefix, old_prefix))
            ),
            None,
        )
        if last is None:
            raise ProviderError("There is no prompt to retry in this session.")
        request = str(last.data.get("text") or "")
        text = (
            prefix + " "
            "Re-read the current command instructions. Reassess the request against "
            "the current state, finish what remains, and "
            "avoid repeating completed steps or creating duplicate rounds."
            + f"\n\nThe request was:\n{request}"
        )
        await self.send(session_id, text, connection)

    async def _finish(
        self, session_id: str, result: TurnResult, started: float, running: Running
    ) -> None:
        session = sessions.load(session_id)
        seg = session.current()
        if seg is not None:
            seg.native_session_id = result.native_session or seg.native_session_id
            if result.cost_usd:
                seg.cost_usd += float(result.cost_usd)
        if result.end_reason == "limit" and seg is not None:
            seg.ended = time.time()
            seg.end_reason = "limit"
        sessions.save(session)
        if result.end_reason == "auth" and seg is not None:
            forget = getattr(self.providers.get(seg.provider), "forget_auth", None)
            if forget:
                forget()
        target = await self._failover(session_id, seg, result, started)
        if target and seg is not None:
            why = "is not signed in" if result.end_reason == "auth" else "could not reach the service"
            await self._emit(
                session_id,
                Event(
                    type="notice",
                    provider=seg.provider,
                    data={
                        "kind": "failover",
                        "from": seg.provider,
                        "to": target,
                        "text": f"{self.providers[seg.provider].label} {why}"
                        f" ({short(result.error or '', 200)}). Continuing on "
                        f"{self.providers[target].label}.",
                    },
                ),
            )
            await self._emit(
                session_id,
                Event(type="done", data={"end_reason": result.end_reason}, provider=seg.provider),
            )
            self.last_turn_end[session_id] = time.time()
            self._release_locks(session_id)
            running.ended = True
            try:
                await self.switch(
                    session_id, target, pending=running.request, reason=result.end_reason, echo=False
                )
                return
            except Exception as exc:  # noqa: BLE001  fall back to showing the failure
                result = result.model_copy(
                    update={"error": f"{result.error} Moving to {target} failed: {exc}"}
                )
                running.ended = False
        if result.end_reason not in ("done", "stopped"):
            kind = (
                result.end_reason
                if result.end_reason in ("limit", "auth", "context", "network")
                else "other"
            )
            data: dict[str, Any] = {
                "kind": kind,
                "text": result.error,
                "resets_at": result.resets_at,
            }
            if kind == "limit" and seg is not None:
                data["provider"] = seg.provider
                data["next"] = self.next_connection(seg.provider)
                data["next_bills_per_token"] = (data["next"] or "").endswith("-api")
            await self._emit(
                session_id, Event(type="error", data=data, provider=seg.provider if seg else None)
            )
        if result.end_reason == "done" and self._did_nothing(session_id, started):
            # A turn that ended without a word or a tool call did not run the request: say
            # so, and offer Retry (POST /api/sessions/{id}/retry) instead of a silent "done".
            await self._emit(
                session_id,
                Event(
                    type="notice",
                    data={
                        "kind": "empty",
                        "text": "The model ended this turn without doing anything, so the "
                        "request did not run. Retry to carry on from where the task stands.",
                    },
                    provider=seg.provider if seg else None,
                ),
            )
        await self._emit(
            session_id,
            Event(
                type="done",
                data={"end_reason": result.end_reason, "cost_usd": result.cost_usd},
                provider=seg.provider if seg else None,
            ),
        )
        self.last_turn_end[session_id] = time.time()
        self._release_locks(session_id)
        # Whatever the follow-up steps do, the turn must end with "not running": a failure
        # here without that message would leave the app showing the task in progress for ever.
        try:
            repair = None
            if result.end_reason == "done" and seg is not None:
                repair = await self._codex_gate(session, seg, started, running)
                await self._handover_offer(session_id, seg)
            if repair:
                running.gate_repaired = True
                running.task = asyncio.create_task(self._run(session_id, repair, running))
                return
            following = await self._next_stage(session_id, result, running)
            if following:
                running.task = asyncio.create_task(self._run(session_id, following, running, following))
                return
        except Exception as exc:  # noqa: BLE001
            await self._emit(
                session_id,
                Event(type="error", data={"kind": "other", "text": f"After the turn ended: {type(exc).__name__}: {exc}"}),
            )
        running.ended = True
        await self.hub.publish(session_id, {"type": "state", "running": False})

    # ------------------------------------------------------------------ staged pipeline

    def _stage_pipeline(self, session: Session, text: str, prompt: str) -> str:
        """Record the pipeline the author started, or the stage they named, so the app
        can run the next stage when this one is done."""
        if not config.load_settings().get("staged_pipeline"):
            session.pipeline = None
            return prompt
        named = STAGE_ARG.search(text)
        if named and named.group(1) in PIPELINE:
            run = RUN_ARG.search(text)
            session.pipeline = {
                "run": run.group(1) if run else session.project,
                "stage": named.group(1),
            }
            return prompt
        session.pipeline = {"run": session.project, "stage": "gather"}
        return prompt + STAGED_NOTE

    async def _next_stage(
        self, session_id: str, result: TurnResult, running: Running
    ) -> str | None:
        """The prompt for the next stage, when the current one has left its files; None
        to wait for the author (a question asked, a stage unfinished) or when done."""
        session = sessions.load(session_id)
        p = session.pipeline
        if not p or result.end_reason != "done" or running.stop:
            return None
        run = p.get("run") or (session.runs[-1] if session.runs else "")
        stage = p.get("stage", "gather")

        async def note(text: str) -> None:
            await self._emit(
                session_id, Event(type="notice", data={"kind": "pipeline", "text": text})
            )

        if not run or not (config.OUTPUTS / run).is_dir():
            # Answered without a run (a Tier 0 or 1 question), or the run is not there yet.
            if stage == "gather" and not run:
                session.pipeline = None
                sessions.save(session)
            return None
        try:
            missing = stage_missing(run, stage)
        except (FileNotFoundError, ValueError):
            return None
        if missing:
            await note(
                f"Waiting on you: the {stage} stage is not complete yet "
                f"(missing: {', '.join(missing)}). Reply to continue it."
            )
            return None
        i = PIPELINE.index(stage)
        if i == len(PIPELINE) - 1:
            session.pipeline = None
            sessions.save(session)
            await note("The pipeline has finished; each stage ran in its own conversation.")
            return None
        following = PIPELINE[i + 1]
        session.pipeline = {"run": run, "stage": following}
        sessions.save(session)
        await note(f"The {stage} stage is complete. Starting {following} in a fresh conversation.")
        return f"/research-pipeline stage={following} run=outputs/{run}"

    def next_connection(self, current: str) -> str | None:
        order = [c for c in config.load_settings().get("fallback_order", []) if c in self.providers]
        if current in order:
            order = order[order.index(current) + 1 :] + order[: order.index(current)]
        return next((c for c in order if c != current), None)

    async def _on_event(self, session_id: str, ev: Event) -> None:
        session = sessions.load(session_id)
        seg = session.current()
        changed = False
        if ev.type == "session" and seg is not None and ev.data.get("session_id"):
            seg.native_session_id = str(ev.data["session_id"])
            changed = True
        if ev.type in ("tool_call", "tool_result"):
            text = " ".join(
                [
                    *(ev.data.get("files") or []),
                    str(ev.data.get("summary", "")),
                    json.dumps(ev.data.get("input") or {}),
                ]
            )
            for run in sorted(workspace.runs_in(text)):
                if run not in session.runs and (config.OUTPUTS / run).is_dir():
                    session.runs.append(run)
                    changed = True
                    owner = self.locks.get(run)
                    if owner and owner != session_id:
                        await self._emit(
                            session_id,
                            Event(
                                type="notice",
                                data={
                                    "kind": "lock",
                                    "text": f"outputs/{run} is also open in another app session.",
                                },
                            ),
                        )
                    else:
                        self._lock(run, session_id)
        if ev.type == "tool_call" and seg is not None:
            name = str(ev.data.get("name"))
            if name == "WebSearch":
                seg.searches += 1
                changed = True
            elif name == "WebFetch":
                seg.fetches += 1
                changed = True
        if ev.type == "usage" and seg is not None and ev.data.get("tokens_in") is not None:
            seg.tokens_in += int(ev.data.get("tokens_in") or 0)
            seg.tokens_out += int(ev.data.get("tokens_out") or 0)
            changed = True
        if changed:
            sessions.save(session)
        await self._emit(session_id, ev)

    async def _route(
        self, provider: Provider, connection: str, text: str, sticky: str = ""
    ) -> router.Route:
        """The routed model and effort, checked against the models the connection offers.
        The model list is cached by each provider; a fake without one skips the check."""
        settings = config.load_settings()
        lister = getattr(provider, "models", None)
        models: list[dict[str, Any]] | None = None
        if callable(lister) and (settings.get("routing") or {}).get("enabled"):
            try:
                models = await asyncio.to_thread(lister)
            except Exception:  # noqa: BLE001  an unreadable list only skips the check
                models = None
        return router.route(text, connection, settings, models, sticky)

    async def _emit(self, session_id: str, ev: Event) -> None:
        sessions.append(session_id, ev)
        await self.hub.publish(session_id, {"type": "event", "event": ev.model_dump()})

    async def _permission(self, session_id: str, req: PermissionRequest) -> PermissionDecision:
        rules = config.load_settings().get("allow_rules", []) if req.kind == "permission" else []
        for r in req.rules:
            if any(a.get("tool") == r["tool"] and a.get("rule", "") == r["rule"] for a in rules):
                return PermissionDecision(allow=True, always=True)
        running = self.running.get(session_id)
        if running is None or running.stop:
            return PermissionDecision(allow=False, message="The turn was stopped.")
        fut: asyncio.Future[PermissionDecision] = asyncio.get_running_loop().create_future()
        running.permissions[req.id] = fut
        await self._emit(
            session_id, Event(type="permission_request", data=req.model_dump(), agent=req.agent)
        )
        try:
            decision = await fut
        except asyncio.CancelledError:
            await self._emit(
                session_id,
                Event(type="permission_answer", data={"id": req.id, "decision": "withdrawn"}),
            )
            raise
        finally:
            running.permissions.pop(req.id, None)
        if decision.always and req.rules:
            settings = config.load_settings()
            known = settings.get("allow_rules", [])
            for r in req.rules:
                if r not in known:
                    known.append(r)
            config.save_settings({"allow_rules": known})
        await self._emit(
            session_id,
            Event(
                type="permission_answer",
                data={
                    "id": req.id,
                    "decision": "answered"
                    if decision.answers is not None
                    else "always"
                    if decision.always
                    else "once"
                    if decision.allow
                    else "deny",
                    **({"answers": decision.answers} if decision.answers is not None else {}),
                },
            ),
        )
        return decision

    # ------------------------------------------------------------------ after a turn

    async def _codex_gate(
        self, session: Session, seg: Segment, started: float, running: Running
    ) -> str | None:
        """Codex: gate the masters the turn wrote. One automatic repair, then stop."""
        if not seg.provider.startswith("codex"):
            return None
        failures = []
        for doc in workspace.masters_changed_since(set(session.runs), started):
            code, text = await asyncio.to_thread(workspace.gate, doc)
            if code != 0:
                failures.append(f"{doc.relative_to(config.ROOT)}:\n{text[-3000:]}")
        if not failures:
            return None
        body = "\n\n".join(failures)
        if running.gate_repaired:
            await self._emit(
                session.id,
                Event(
                    type="notice",
                    provider=seg.provider,
                    data={
                        "kind": "gate",
                        "text": f"The gate still fails after one repair. Over to you:\n\n{body}",
                    },
                ),
            )
            return None
        await self._emit(
            session.id,
            Event(
                type="notice",
                provider=seg.provider,
                data={"kind": "gate", "text": "The gate failed; sending the findings back once."},
            ),
        )
        return f"gate.py reports hard failures in the documents you just wrote. Fix them, then stop.\n\n{body}"

    async def _handover_offer(self, session_id: str, seg: Segment) -> None:
        threshold = float(config.load_settings().get("handover_threshold", 90))
        provider = self.providers.get(seg.provider)
        if provider is None:
            return
        try:
            win = usage.over_threshold(await asyncio.to_thread(provider.usage), threshold)
        except Exception:  # noqa: BLE001  usage is advisory
            return
        if win:
            nxt = self.next_connection(seg.provider)
            await self._emit(
                session_id,
                Event(
                    type="notice",
                    provider=seg.provider,
                    data={
                        "kind": "handover",
                        "window": win.name,
                        "used": win.used_percent,
                        "resets_at": win.resets_at,
                        "next": nxt,
                        "text": f"{provider.label}'s {win.name} window is {win.used_percent:.0f}% used.",
                    },
                ),
            )

    # ------------------------------------------------------------------ locks

    def _lock_path(self, run: str) -> Path:
        return config.data_dir("locks") / f"{run}.lock"

    def _lock(self, run: str, session_id: str) -> None:
        self.locks[run] = session_id
        self._lock_path(run).write_text(
            json.dumps({"session": session_id, "pid": os.getpid(), "at": time.time()})
        )

    def _take_locks(self, session: Session) -> str | None:
        for run in session.runs:
            owner = self.locks.get(run)
            if owner and owner != session.id and self.is_running(owner):
                return f"outputs/{run} is in use by another session's running turn. Wait for it to finish."
        for run in session.runs:
            self._lock(run, session.id)
        return None

    def _release_locks(self, session_id: str) -> None:
        for run, owner in list(self.locks.items()):
            if owner == session_id:
                del self.locks[run]
                self._lock_path(run).unlink(missing_ok=True)

    async def _warn_external(self, session: Session) -> None:
        """A run changed recently by something the app did not start (VS Code, say)."""
        since = self.last_turn_end.get(session.id, 0)
        for run in session.runs:
            with contextlib.suppress(ValueError, FileNotFoundError):
                newest = workspace.newest_mtime(workspace.run_dir(run))
                if newest > since + 2 and time.time() - newest < RECENT_EXTERNAL_S and since:
                    await self._emit(
                        session.id,
                        Event(
                            type="notice",
                            data={
                                "kind": "external",
                                "text": f"outputs/{run} changed in the last few minutes outside this app. If an agent is working on it in VS Code, let it finish first.",
                            },
                        ),
                    )

    # ------------------------------------------------------------------ Improve with an agent

    async def improve(self, rel: str, request: str) -> dict[str, Any]:
        """A turn that may read `.claude/` and edit a copy of one file, with no web and
        no shell. The change comes back as a diff for the author to accept or reject."""
        original = workspace.editable(rel)
        work = config.data_dir("improve", uuid.uuid4().hex[:8])
        copy = work / original.name
        shutil.copyfile(original, copy) if original.exists() else copy.write_text("")
        prompt = (config.PROMPTS / "improve.md").read_text()
        for key, value in {"path": str(copy), "original": rel, "request": request}.items():
            prompt = prompt.replace("{{" + key + "}}", value)
        claude = [
            c
            for c in config.load_settings().get("fallback_order", [])
            if c in self.providers and getattr(self.providers[c], "runtime", "") == "claude"
        ]
        connection = next(
            (c for c in [*claude, "claude-sub", "claude-api"] if self.providers[c].status().signed_in), None
        )
        if connection is None:
            raise ProviderError("Improve with an agent needs Claude Code; sign in under Models.")
        conf = config.load_settings()["connections"].get(connection, {})
        replies: list[str] = []

        async def on_event(ev: Event) -> None:
            if ev.type == "assistant_text" and ev.agent is None:
                replies.append(str(ev.data.get("text", "")))

        async def deny(_: PermissionRequest) -> PermissionDecision:
            return PermissionDecision(allow=False)

        options = TurnOptions(
            model=conf.get("model", ""),
            effort=conf.get("effort", ""),
            tools=["Read", "Grep", "Glob", "Edit"],
            edit_path=str(copy),
        )
        result = await self.providers[connection].run_turn(
            prompt, None, on_event, lambda: False, deny, options
        )
        proposed = copy.read_text()
        shutil.rmtree(work, ignore_errors=True)
        return {
            "diff": workspace.diff(rel, proposed),
            "content": proposed,
            "reply": replies[-1] if replies else "",
            "end_reason": result.end_reason,
            "error": result.error,
        }
