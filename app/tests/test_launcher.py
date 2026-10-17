"""Reopening the Chrome window must not kill a turn's detached backend."""

from __future__ import annotations

import sys

import pytest

from mac import launcher


def test_reopen_reattaches_to_running_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    info: dict[str, object] = {"port": 54321, "pid": 12345, "token": "existing"}
    opened: list[str] = []
    watched: list[dict[str, object]] = []
    monkeypatch.setattr(sys, "argv", ["launcher.py"])
    monkeypatch.setattr(launcher, "running_backend", lambda: info)
    monkeypatch.setattr(launcher, "raise_window", lambda: "")
    monkeypatch.setattr(launcher, "start_backend", lambda: (_ for _ in ()).throw(AssertionError("started a second backend")))
    monkeypatch.setattr(launcher, "open_window", lambda url, browser: opened.append(url))
    monkeypatch.setattr(launcher, "watch", lambda current: watched.append(current))

    launcher.main()

    assert opened == ["http://127.0.0.1:54321/?token=existing"]
    assert watched == [info]


def test_window_loss_keeps_active_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    health = iter(({"clients": 1, "running": True}, {"clients": 0, "running": True}))
    monkeypatch.setattr(launcher, "IDLE_S", 0)
    monkeypatch.setattr(launcher, "_health", lambda port: next(health))
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(launcher.time, "time", lambda: 100.0)
    monkeypatch.setattr(launcher, "stop_backend", lambda info: (_ for _ in ()).throw(AssertionError("stopped an active turn")))

    launcher.watch({"port": 54321})
