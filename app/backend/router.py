"""Model routing: the model and effort a turn runs on, chosen from the command it starts with.

The slash command already states what the author wants, so the route is a table lookup
and costs no model call. Commands map to a tier (frontier, workhorse, fast) and an
effort; each runtime maps the tiers to its own models. A prompt without a command takes
the `chat` route. Both maps live in settings, so a renamed model is a settings edit.

With routing off, or for a connection the maps do not cover, the connection's own model
and effort apply, as before.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

COMMAND = re.compile(r"^/([A-Za-z0-9:_-]+)")
TIERS = ("frontier", "workhorse", "fast")


class Route(BaseModel):
    model: str
    effort: str
    tier: str = ""
    key: str = ""  # the command name, or "chat"
    notice: str = ""  # why the route fell back, for the transcript
    command: bool = False  # the author typed the command this turn (not carried over)


def command_of(text: str) -> str | None:
    m = COMMAND.match(text.strip())
    return m.group(1) if m else None


def runtime_of(connection: str) -> str:
    return "codex" if connection.startswith("codex") else "claude"


def route(
    text: str,
    connection: str,
    settings: dict[str, Any],
    models: list[dict[str, Any]] | None = None,
    sticky: str = "",
) -> Route:
    """The model and effort for a turn whose author text is `text`.

    `sticky` is the command that started the conversation this turn continues: a reply
    without a command (an answer to the pipeline's clarifying question) keeps that
    command's tier rather than dropping to chat.

    `models` is the runtime's own model list, when known: a routed model missing from it
    falls back to the connection's model, and an effort the model does not accept is
    dropped (Haiku takes none)."""
    conf = settings.get("connections", {}).get(connection, {})
    own = Route(model=str(conf.get("model", "")), effort=str(conf.get("effort", "")))
    routing = settings.get("routing") or {}
    if not routing.get("enabled"):
        return own
    tiers = (routing.get("tiers") or {}).get(runtime_of(connection)) or {}
    name = command_of(text)
    commands = routing.get("commands") or {}
    typed = bool(name and name in commands)
    key = name if typed and name else sticky if sticky in commands else "chat"
    tier, effort = _pair(commands.get(key) or routing.get("chat"))
    model = str(tiers.get(tier, ""))
    if not model:
        return own
    if models:
        listed = next((m for m in models if m.get("value") == model), None)
        if listed is None:
            return own.model_copy(
                update={
                    "tier": tier,
                    "key": key,
                    "notice": f"Routed model {model} is not offered by this connection; "
                    f"used the connection's own model instead.",
                    "command": typed,
                }
            )
        efforts = listed.get("efforts")
        if isinstance(efforts, list) and effort not in efforts:
            effort = ""
    return Route(model=model, effort=effort, tier=tier, key=key, command=typed)


def _pair(value: Any) -> tuple[str, str]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return str(value[0]), str(value[1])
    return "workhorse", "medium"
