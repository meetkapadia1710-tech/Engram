"""CRUD + listing for memories.

Supermemory Local is the durable, semantically-searchable content store; the
local SQLite mirror (populated by pipeline.ingest_memory) is the source of
truth for structured fields the knowledge graph and ranking depend on
(access_count, importance, confidence, entity links, relationships). Reads
never write back to Supermemory — only create/update/delete/compress do,
and always with the complete metadata snapshot so a partial write can never
clobber a field another code path relies on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select

from ..db import build_full_metadata, get_memory_store
from ..events import emit
from ..graph import find_related
from ..models import Memory, Workspace
from ..pipeline import ingest_memory
from ..schemas import MEMORY_TYPES, MemoryCreate, MemoryOut, MemoryUpdate
from ..security import Guard, audit, guard

router = APIRouter(prefix="/v1", tags=["memories"])


def memory_out(m: Memory) -> MemoryOut:
    return MemoryOut(
        id=m.id, workspace_id=m.workspace_id, type=m.type, title=m.title,
        content=m.content, summary=m.summary, keywords=m.keywords, tags=m.tags,
        source=m.source, author=m.author, importance=m.importance,
        confidence=m.confidence, access_count=m.access_count,
        archived=bool(m.archived), created_at=m.created_at, updated_at=m.updated_at,
        entities=[
            {"id": l.entity.id, "name": l.entity.name, "kind": l.entity.kind}
            for l in m.entity_links
        ],
    )


def _get_workspace(g: Guard, workspace_id: str) -> Workspace:
    ws = g.db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return ws


def _get_local_memory(g: Guard, memory_id: str) -> Memory:
    m = g.db.get(Memory, memory_id)
    if m is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return m


@router.get("/types")
def list_types() -> list[str]:
    return MEMORY_TYPES


@router.post("/workspaces/{workspace_id}/memories", response_model=MemoryOut, status_code=201)
def create_memory(workspace_id: str, body: MemoryCreate, g: Guard = Depends(guard)):
    _get_workspace(g, workspace_id)
    if body.type not in MEMORY_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown memory type {body.type!r}")
    try:
        mem = ingest_memory(
            g.db, workspace_id=workspace_id, content=body.content, type_=body.type,
            title=body.title, source=body.source, author=body.author, tags=body.tags,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    audit(g.db, actor=g.actor, action="memory.create", workspace_id=workspace_id, detail=mem.id)
    emit(g.db, "MemoryCreated", {"memory_id": mem.id, "type": mem.type, "title": mem.title},
         workspace_id=workspace_id)
    g.db.commit()
    return memory_out(mem)


@router.get("/workspaces/{workspace_id}/memories")
def list_memories(
    workspace_id: str,
    g: Guard = Depends(guard),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    type: str | None = None,
    include_archived: bool = False,
):
    _get_workspace(g, workspace_id)
    q = select(Memory).where(Memory.workspace_id == workspace_id)
    if not include_archived:
        q = q.where(Memory.archived == 0)
    if type:
        q = q.where(Memory.type == type)
    q = q.order_by(desc(Memory.created_at)).limit(limit).offset(offset)
    items = [memory_out(m) for m in g.db.execute(q).scalars()]
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/memories/{memory_id}", response_model=MemoryOut)
def get_memory(memory_id: str, g: Guard = Depends(guard)):
    m = _get_local_memory(g, memory_id)
    m.access_count += 1
    m.last_accessed_at = datetime.now(timezone.utc).isoformat()
    g.db.commit()
    return memory_out(m)


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, body: MemoryUpdate, g: Guard = Depends(guard)):
    m = _get_local_memory(g, memory_id)
    if body.title is not None:
        m.title = body.title
    if body.content is not None:
        from ..pipeline import apply_content_update

        try:
            apply_content_update(g.db, m, body.content)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    if body.tags is not None:
        m.tags = body.tags
    if body.importance is not None:
        m.importance = body.importance
    if body.archived is not None:
        m.archived = 1 if body.archived else 0
    m.updated_at = datetime.now(timezone.utc).isoformat()

    store = get_memory_store(g.db)
    store.update(m.workspace_id, m.id, m.content, build_full_metadata(m))

    audit(g.db, actor=g.actor, action="memory.update", workspace_id=m.workspace_id, detail=m.id)
    emit(g.db, "MemoryUpdated", {"memory_id": m.id}, workspace_id=m.workspace_id)
    g.db.commit()
    return memory_out(m)


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: str, g: Guard = Depends(guard)):
    m = _get_local_memory(g, memory_id)
    audit(g.db, actor=g.actor, action="memory.delete", workspace_id=m.workspace_id, detail=m.id)
    emit(g.db, "MemoryDeleted", {"memory_id": m.id}, workspace_id=m.workspace_id)
    store = get_memory_store(g.db)
    store.delete(m.workspace_id, m.id)
    g.db.delete(m)
    g.db.commit()


@router.get("/memories/{memory_id}/related")
def related(memory_id: str, g: Guard = Depends(guard), limit: int = Query(default=8, ge=1, le=25)):
    if g.db.get(Memory, memory_id) is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return {"items": find_related(g.db, memory_id, limit=limit)}


@router.post("/workspaces/{workspace_id}/compress")
def compress(workspace_id: str, g: Guard = Depends(guard), older_than_days: int = Query(default=90, ge=1)):
    """Archive stale, rarely-accessed, low-importance memories.

    Archiving is local-first (the local mirror is the ranking source of
    truth); the archived flag is then synced to Supermemory with a complete
    metadata snapshot so no other field is clobbered.
    """
    _get_workspace(g, workspace_id)
    store = get_memory_store(g.db)
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    archived_count = 0

    memories = g.db.execute(
        select(Memory).where(Memory.workspace_id == workspace_id, Memory.archived == 0)
    ).scalars().all()
    for m in memories:
        try:
            created = datetime.fromisoformat(m.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if created < cutoff and m.access_count < 2 and m.importance < 0.6:
            m.archived = 1
            if not m.summary:
                m.summary = m.content[:280]
            m.updated_at = datetime.now(timezone.utc).isoformat()
            store.update(m.workspace_id, m.id, m.content, build_full_metadata(m))
            archived_count += 1

    audit(g.db, actor=g.actor, action="workspace.compress", workspace_id=workspace_id,
          detail=f"archived={archived_count}")
    g.db.commit()
    return {"archived": archived_count}
