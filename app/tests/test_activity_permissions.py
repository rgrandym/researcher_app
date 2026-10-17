"""Permission history follows live backend requests, not transcript shape."""

from backend import activity
from backend.providers.base import Event


def test_only_open_request_is_waiting() -> None:
    events = [
        Event(type="permission_request", data={"id": "old", "tool": "Bash", "summary": "earlier action"}, ts=1),
        Event(type="user", data={"text": "continue"}, ts=2),
        Event(type="permission_request", data={"id": "live", "tool": "Bash", "summary": "current action"}, ts=3),
    ]

    rows = activity.permissions(events, {"live"})

    assert {row["id"]: row["decision"] for row in rows} == {"old": "unanswered", "live": "waiting"}
