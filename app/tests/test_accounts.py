"""Claude subscription accounts: adding one gives it a config folder of its own linked to
the shared setup, a place in the order of use and a provider; removing one takes it out
everywhere but leaves the folder on disk. Runs against a temporary home, offline."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeProvider

from backend import accounts, config, usage
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
    a = accounts.add("Second")
    assert accounts.provider(a["id"]).env()["CLAUDE_CONFIG_DIR"] == a["config_dir"]
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
