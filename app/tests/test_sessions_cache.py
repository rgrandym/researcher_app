"""Transcript cache follows appends and outside writes without stale activity."""

from pathlib import Path

from backend import activity, sessions
from backend.providers.base import Event


def test_transcript_cache_tracks_appends_and_external_changes(data: Path) -> None:
    session = sessions.create()
    sessions.append(session.id, Event(type="user", data={"text": "first"}))
    assert [e.data["text"] for e in sessions.transcript(session.id)] == ["first"]
    first = sessions.transcript_revision(session.id)
    sessions.append(session.id, Event(type="user", data={"text": "second"}))
    assert sessions.transcript_revision(session.id) != first
    assert [e.data["text"] for e in sessions.transcript(session.id)] == ["first", "second"]
    path = data / "sessions" / session.id / "transcript.jsonl"
    with path.open("a") as fh:
        fh.write(Event(type="user", data={"text": "external"}).model_dump_json() + "\n")
    assert [e.data["text"] for e in sessions.transcript(session.id)] == ["first", "second", "external"]


def test_activity_reuses_event_aggregates_until_transcript_changes(data: Path, monkeypatch) -> None:
    session = sessions.create()
    sessions.append(session.id, Event(type="user", data={"text": "hello"}))
    original = activity.stage_timings
    calls = []

    def counted(events):
        calls.append(len(events))
        return original(events)

    monkeypatch.setattr(activity, "stage_timings", counted)
    activity.build(session.id, False, {})
    activity.build(session.id, False, {})
    assert calls == [1]
    sessions.append(session.id, Event(type="done"))
    activity.build(session.id, False, {})
    assert calls == [1, 2]
