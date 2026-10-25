"""Model routing: the command a turn starts with picks the tier, each runtime maps the tier
to its own model, and the connection's own settings apply when routing is off."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from conftest import RUN, FakeProvider
from test_turns import _settle

from backend import config, router, sessions, workspace
from backend.turns import TurnManager

CLAUDE_MODELS = [
    {"value": "opus", "efforts": ["low", "medium", "high"]},
    {"value": "sonnet", "efforts": ["low", "medium", "high"]},
    {"value": "haiku", "efforts": []},
]


def _settings(**routing: Any) -> dict[str, Any]:
    s = config.load_settings()
    s["routing"].update(routing)
    return s


def test_command_picks_tier_per_runtime(data: Path) -> None:
    s = _settings()
    r = router.route("/research lithium prices", "claude-sub", s)
    assert (r.model, r.effort, r.tier, r.key) == ("opus", "medium", "frontier", "research")
    r = router.route("/research lithium prices", "codex-plan", s)
    assert (r.model, r.effort) == ("gpt-6-astra", "medium")
    r = router.route("/verify outputs/x E42", "codex-api", s)
    assert (r.model, r.effort, r.tier) == ("gpt-6.1-sol", "medium", "workhorse")
    r = router.route("/brain_storm revise the angle", "codex-api", s)
    assert (r.model, r.effort, r.tier, r.key) == ("gpt-6-astra", "medium", "frontier", "brain_storm")


def test_plain_text_and_unknown_commands_are_chat(data: Path) -> None:
    s = _settings()
    for text in ("what does the gate check?", "/compact", "  /nonsense here"):
        r = router.route(text, "claude-sub", s)
        assert (r.model, r.effort, r.key) == ("sonnet", "medium", "chat"), text


def test_fast_tier_drops_an_effort_the_model_does_not_take(data: Path) -> None:
    r = router.route("/app how do I rebuild?", "claude-sub", _settings(), CLAUDE_MODELS)
    assert (r.model, r.effort, r.tier) == ("haiku", "", "fast")
    r = router.route("/app how do I rebuild?", "codex-plan", _settings())
    assert r.model == "gpt-6-luna"


def test_unknown_model_falls_back_to_the_connection(data: Path) -> None:
    s = _settings()
    s["connections"]["codex-plan"] = {"model": "gpt-6.1-sol", "effort": "medium"}
    listed = [{"value": "gpt-6.1-sol", "efforts": ["low", "medium", "high"]}]
    r = router.route("/research x", "codex-plan", s, listed)
    assert (r.model, r.effort) == ("gpt-6.1-sol", "medium")
    assert "gpt-6-astra" in r.notice


def test_routing_off_uses_the_connection(data: Path) -> None:
    s = _settings(enabled=False)
    s["connections"]["claude-sub"] = {"model": "default", "effort": "xhigh"}
    r = router.route("/research x", "claude-sub", s)
    assert (r.model, r.effort, r.key) == ("default", "xhigh", "")


def test_stored_routing_overrides_entry_by_entry(data: Path) -> None:
    config.save_settings(
        {
            "routing": {
                "tiers": {"codex": {"fast": "gpt-5.6-luna"}},
                "commands": {"export": ["fast", "low"]},
            }
        }
    )
    s = config.load_settings()["routing"]
    assert s["tiers"]["codex"] == {
        "frontier": "gpt-6-astra",
        "workhorse": "gpt-6.1-sol",
        "fast": "gpt-5.6-luna",
    }
    assert s["commands"]["export"] == ["fast", "low"]
    assert s["commands"]["research"] == ["frontier", "medium"] and s["enabled"] is True


def test_continue_keeps_the_route_of_the_command_that_started_it(root: Path) -> None:
    claude = FakeProvider("claude-sub", ["claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "/research lithium prices in 2026", "claude-sub")
        await _settle(m, s.id)
        await m.send(s.id, "/continue only list prices, please", "claude-sub")
        await _settle(m, s.id)
        assert [(o.model, o.effort) for o in claude.options] == [("opus", "medium")] * 2
        seg = sessions.load(s.id).segments[0]
        assert (seg.model, seg.route_key) == ("opus", "research")
        routes = [
            e.data["text"] for e in sessions.transcript(s.id) if e.data.get("kind") == "route"
        ]
        assert routes == [
            "/research: frontier tier, opus at medium effort",
            "/research (continued): frontier tier, opus at medium effort",
        ]

    asyncio.run(go())


def test_command_starts_a_fresh_conversation_on_the_run(root: Path) -> None:
    claude = FakeProvider("claude-sub", ["claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "what does the gate check?", "claude-sub")
        await _settle(m, s.id)
        s = sessions.load(s.id)
        first = s.segments[0].native_session_id
        assert first
        s.runs = [RUN]
        sessions.save(s)

        await m.send(s.id, "/verify E42", "claude-sub")
        await _settle(m, s.id)
        prompt, native = claude.prompts[1]
        assert native is None  # fresh: the command works from the run folder
        assert prompt.startswith("/verify E42") and f"outputs/{RUN}" in prompt
        assert (claude.options[0].model, claude.options[1].model) == ("sonnet", "sonnet")
        assert sessions.load(s.id).segments[0].route_key == "verify"

        config.save_settings({"routing": {"fresh": False}})
        await m.send(s.id, "/verify E43", "claude-sub")
        await _settle(m, s.id)
        assert claude.prompts[2] == ("/verify E43", first)

    asyncio.run(go())


def test_hidden_commands_leave_the_menu_and_are_refused(root: Path) -> None:
    from backend import main
    from backend.providers.base import ProviderError

    assert config.load_settings()["hidden_commands"] == []
    hidden = {"figures"}
    config.save_settings({"hidden_commands": sorted(hidden)})
    offered = {c["name"] for c in main.commands()}
    assert offered.isdisjoint(hidden)
    assert offered == ({c["name"] for c in workspace.commands()} - hidden) | {"continue", "do"}

    claude = FakeProvider("claude-sub", ["claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})

    async def go() -> None:
        s = sessions.create()
        try:
            await m.send(s.id, "/figures F4 horizontal", "claude-sub")
        except ProviderError as exc:
            assert "not part of this app" in str(exc)
        else:
            raise AssertionError("a hidden command was sent")
        assert claude.prompts == []

    asyncio.run(go())


def test_turns_run_in_auto_mode_and_ask_before_deleting(root: Path) -> None:
    import json

    from backend.providers.base import TurnOptions
    from backend.providers.claude import ClaudeProvider

    claude = FakeProvider("claude-sub", ["claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "what does the gate check?", "claude-sub")
        await _settle(m, s.id)

    asyncio.run(go())
    opts = claude.options[0]
    assert opts.permission_mode == "auto" and "Bash(rm *)" in opts.ask_rules
    cmd = ClaudeProvider("claude-sub").command("claude", None, opts)
    assert cmd[cmd.index("--permission-mode") + 1] == "auto"
    asked = json.loads(cmd[cmd.index("--settings") + 1])["permissions"]["ask"]
    assert {"Bash(rm *)", "Bash(git clean *)", "Bash(find * -delete*)"} <= set(asked)
    # A restricted turn (Improve with an agent) keeps asking for everything.
    cmd = ClaudeProvider("claude-sub").command("claude", None, TurnOptions(tools=["Read"]))
    assert cmd[cmd.index("--permission-mode") + 1] == "default" and "--settings" not in cmd


def test_interface_preferences_are_kept_in_settings(data: Path) -> None:
    assert config.load_settings()["ui"]["theme"] == "system"
    ui = {
        "theme": "midnight",
        "agents_view": "lanes",
        "activity_open": False,
        "run_panel_open": False,
    }
    config.save_settings({"ui": ui})
    assert config.load_settings()["ui"] == ui


def test_a_message_without_a_command_is_a_read_only_question(root: Path) -> None:
    claude = FakeProvider("claude-sub", ["claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "/research lithium prices in 2026", "claude-sub")
        await _settle(m, s.id)
        await m.send(s.id, "what does the gate check?", "claude-sub")
        await _settle(m, s.id)
        work, question = claude.options
        assert not work.read_only and work.model == "opus"
        assert question.read_only and question.model == "sonnet" and "without a command" in question.system_append
        assert sessions.load(s.id).segments[0].route_key == "research"  # the work stays resumable
        await m.send(s.id, "/continue only list prices, please", "claude-sub")
        await _settle(m, s.id)
        resumed = claude.options[2]
        assert not resumed.read_only and resumed.model == "opus"
        assert claude.prompts[2][0].startswith("only list prices, please")
        routes = [e.data["text"] for e in sessions.transcript(s.id) if e.data.get("kind") == "route"]
        assert routes[1].startswith("Question (read-only)") and routes[2].startswith("/research (continued)")

    asyncio.run(go())


def test_read_only_turns_switch_off_the_tools_that_do_work() -> None:
    from backend.providers.base import TurnOptions
    from backend.providers.claude import ClaudeProvider
    from backend.providers.codex import CodexProvider

    cmd = ClaudeProvider("claude-sub").command("claude", None, TurnOptions(read_only=True))
    off = cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert {"Write", "Edit", "Bash", "Agent", "Task", "Skill"} <= set(off)
    assert "--disallowedTools" not in ClaudeProvider("claude-sub").command("claude", None, TurnOptions())
    assert 'sandbox_mode="read-only"' in CodexProvider("codex-plan").command("codex", None, TurnOptions(read_only=True))


def test_do_carries_out_a_one_off_task_with_every_tool(root: Path) -> None:
    claude = FakeProvider("claude-sub", ["claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "/do make the table headers lighter in meridian", "claude-sub")
        await _settle(m, s.id)
        options, (prompt, _) = claude.options[0], claude.prompts[0]
        assert not options.read_only and options.model == "sonnet"
        assert prompt.startswith("make the table headers lighter")
        routes = [e.data["text"] for e in sessions.transcript(s.id) if e.data.get("kind") == "route"]
        assert routes[0].startswith("/do:")

    asyncio.run(go())


def test_a_reply_to_an_agent_that_asked_carries_its_work_on(root: Path) -> None:
    claude = FakeProvider("claude-sub", ["claude_asks.jsonl", "claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "/research lithium prices in 2026", "claude-sub")
        await _settle(m, s.id)
        assert sessions.load(s.id).segments[0].awaiting
        await m.send(s.id, "yes, and keep the table", "claude-sub")
        await _settle(m, s.id)
        reply = claude.options[1]
        assert not reply.read_only and reply.model == "opus" and not reply.system_append
        assert claude.prompts[1][0].startswith("yes, and keep the table")
        assert not sessions.load(s.id).segments[0].awaiting  # that turn did not ask
        await m.send(s.id, "what does the gate check?", "claude-sub")
        await _settle(m, s.id)
        assert claude.options[2].read_only
        routes = [e.data["text"] for e in sessions.transcript(s.id) if e.data.get("kind") == "route"]
        assert routes[1].startswith("Reply to /research (continued), with every tool")

    asyncio.run(go())


def test_a_yes_to_a_read_only_turn_that_asked_carries_its_request_out(root: Path) -> None:
    claude = FakeProvider("claude-sub", ["claude_asks.jsonl", "claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "apply the five edits to the outlook", "claude-sub")
        await _settle(m, s.id)
        assert claude.options[0].read_only
        route = next(e for e in sessions.transcript(s.id) if e.data.get("kind") == "route")
        assert route.data["read_only"] and route.data["request"] == "apply the five edits to the outlook"
        assert sessions.load(s.id).segments[0].offered == "apply the five edits to the outlook"
        await m.send(s.id, "Yes please", "claude-sub")
        await _settle(m, s.id)
        assert not claude.options[1].read_only
        assert "Do what they asked earlier:\napply the five edits to the outlook" in claude.prompts[1][0]
        await m.send(s.id, "why five?", "claude-sub")  # not a yes: still a question
        await _settle(m, s.id)
        assert claude.options[2].read_only

    asyncio.run(go())


def test_a_read_only_turn_asks_rather_than_refuses() -> None:
    from backend.turns import AFFIRM, QUESTION

    assert "never answer that you cannot do it" in QUESTION and "Never tell" in QUESTION
    assert all(AFFIRM.match(t) for t in ["yes", "Yes please", "ok", "go ahead", "Do it.", "yes, apply them"])
    assert not any(AFFIRM.match(t) for t in ["yes but only the first two", "why five?", "no"])
