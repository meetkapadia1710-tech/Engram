"""CRUD + listing for memories — backed by Supermemory."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from ..events import emit
from ..models import Memory, Workspace
from ..pipeline import ingest_memory
from ..schemas import MEMORY_TYPES, MemoryCreate, MemoryOut, MemoryUpdate
from ..db import get_memory_store
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
    store = get_memory_store()
    memories = store.list(workspace_id, limit=limit, offset=offset)
    if not include_archived:
        memories = [m for m in memories if not m.archived]
    if type:
        memories = [m for m in memories if m.type == type]
    items = [memory_out(m) for m in memories[:limit]]
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/memories/{memory_id}", response_model=MemoryOut)
def get_memory(memory_id: str, g: Guard = Depends(guard)):
    store = get_memory_store()
    m = store.get(None, memory_id)
    if m is None:
        raise HTTPException(status_code=404, detail="memory not found")
    # Increment access counter and persist it back to Supermemory
    m.access_count += 1
    m.last_accessed_at = datetime.now(timezone.utc).isoformat()
    store.update(m.workspace_id, m.id, m.content, {
        "title": m.title, "type": m.type, "summary": m.summary,
        "source": m.source, "author": m.author, "importance": m.importance,
        "keywords": m.keywords, "tags": m.tags, "access_count": m.access_count,
    })
    return memory_out(m)


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, body: MemoryUpdate, g: Guard = Depends(guard)):
    store = get_memory_store()
    m = store.get(None, memory_id)
    if m is None:
        raise HTTPException(status_code=404, detail="memory not found")
    if body.title is not None:
        m.title = body.title
    if body.content is not None:
        from ..pipeline import clean_text, extract_keywords
        m.content = clean_text(body.content)
        if not m.content:
            raise HTTPException(status_code=422, detail="content is empty")
        m.keywords = extract_keywords(m.content)
    if body.tags is not None:
        m.tags = body.tags
    if body.importance is not None:
        m.importance = body.importance
    if body.archived is not None:
        m.archived = 1 if body.archived else 0
    m.updated_at = datetime.now(timezone.utc).isoformat()

    metadata = {
        "title": m.title, "type": m.type, "summary": m.summary,
        "source": m.source, "author": m.author, "importance": m.importance,
        "keywords": m.keywords, "tags": m.tags, "access_count": m.access_count,
        "archived": m.archived, "updated_at": m.updated_at,
    }
    store.update(m.workspace_id, m.id, m.content, metadata)

    audit(g.db, actor=g.actor, action="memory.update", workspace_id=m.workspace_id, detail=m.id)
    emit(g.db, "MemoryUpdated", {"memory_id": m.id}, workspace_id=m.workspace_id)
    g.db.commit()
    return memory_out(m)


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: str, g: Guard = Depends(guard)):
    store = get_memory_store()
    m = store.get(None, memory_id)
    if m is None:
        raise HTTPException(status_code=404, detail="memory not found")
    audit(g.db, actor=g.actor, action="memory.delete", workspace_id=m.workspace_id, detail=m.id)
    emit(g.db, "MemoryDeleted", {"memory_id": m.id}, workspace_id=m.workspace_id)
    store.delete(m.workspace_id, m.id)
    g.db.commit()


@router.get("/memories/{memory_id}/related")
def related(memory_id: str, g: Guard = Depends(guard), limit: int = Query(default=8, ge=1, le=25)):
    """Return semantically related memories by searching with the memory's own content."""
    store = get_memory_store()
    m = store.get(None, memory_id)
    if m is None:
        raise HTTPException(status_code=404, detail="memory not found")
    # Use memory's title + first 200 chars of content as the query for related search
    query = f"{m.title} {m.content[:200]}".strip()
    related_mems = store.search(m.workspace_id, query, limit=limit + 1)
    # Exclude the memory itself from results
    related_mems = [r for r in related_mems if r.id != memory_id][:limit]
    return {"items": [memory_out(r) for r in related_mems]}


@router.post("/workspaces/{workspace_id}/compress")
def compress(workspace_id: str, g: Guard = Depends(guard), older_than_days: int = Query(default=90, ge=1)):
    """Mark low-value memories as archived.

    With Supermemory as the backend, memories are stored externally; this
    endpoint scans the workspace and updates the ``archived`` metadata flag on
    qualifying memories (old + rarely-accessed + low-importance).
    """
    _get_workspace(g, workspace_id)
    store = get_memory_store()
    memories = store.list(workspace_id, limit=10000, offset=0)

    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    archived_count = 0

    for m in memories:
        if m.archived:
            continue
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
            metadata = {
                "title": m.title, "type": m.type, "summary": m.summary,
                "source": m.source, "author": m.author, "importance": m.importance,
                "keywords": m.keywords, "tags": m.tags, "access_count": m.access_count,
                "archived": 1, "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            store.update(m.workspace_id, m.id, m.content, metadata)
            archived_count += 1

    audit(g.db, actor=g.actor, action="workspace.compress", workspace_id=workspace_id,
          detail=f"archived={archived_count}")
    g.db.commit()
    return {"archived": archived_count}
