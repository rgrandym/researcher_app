"""Claude subscription accounts: adding one gives it a config folder of its own linked to
the shared setup, a place in the order of use and a provider; removing one takes it out
everywhere but leaves the folder on disk. Runs against a temporary home, offline."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from conftest import FakeProvider

from backend import accounts, config, main, usage
from backend.providers.base import ProviderError
from backend.providers.claude import ClaudeProvider
from backend.turns import TurnManager


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: Path) -> Path:
    h = tmp_path / "home"
    (h / ".claude" / "skills").mkdir(parents=True)
    (h / ".claude" / "settings.json").write_text("{}")
    monkeypatch.setattr(accounts, "DEFAULT_DIR", h / ".claude")
    monkeypatch.setattr(Path, "home", lambda: h)
    monkeypatch.setattr(ClaudeProvider, "logout", lambda self: None)
    return h


def test_add_links_shared_setup_and_orders_after_plans(home: Path) -> None:
    config.save_settings({"fallback_order": ["claude-sub", "codex-plan", "claude-api"]})
    a = accounts.add("Second plan", "me@example.com")
    assert a["id"] == "claude-second-plan"
    folder = Path(a["config_dir"])
    assert folder == (home / ".claude-second-plan").resolve()
    assert (folder / "skills").is_symlink() and (folder / "settings.json").is_symlink()
    s = config.load_settings()
    assert s["fallback_order"] == ["claude-sub", "claude-second-plan", "codex-plan", "claude-api"]
    assert "claude-second-plan" in s["connections"]
    assert config.connection_ids()[:2] == ["claude-sub", "claude-second-plan"]


def test_add_reuses_an_existing_folder(home: Path) -> None:
    existing = home / ".claude-work"
    existing.mkdir()
    (existing / ".claude.json").write_text("{}")
    a = accounts.add("work", config_dir=str(existing))
    assert Path(a["config_dir"]) == existing.resolve()
    assert (existing / ".claude.json").read_text() == "{}"


def test_add_refuses_duplicates_and_the_default_folder(home: Path) -> None:
    accounts.add("Second")
    with pytest.raises(ProviderError):
        accounts.add("second")
    with pytest.raises(ProviderError):
        accounts.add("Other", config_dir=str(home / ".claude"))
    with pytest.raises(ProviderError):
        accounts.add("api")  # would collide with the API-key connection


def test_remove_clears_order_and_default_but_keeps_folder(home: Path) -> None:
    a = accounts.add("Second")
    config.save_settings({"default_connection": a["id"]})
    accounts.remove(a["id"])
    s = config.load_settings()
    assert a["id"] not in s["fallback_order"]
    assert s["claude_accounts"] == []
    assert s["default_connection"] == s["fallback_order"][0]
    assert Path(a["config_dir"]).is_dir()


def test_provider_runs_from_the_account_folder(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/elsewhere")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "inherited-token")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "inherited-refresh")
    a = accounts.add("Second")
    assert accounts.provider(a["id"]).env()["CLAUDE_CONFIG_DIR"] == a["config_dir"]
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in accounts.provider(a["id"]).env()
    assert "CLAUDE_CODE_OAUTH_REFRESH_TOKEN" not in accounts.provider(a["id"]).env()
    # the default account ignores a folder inherited from the shell
    assert "CLAUDE_CONFIG_DIR" not in ClaudeProvider("claude-sub").env()


def test_manager_follows_added_and_removed_accounts(home: Path) -> None:
    m = TurnManager({"claude-sub": FakeProvider("claude-sub", [])})
    a = accounts.add("Second")
    assert m.provider(a["id"]).id == a["id"]
    accounts.remove(a["id"])
    m.sync_accounts()
    assert a["id"] not in m.providers


def test_each_account_keeps_its_own_plan_windows(home: Path) -> None:
    usage.record_claude_limit({"rateLimitType": "five_hour", "status": "rejected", "utilization": 1.0}, "claude-x")
    assert usage.claude_usage("claude-x").windows
    assert not usage.claude_usage("claude-sub").windows


def test_usage_from_previous_login_is_hidden(home: Path) -> None:
    usage.record_claude_limit(
        {"rateLimitType": "five_hour", "status": "rejected", "utilization": 1.0},
        "claude-second", "first@example.com",
    )
    assert not usage.claude_usage("claude-second", expected_email="second@example.com").windows
    usage.record_claude_limit(
        {"rateLimitType": "five_hour", "status": "allowed", "utilization": 0.1},
        "claude-second", "second@example.com",
    )
    window = usage.claude_usage("claude-second", expected_email="second@example.com").windows[0]
    assert window.used_percent == 10.0


def test_imports_claude_usage_snapshot_for_verified_account(home: Path) -> None:
    folder = home / ".claude-second"
    folder.mkdir()
    (folder / ".claude.json").write_text(json.dumps({
        "oauthAccount": {"emailAddress": "second@example.com", "accountUuid": "account-2"},
        "cachedUsageUtilization": {
            "accountUuid": "account-2", "fetchedAtMs": 1792860000000,
            "utilization": {
                "five_hour": {"utilization": 0, "resets_at": None},
                "seven_day": {"utilization": 31, "resets_at": "2026-10-26T13:00:00+00:00"},
            },
        },
    }))
    usage.import_claude_local_usage("claude-second", str(folder), "second@example.com")
    windows = usage.claude_usage("claude-second", expected_email="second@example.com").windows
    assert [(w.name, w.used_percent) for w in windows] == [("5h", 0), ("7d", 31)]
    usage.import_claude_local_usage("claude-other", str(folder), "other@example.com")
    assert not usage.claude_usage("claude-other").windows


def test_duplicate_claude_sign_in_is_refused(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = accounts.add("Second", "second@example.com")
    manager = TurnManager()
    monkeypatch.setattr(ClaudeProvider, "verified_email", lambda self, check_expected=True: "same@example.com")
    with pytest.raises(ProviderError, match="both signed in as same@example.com"):
        manager._verify_claude_account(manager.provider(a["id"]))


def test_distinct_claude_sign_ins_are_allowed(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = accounts.add("Second", "second@example.com")
    manager = TurnManager()
    monkeypatch.setattr(
        ClaudeProvider, "verified_email",
        lambda self, check_expected=True: "second@example.com" if self.id == a["id"] else "first@example.com",
    )
    manager._verify_claude_account(manager.provider(a["id"]))


def test_models_marks_duplicate_accounts_unavailable(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = accounts.add("Second", "same@example.com")
    monkeypatch.setattr(main, "_status", lambda conn, fresh=False: {
        "id": conn, "label": conn, "runtime": "claude", "billing": "plan",
        "signed_in": True, "account": "same@example.com", "message": "Signed in.",
    })
    monkeypatch.setattr(main.manager, "provider", lambda conn: FakeProvider(conn, []))
    result = asyncio.run(main.connections(fresh=True))
    duplicate = [item for item in result if item["id"] in ("claude-sub", a["id"])]
    assert len(duplicate) == 2
    assert duplicate[0]["signed_in"] and "Another connection uses this same account" in duplicate[0]["message"]
    assert not duplicate[1]["signed_in"] and "Duplicate Claude sign-in" in duplicate[1]["message"]


def test_configured_email_must_match_verified_login(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeProvider("claude-second", email="second@example.com")
    monkeypatch.setattr("backend.providers.claude.claude_binary", lambda: "claude")
    monkeypatch.setattr(provider, "_auth_info", lambda binary, fresh=False: {
        "loggedIn": True, "authMethod": "claude.ai", "email": "first@example.com",
    })
    with pytest.raises(ProviderError, match="configured for second@example.com"):
        provider.verified_email()


def test_sign_in_email_is_saved_and_passed_to_claude(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = accounts.add("Second", "old@example.com")
    requested: list[str | None] = []
    monkeypatch.setattr(ClaudeProvider, "start_login", lambda self, email=None: requested.append(email))
    main.login(a["id"], main.LoginBody(email="new@example.com"))
    assert requested == ["new@example.com"]
    assert accounts.get(a["id"])["email"] == "new@example.com"
    assert main.manager.provider(a["id"]).email == "new@example.com"


def test_default_sign_in_email_is_saved(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str | None] = []
    monkeypatch.setattr(ClaudeProvider, "start_login", lambda self, email=None: requested.append(email))
    main.login("claude-sub", main.LoginBody(email="first@example.com"))
    assert requested == ["first@example.com"]
    assert config.load_settings()["claude_default_email"] == "first@example.com"
    assert main.manager.provider("claude-sub").email == "first@example.com"
