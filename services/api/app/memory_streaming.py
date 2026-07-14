"""Memory streaming via Server-Sent Events (SSE).

Clients subscribe to a workspace event stream and receive real-time
notifications as memories, embeddings, graph updates, and other platform
events are emitted.

Usage
-----
    GET /v1/workspaces/{ws}/stream?types=MemoryCreated,GraphUpdated

The response is ``text/event-stream``. Each event is a JSON-encoded
EventRecord payload preceded by ``event: <type>`` and ``data: <json>``.

Design notes
------------
* Uses FastAPI's ``StreamingResponse`` — no WebSocket server needed.
* In-process: works with the existing ``events.subscribe`` mechanism.
* For multi-instance deployments, wire the SSE generator to a Redis
  pub/sub channel instead of the in-process queue (drop-in replacement).
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .events import subscribe, unsubscribe
from .models_platform import EventRecord
from .security import Guard, guard

router = APIRouter(prefix="/v1", tags=["streaming"])


def _make_sse_message(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/workspaces/{workspace_id}/stream")
async def event_stream(
    workspace_id: str,
    g: Guard = Depends(guard),
    types: str | None = Query(
        default=None,
        description="Comma-separated event types to subscribe to. Omit for all.",
    ),
    heartbeat_s: int = Query(default=15, ge=5, le=60),
):
    """Server-Sent Events stream for real-time workspace events."""
    type_filter: set[str] | None = (
        {t.strip() for t in types.split(",") if t.strip()} if types else None
    )
    q: queue.Queue = queue.Queue(maxsize=500)
    sub_name = f"sse-{workspace_id}-{id(q)}"

    def _on_event(db: Session, event: EventRecord) -> None:
        if event.workspace_id != workspace_id:
            return
        if type_filter and event.type not in type_filter:
            return
        try:
            q.put_nowait(
                {
                    "type": event.type,
                    "id": event.id,
                    "seq": event.seq,
                    "payload": event.payload,
                    "created_at": event.created_at,
                }
            )
        except queue.Full:
            pass  # drop if consumer is too slow

    subscribe(sub_name, "*", _on_event)

    async def generate() -> AsyncGenerator[str, None]:
        last_heartbeat = time.monotonic()
        try:
            yield _make_sse_message("connected", {"workspace_id": workspace_id})
            while True:
                now = time.monotonic()
                # Heartbeat to keep connection alive
                if now - last_heartbeat >= heartbeat_s:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now
                # Drain pending events
                drained = False
                while True:
                    try:
                        item = q.get_nowait()
                        yield _make_sse_message(item["type"], item)
                        drained = True
                    except queue.Empty:
                        break
                if not drained:
                    await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(sub_name)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
