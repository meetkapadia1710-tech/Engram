"""Event bus: emit/subscribe, retry-to-dead-letter, and replay."""

from app import events


def test_emit_dispatches_to_matching_subscriber(session):
    received = []
    events.subscribe("t-exact", "WidgetCreated", lambda db, e: received.append(e.type))
    try:
        events.emit(session, "WidgetCreated", {"id": 1})
        events.emit(session, "OtherThing", {"id": 2})
        assert received == ["WidgetCreated"]
    finally:
        events.unsubscribe("t-exact")


def test_wildcard_subscriber_sees_everything(session):
    received = []
    events.subscribe("t-wild", "*", lambda db, e: received.append(e.type))
    try:
        events.emit(session, "A", {})
        events.emit(session, "B", {})
        assert received == ["A", "B"]
    finally:
        events.unsubscribe("t-wild")


def test_failing_subscriber_retries_then_dead_letters(session):
    calls = {"n": 0}

    def flaky(db, e):
        calls["n"] += 1
        raise RuntimeError("boom")

    events.subscribe("t-flaky", "Flaky", flaky)
    try:
        event = events.emit(session, "Flaky", {})
        assert calls["n"] == events.MAX_ATTEMPTS

        dead = events.dead_letters(session)
        assert any(d.event_id == event.id and d.subscriber == "t-flaky" for d in dead)
        matching = next(d for d in dead if d.event_id == event.id)
        assert matching.attempts == events.MAX_ATTEMPTS
        assert "boom" in matching.last_error
    finally:
        events.unsubscribe("t-flaky")


def test_successful_subscriber_is_not_dead_lettered(session):
    events.subscribe("t-ok", "Fine", lambda db, e: None)
    try:
        event = events.emit(session, "Fine", {})
        dead = events.dead_letters(session)
        assert not any(d.event_id == event.id for d in dead)
    finally:
        events.unsubscribe("t-ok")


def test_replay_redispatches_to_all_or_one_subscriber(session):
    # Note: other process-global subscribers (e.g. the workflow engine's "*"
    # wildcard, registered at app.workflows import time) may also legitimately
    # receive this event — so we check our own subscribers' call counts
    # rather than asserting an exact total dispatch count.
    calls_a, calls_b = [], []
    events.subscribe("t-a", "Repl", lambda db, e: calls_a.append(1))
    events.subscribe("t-b", "Repl", lambda db, e: calls_b.append(1))
    try:
        event = events.emit(session, "Repl", {})
        assert len(calls_a) == 1 and len(calls_b) == 1

        events.replay(session, event.id)
        assert len(calls_a) == 2 and len(calls_b) == 2

        n = events.replay(session, event.id, subscriber="t-a")
        assert n == 1
        assert len(calls_a) == 3 and len(calls_b) == 2
    finally:
        events.unsubscribe("t-a")
        events.unsubscribe("t-b")


def test_replay_unknown_event_raises_keyerror(session):
    import pytest

    with pytest.raises(KeyError):
        events.replay(session, "does-not-exist")


def test_unsubscribe_stops_delivery(session):
    received = []
    events.subscribe("t-unsub", "X", lambda db, e: received.append(1))
    events.unsubscribe("t-unsub")
    events.emit(session, "X", {})
    assert received == []
