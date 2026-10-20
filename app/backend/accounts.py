"""Claude subscription accounts: add, remove, sign in and sign out.

Each extra account is a Claude Code config folder of its own (`CLAUDE_CONFIG_DIR`), so
each keeps its own sign-in and plan windows. The folder links the shared parts back to
~/.claude (settings, skills, commands, plugins, projects, history), so every account sees
the same setup and can resume the same conversations. The default account, "claude-sub",
is ~/.claude itself and cannot be removed.

The Models page calls these through the API; the agent, or the author in a terminal, can
call the same functions:

    python3 -m backend.accounts list
    python3 -m backend.accounts add "Second plan" --email me@example.com [--dir ~/.claude-x]
    python3 -m backend.accounts login claude-second-plan
    python3 -m backend.accounts logout claude-second-plan
    python3 -m backend.accounts remove claude-second-plan

run from `app/`. A running app picks the change up on its next request.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from backend import config
from backend.providers.base import ProviderError
from backend.providers.claude import ClaudeProvider

DEFAULT_DIR = Path.home() / ".claude"
# What every account shares with ~/.claude. Sign-in (.claude.json, the Keychain entry)
# and session state stay per folder.
SHARED = (
    "settings.json",
    "skills",
    "commands",
    "agents",
    "plugins",
    "dev-mods",
    "scripts",
    "statusline.py",
    "projects",
    "history.jsonl",
    "file-history",
    "subagent-rows",
)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32]


def _link_shared(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in SHARED:
        link, target = folder / name, DEFAULT_DIR / name
        if target.exists() and not link.exists() and not link.is_symlink():
            link.symlink_to(target)


def provider_for(account: dict[str, str]) -> ClaudeProvider:
    return ClaudeProvider(
        account["id"], account["config_dir"], account.get("label", ""), account.get("email", "")
    )


def get(account_id: str) -> dict[str, str]:
    for a in config.claude_accounts():
        if a["id"] == account_id:
            return a
    raise ProviderError(f"No added Claude account {account_id}.")


def add(label: str, email: str = "", config_dir: str = "") -> dict[str, str]:
    """Register an account. An existing folder (one set up for VS Code, say) is reused
    with its sign-in; a new one is created with the shared parts linked in."""
    label = label.strip()
    if not label:
        raise ProviderError("Give the account a name.")
    name = slug(label)
    if not name:
        raise ProviderError("The name needs a letter or a digit.")
    account_id = config.ACCOUNT_PREFIX + name
    settings = config.load_settings()
    if account_id in config.connection_ids(settings):
        raise ProviderError(f"An account named {label} already exists.")
    folder = Path(config_dir).expanduser() if config_dir else Path.home() / f".claude-{name}"
    folder = folder.resolve()
    if folder == DEFAULT_DIR.resolve():
        raise ProviderError("~/.claude is the default account; choose another folder.")
    if any(Path(a["config_dir"]).resolve() == folder for a in config.claude_accounts(settings)):
        raise ProviderError(f"{folder} is already an account.")
    _link_shared(folder)
    account = {"id": account_id, "label": label, "email": email.strip(), "config_dir": str(folder)}
    order = list(settings.get("fallback_order") or [])
    # after the last Claude subscription in the order, so plans come before API keys
    plans = [i for i, c in enumerate(order) if c != "claude-api" and c.startswith("claude-")]
    order.insert(plans[-1] + 1 if plans else len(order), account_id)
    base = settings["connections"].get("claude-sub", {})
    config.save_settings(
        {
            "claude_accounts": [*config.claude_accounts(settings), account],
            "fallback_order": order,
            "connections": {account_id: {"model": base.get("model", "default"), "effort": base.get("effort", "high")}},
        }
    )
    return account


def remove(account_id: str, sign_out: bool = True) -> dict[str, str]:
    """Take an account out of the app. Its folder stays on disk, with the shared links, so
    nothing outside the app breaks; signing out frees its saved sign-in."""
    account = get(account_id)
    if sign_out:
        try:
            provider_for(account).logout()
        except ProviderError:
            pass  # already signed out, or Claude Code missing: removal goes ahead
    settings = config.load_settings()
    order = [c for c in settings.get("fallback_order") or [] if c != account_id]
    patch: dict[str, Any] = {
        "claude_accounts": [a for a in config.claude_accounts(settings) if a["id"] != account_id],
        "fallback_order": order,
    }
    if settings.get("default_connection") == account_id:
        patch["default_connection"] = order[0] if order else "claude-sub"
    config.save_settings(patch)
    return account


def provider(connection: str) -> ClaudeProvider:
    if connection == "claude-sub":
        return ClaudeProvider("claude-sub")
    return provider_for(get(connection))


def login(connection: str) -> None:
    provider(connection).start_login()


def logout(connection: str) -> None:
    provider(connection).logout()


def listing() -> list[dict[str, Any]]:
    out = []
    for conn in ["claude-sub", *(a["id"] for a in config.claude_accounts())]:
        st = provider(conn).status()
        out.append({"id": conn, "label": st.label, "signed_in": st.signed_in, "account": st.account,
                    "config_dir": provider(conn).config_dir or str(DEFAULT_DIR)})
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python3 -m backend.accounts", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("label")
    a.add_argument("--email", default="")
    a.add_argument("--dir", default="")
    for name in ("remove", "login", "logout"):
        sub.add_parser(name).add_argument("id")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            print(json.dumps(listing(), indent=2))
        elif args.cmd == "add":
            print(json.dumps(add(args.label, args.email, args.dir), indent=2))
        elif args.cmd == "remove":
            print(f"removed {remove(args.id)['id']}; its folder stays on disk")
        elif args.cmd == "login":
            login(args.id)
            print("The sign-in page opens in the browser. If it shows another Claude account, "
                  "sign out of claude.ai there first, then sign in again.")
        elif args.cmd == "logout":
            logout(args.id)
            print(f"signed out {args.id}")
    except ProviderError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
