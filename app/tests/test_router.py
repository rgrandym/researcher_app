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
    assert (r.model, r.effort, r.tier, r.key) == ("opus", "high", "frontier", "research")
    r = router.route("/research lithium prices", "codex-plan", s)
    assert (r.model, r.effort) == ("gpt-6-astra", "high")
    r = router.route("/verify outputs/x E42", "codex-api", s)
    assert (r.model, r.effort, r.tier) == ("gpt-6.1-sol", "medium", "workhorse")


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
    assert s["commands"]["research"] == ["frontier", "high"] and s["enabled"] is True


def test_reply_keeps_the_route_of_the_command_that_started_it(root: Path) -> None:
    claude = FakeProvider("claude-sub", ["claude_subagent.jsonl"])
    m = TurnManager({"claude-sub": claude})

    async def go() -> None:
        s = sessions.create()
        await m.send(s.id, "/research lithium prices in 2026", "claude-sub")
        await _settle(m, s.id)
        await m.send(s.id, "only list prices, please", "claude-sub")
        await _settle(m, s.id)
        assert [(o.model, o.effort) for o in claude.options] == [("opus", "high")] * 2
        seg = sessions.load(s.id).segments[0]
        assert (seg.model, seg.route_key) == ("opus", "research")
        routes = [
            e.data["text"] for e in sessions.transcript(s.id) if e.data.get("kind") == "route"
        ]
        assert routes == [
            "/research: frontier tier, opus at high effort",
            "/research (continued): frontier tier, opus at high effort",
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
    assert offered == {c["name"] for c in workspace.commands()} - hidden

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
