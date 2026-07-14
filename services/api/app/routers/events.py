"""Event bus router.

Endpoints
---------
GET  /v1/workspaces/{ws}/events             — Event stream (paginated)
GET  /v1/workspaces/{ws}/events/{id}        — Single event detail
GET  /v1/events/types                       — All known event type strings
GET  /v1/events/dlq                         — Dead-letter queue entries
POST /v1/events/{id}/replay                 — Replay a single event
GET  /v1/events/subscribers                 — Active in-process subscribers
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select

from ..events import EVENT_TYPES, _subscribers, dead_letters, replay
from ..models_platform import EventDelivery, EventRecord
from ..security import Guard, audit, guard

router = APIRouter(prefix="/v1", tags=["events"])


@router.get("/events/types")
def event_types():
    """Return all supported event type strings."""
    return {"event_types": EVENT_TYPES}


@router.get("/events/subscribers")
def list_subscribers():
    """Return currently registered in-process subscribers."""
    return {
        "subscribers": [
            {"name": name, "filter": filt}
            for name, (filt, _) in _subscribers.items()
        ]
    }


@router.get("/workspaces/{workspace_id}/events")
def list_events(
    workspace_id: str,
    g: Guard = Depends(guard),
    type_: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List events for a workspace (most-recent first)."""
    stmt = (
        select(EventRecord)
        .where(EventRecord.workspace_id == workspace_id)
        .order_by(desc(EventRecord.seq))
    )
    if type_:
        stmt = stmt.where(EventRecord.type == type_)
    stmt = stmt.limit(limit).offset(offset)
    rows = g.db.execute(stmt).scalars().all()
    return {
        "items": [_event_out(e) for e in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/workspaces/{workspace_id}/events/{event_id}")
def get_event(workspace_id: str, event_id: str, g: Guard = Depends(guard)):
    event = g.db.execute(
        select(EventRecord).where(EventRecord.id == event_id)
    ).scalar_one_or_none()
    if event is None or event.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="event not found")

    # Include delivery attempts
    deliveries = g.db.execute(
        select(EventDelivery).where(EventDelivery.event_id == event_id)
    ).scalars().all()

    return {
        **_event_out(event),
        "deliveries": [
            {
                "subscriber": d.subscriber,
                "status": d.status,
                "attempts": d.attempts,
                "last_error": d.last_error,
                "updated_at": d.updated_at,
            }
            for d in deliveries
        ],
    }


@router.get("/events/dlq")
def get_dlq(
    g: Guard = Depends(guard),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Return dead-letter queue: failed event deliveries after max retries."""
    entries = dead_letters(g.db, limit=limit)
    return {
        "items": [
            {
                "id": d.id,
                "event_id": d.event_id,
                "subscriber": d.subscriber,
                "attempts": d.attempts,
                "last_error": d.last_error,
                "updated_at": d.updated_at,
            }
            for d in entries
        ]
    }


@router.post("/events/{event_id}/replay")
def replay_event(
    event_id: str,
    g: Guard = Depends(guard),
    subscriber: str | None = Query(default=None),
):
    """Re-dispatch a persisted event to all subscribers (or one named subscriber)."""
    try:
        n = replay(g.db, event_id, subscriber=subscriber)
    except KeyError:
        raise HTTPException(status_code=404, detail="event not found")
    audit(g.db, actor=g.actor, action="event.replay", detail=event_id)
    g.db.commit()
    return {"replayed": n, "event_id": event_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event_out(e: EventRecord) -> dict:
    return {
        "seq": e.seq,
        "id": e.id,
        "workspace_id": e.workspace_id,
        "type": e.type,
        "payload": e.payload,
        "version": e.version,
        "trace_id": e.trace_id,
        "created_at": e.created_at,
    }
