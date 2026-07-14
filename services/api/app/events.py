"""Event bus: append-only log + in-process dispatch with retry/DLQ/replay.

Design: every `emit()` persists an EventRecord (total ordering via `seq`),
then dispatches synchronously to registered subscribers. Each delivery is
tracked; a subscriber failure is retried up to MAX_ATTEMPTS and then parked
in the dead-letter queue, from which it can be replayed. Metrics are kept by
the observability module.

Subscribers are process-local (the workflow engine, streaming fan-out,
plugins). For multi-instance deployments the same EventRecord table acts as
an outbox that a broker consumer can tail — the emit contract stays identical.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import _now_iso
from .models_platform import EventDelivery, EventRecord

log = logging.getLogger("engram.events")

MAX_ATTEMPTS = 3

EVENT_TYPES = [
    "MemoryCreated", "MemoryUpdated", "MemoryDeleted", "GraphUpdated",
    "EmbeddingGenerated", "PluginInstalled", "PluginUninstalled",
    "WorkspaceCreated", "AgentStarted", "AgentFinished", "SearchExecuted",
    "ContextBuilt", "RetrievalCompleted", "LLMCompleted", "WorkflowStarted",
    "WorkflowFinished", "InsightGenerated", "ContradictionDetected",
]

# subscriber name -> (event_type_filter or "*", callback(db, event))
_subscribers: dict[str, tuple[str, Callable[[Session, EventRecord], None]]] = {}


def subscribe(name: str, event_type: str, fn: Callable[[Session, EventRecord], None]) -> None:
    _subscribers[name] = (event_type, fn)


def unsubscribe(name: str) -> None:
    _subscribers.pop(name, None)


def _deliver(db: Session, event: EventRecord, name: str, fn) -> None:
    delivery = EventDelivery(event_id=event.id, subscriber=name)
    db.add(delivery)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        delivery.attempts = attempt
        try:
            fn(db, event)
            delivery.status = "ok"
            delivery.updated_at = _now_iso()
            db.flush()  # session doesn't autoflush; dead_letters()/replay()
            return       # in the same transaction must see this immediately
        except Exception as exc:  # noqa: BLE001 — subscriber isolation is the point
            delivery.status = "retrying"
            delivery.last_error = f"{type(exc).__name__}: {exc}"[:500]
            log.warning("subscriber %s failed on %s (attempt %d): %s",
                        name, event.type, attempt, exc)
    delivery.status = "dead"
    delivery.updated_at = _now_iso()
    db.flush()


def emit(
    db: Session,
    type_: str,
    payload: dict | None = None,
    *,
    workspace_id: str = "",
    trace_id: str = "",
) -> EventRecord:
    """Persist + dispatch one event. Never raises on subscriber failure."""
    import json

    from . import observability

    event = EventRecord(
        workspace_id=workspace_id,
        type=type_,
        payload_json=json.dumps(payload or {}, default=str),
        trace_id=trace_id,
    )
    db.add(event)
    db.flush()  # assign seq/id before dispatch

    observability.count(f"events.{type_}")
    for name, (filt, fn) in list(_subscribers.items()):
        if filt in ("*", type_):
            _deliver(db, event, name, fn)
    return event


def replay(db: Session, event_id: str, subscriber: str | None = None) -> int:
    """Re-dispatch a stored event (all subscribers, or one). Returns count."""
    event = (
        db.query(EventRecord).filter(EventRecord.id == event_id).one_or_none()
    )
    if event is None:
        raise KeyError(event_id)
    n = 0
    for name, (filt, fn) in list(_subscribers.items()):
        if subscriber and name != subscriber:
            continue
        if filt in ("*", event.type):
            _deliver(db, event, name, fn)
            n += 1
    return n


def dead_letters(db: Session, limit: int = 50) -> list[EventDelivery]:
    return (
        db.query(EventDelivery)
        .filter(EventDelivery.status == "dead")
        .order_by(EventDelivery.updated_at.desc())
        .limit(limit)
        .all()
    )
