"""The handoff packet: the right stage, the verbatim requests, the truncated evidence line,
and nothing the transcript does not contain."""

from __future__ import annotations

import re
import time
from pathlib import Path

from conftest import RUN

from backend import handoff, sessions
from backend.providers.base import Event


def _session(events: list[Event]) -> sessions.Session:
    s = sessions.create("Lithium costs")
    s.runs = [RUN]
    s.segments.append(
        sessions.Segment(provider="claude-sub", model="opus", ended=time.time(), end_reason="limit")
    )
    sessions.save(s)
    for e in events:
        sessions.append(s.id, e)
    return s


def _events(start: float) -> list[Event]:
    req1 = "/research how much does battery-grade lithium cost per tonne in 2026"
    req2 = "Also cover\nrecombinant routes."
    return [
        Event(type="user", data={"text": req1}, ts=start),
        Event(
            type="tool_call",
            data={"id": "a", "name": "Bash", "summary": "new_run.sh", "files": []},
            ts=start + 1,
        ),
        Event(
            type="tool_result",
            data={"id": "a", "is_error": False, "summary": f"outputs/{RUN}"},
            ts=start + 2,
        ),
        Event(type="user", data={"text": req2}, ts=start + 3),
        Event(
            type="tool_call",
            data={
                "id": "b",
                "name": "Write",
                "summary": "evidence",
                "files": [f"outputs/{RUN}/evidence.jsonl"],
            },
            ts=start + 4,
        ),
        Event(type="assistant_text", data={"text": "Writing evidence rows for SQ1."}, ts=start + 5),
    ]


def test_full_packet(root: Path) -> None:
    start = time.time() - 60
    events = _events(start)
    s = _session(events)
    packet, files = handoff.build(
        s, events, "Claude Code (subscription)", "opus", "limit", time.time()
    )

    assert "(Claude Code (subscription), opus)" in packet and "its plan or quota ran out" in packet
    # The author's requests, verbatim and in order, multi-line kept.
    assert "1. /research how much does battery-grade lithium cost per tonne in 2026" in packet
    assert "2. Also cover\n   recombinant routes." in packet
    # run_check output for the run, and the stage to resume.
    assert f"outputs/{RUN}" in packet and "evidence" in packet
    assert f"Resume at: the report stage of outputs/{RUN}" in packet
    # The truncated evidence line is flagged with its number.
    flagged = [f for f in files if f["flag"]]
    assert any(
        f["path"].endswith("evidence.jsonl") and f["flag"] == "line 3 is not valid JSON"
        for f in flagged
    )
    assert "FLAGGED: line 3 is not valid JSON" in packet
    # The previous agent's last message, quoted.
    assert "> Writing evidence rows for SQ1." in packet


def test_packet_invents_nothing(root: Path) -> None:
    start = time.time() - 60
    events = _events(start)
    s = _session(events)
    packet, _ = handoff.build(s, events, "Claude Code", "opus", "limit")
    section = packet.split("## What the previous agent did last", 1)[1].split(
        "The previous agent's last message", 1
    )[0]
    rows = [ln for ln in section.splitlines() if ln.startswith("- ")]
    assert [re.match(r"- (\w+)", r).group(1) for r in rows] == ["Bash", "Write"]  # type: ignore[union-attr]
    assert rows[0].endswith("· ok") and rows[1].endswith("· no result")
    # No file contents are pasted: the evidence rows themselves never appear.
    assert '"claim"' not in packet


def test_caps(root: Path) -> None:
    start = time.time() - 600
    events = [Event(type="user", data={"text": "go"}, ts=start)]
    events += [
        Event(
            type="tool_call",
            data={"id": str(i), "name": "Read", "summary": f"f{i}", "files": []},
            ts=start + i,
        )
        for i in range(1, 40)
    ]
    events.append(Event(type="assistant_text", data={"text": "x" * 5000}, ts=start + 50))
    s = _session(events)
    packet, _ = handoff.build(s, events, "Claude Code", "opus", "limit")
    assert packet.count("- Read ·") == handoff.MAX_TOOL_ROWS
    assert "x" * 2000 + " […]" in packet and "x" * 2001 not in packet


def test_mid_sentence(root: Path) -> None:
    doc = root / "outputs" / RUN / "draft.md"
    doc.write_text("# Draft\n\nLithium prices fell sharply between 2020 and")
    assert handoff.md_problem(doc) == "ends mid-sentence"
    doc.write_text("# Draft\n\nLithium prices fell.\n")
    assert handoff.md_problem(doc) is None
    doc.write_text("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
    assert handoff.md_problem(doc) is None


def test_return_packet(root: Path) -> None:
    start = time.time() - 60
    events = _events(start)
    s = _session(events)
    packet, _ = handoff.build_return(s, events, start + 3.5, "Codex (ChatGPT plan)")
    assert "Codex (ChatGPT plan)" in packet
    assert (
        "Also cover" not in packet and "/research how much" not in packet
    )  # both predate the return point
    assert f"outputs/{RUN}" in packet


def test_with_pending() -> None:
    assert handoff.with_pending("P", None) == "P"
    assert handoff.with_pending("P", "next").endswith("next")
