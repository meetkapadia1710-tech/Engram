"""CRUD + listing for memories."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select

from ..events import emit
from ..graph import find_related
from ..models import Memory, Workspace
from ..pipeline import compress_workspace, ingest_memory
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
    emit(g.db, "EmbeddingGenerated", {"memory_id": mem.id, "chunks": len(mem.chunks)},
         workspace_id=workspace_id)
    emit(g.db, "GraphUpdated", {"memory_id": mem.id}, workspace_id=workspace_id)
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
    m = g.db.get(Memory, memory_id)
    if m is None:
        raise HTTPException(status_code=404, detail="memory not found")
    m.access_count += 1
    m.last_accessed_at = datetime.now(timezone.utc).isoformat()
    g.db.commit()
    return memory_out(m)


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, body: MemoryUpdate, g: Guard = Depends(guard)):
    m = g.db.get(Memory, memory_id)
    if m is None:
        raise HTTPException(status_code=404, detail="memory not found")
    if body.title is not None:
        m.title = body.title
    if body.content is not None:
        from ..pipeline import chunk_text, clean_text, extract_keywords
        from ..ai import get_embedder
        from ..models import MemoryChunk

        m.content = clean_text(body.content)
        if not m.content:
            raise HTTPException(status_code=422, detail="content is empty")
        m.keywords = extract_keywords(m.content)
        chunks = chunk_text(m.content)
        vectors = get_embedder().embed(chunks + [m.content[:2000]])
        m.embedding = vectors[-1]
        for old in list(m.chunks):
            g.db.delete(old)
        for i, (chunk, vec) in enumerate(zip(chunks, vectors[:-1])):
            mc = MemoryChunk(memory_id=m.id, position=i, content=chunk)
            mc.embedding = vec
            g.db.add(mc)
    if body.tags is not None:
        m.tags = body.tags
    if body.importance is not None:
        m.importance = body.importance
    if body.archived is not None:
        m.archived = 1 if body.archived else 0
    m.updated_at = datetime.now(timezone.utc).isoformat()
    audit(g.db, actor=g.actor, action="memory.update", workspace_id=m.workspace_id, detail=m.id)
    emit(g.db, "MemoryUpdated", {"memory_id": m.id}, workspace_id=m.workspace_id)
    g.db.commit()
    return memory_out(m)


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: str, g: Guard = Depends(guard)):
    m = g.db.get(Memory, memory_id)
    if m is None:
        raise HTTPException(status_code=404, detail="memory not found")
    audit(g.db, actor=g.actor, action="memory.delete", workspace_id=m.workspace_id, detail=m.id)
    emit(g.db, "MemoryDeleted", {"memory_id": m.id}, workspace_id=m.workspace_id)
    g.db.delete(m)
    g.db.commit()


@router.get("/memories/{memory_id}/related")
def related(memory_id: str, g: Guard = Depends(guard), limit: int = Query(default=8, ge=1, le=25)):
    if g.db.get(Memory, memory_id) is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return {"items": find_related(g.db, memory_id, limit=limit)}


@router.post("/workspaces/{workspace_id}/compress")
def compress(workspace_id: str, g: Guard = Depends(guard), older_than_days: int = Query(default=90, ge=1)):
    _get_workspace(g, workspace_id)
    n = compress_workspace(g.db, workspace_id, older_than_days=older_than_days)
    audit(g.db, actor=g.actor, action="workspace.compress", workspace_id=workspace_id, detail=f"archived={n}")
    g.db.commit()
    return {"archived": n}
