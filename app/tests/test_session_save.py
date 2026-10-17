"""Concurrent session saves must each own their temporary file."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

from backend import sessions


def test_concurrent_saves_do_not_steal_each_others_temp_file(data: Any, monkeypatch: Any) -> None:
    session = sessions.create("Concurrent save")
    barrier = Barrier(2)
    replace = Path.replace

    def together(source: Path, target: Path) -> Path:
        if source.name.startswith("session.") and source.suffix == ".tmp":
            barrier.wait(timeout=5)
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(sessions.save, session.model_copy(deep=True)) for _ in range(2)]
        for job in jobs:
            job.result(timeout=10)
    assert sessions.load(session.id).id == session.id
