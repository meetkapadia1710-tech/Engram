"""Workspaces (multi-tenancy) + analytics + audit log."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select

from ..models import AuditLog, Entity, Memory, Relationship, Workspace
from ..schemas import WorkspaceCreate, WorkspaceOut
from ..security import Guard, audit, guard

router = APIRouter(prefix="/v1", tags=["workspaces"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "workspace"


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
def create_workspace(body: WorkspaceCreate, g: Guard = Depends(guard)):
    slug = body.slug or _slugify(body.name)
    if g.db.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"slug {slug!r} already exists")
    ws = Workspace(name=body.name, slug=slug)
    g.db.add(ws)
    audit(g.db, actor=g.actor, action="workspace.create", detail=slug)
    from ..events import emit

    emit(g.db, "WorkspaceCreated", {"slug": slug}, workspace_id=ws.id)
    g.db.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, slug=ws.slug, created_at=ws.created_at)


@router.get("/workspaces")
def list_workspaces(g: Guard = Depends(guard)):
    out = []
    for ws in g.db.execute(select(Workspace)).scalars():
        count = g.db.execute(
            select(func.count(Memory.id)).where(
                Memory.workspace_id == ws.id, Memory.archived == 0
            )
        ).scalar_one()
        out.append(WorkspaceOut(
            id=ws.id, name=ws.name, slug=ws.slug,
            created_at=ws.created_at, memory_count=count,
        ))
    return {"items": out}


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, g: Guard = Depends(guard)):
    ws = g.db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    audit(g.db, actor=g.actor, action="workspace.delete", workspace_id=workspace_id, detail=ws.slug)
    g.db.delete(ws)
    g.db.commit()


@router.get("/workspaces/{workspace_id}/analytics")
def analytics(workspace_id: str, g: Guard = Depends(guard)):
    if g.db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")

    from ..db import get_memory_store
    store = get_memory_store(g.db)
    memories = store.list(workspace_id, limit=10000, offset=0)
    
    # We don't have entities and rels in SQLite anymore, just mock for analytics
    entity_count = sum(len(m.entity_links) for m in memories)
    rel_count = 0

    by_type = Counter(m.type for m in memories if not m.archived)

    # 14-day activity series
    today = datetime.now(timezone.utc).date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    per_day = Counter(m.created_at[:10] for m in memories)
    activity = [{"date": d, "count": per_day.get(d, 0)} for d in days]

    # mock top entities
    ents = {}
    for m in memories:
        for l in m.entity_links:
            ents[l.entity.name] = ents.get(l.entity.name, 0) + 1
    top_entities = [{"name": name, "kind": "concept", "mentions": count} 
                    for name, count in sorted(ents.items(), key=lambda x: -x[1])[:10]]

    return {
        "memories": sum(1 for m in memories if not m.archived),
        "archived": sum(1 for m in memories if m.archived),
        "entities": entity_count,
        "relationships": rel_count,
        "by_type": dict(by_type),
        "activity": activity,
        "top_entities": top_entities,
    }


@router.get("/workspaces/{workspace_id}/audit")
def audit_log(workspace_id: str, g: Guard = Depends(guard), limit: int = 50):
    rows = g.db.execute(
        select(AuditLog)
        .where(AuditLog.workspace_id == workspace_id)
        .order_by(desc(AuditLog.created_at))
        .limit(min(limit, 200))
    ).scalars()
    return {
        "items": [
            {"actor": a.actor, "action": a.action, "detail": a.detail, "at": a.created_at}
            for a in rows
        ]
    }
