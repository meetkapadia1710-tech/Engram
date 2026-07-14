"""Search, RAG context, and graph endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import observability
from ..events import emit
from ..graph import build_graph
from ..models import Workspace
from ..rag import build_context
from ..schemas import ContextRequest, SearchRequest
from ..search import hybrid_search
from ..security import Guard, audit, guard
from .memories import memory_out

router = APIRouter(prefix="/v1", tags=["search"])


def _check_ws(g: Guard, workspace_id: str) -> None:
    if g.db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")


@router.post("/workspaces/{workspace_id}/search")
def search(workspace_id: str, body: SearchRequest, g: Guard = Depends(guard)):
    _check_ws(g, workspace_id)
    with observability.timed("search"):
        hits = hybrid_search(
            g.db, workspace_id, body.query,
            limit=body.limit, mode=body.mode, types=body.types, tags=body.tags,
            entities=body.entities, date_from=body.date_from, date_to=body.date_to,
        )
    audit(g.db, actor=g.actor, action="search", workspace_id=workspace_id, detail=body.query[:200])
    emit(g.db, "SearchExecuted",
         {"query": body.query[:200], "mode": body.mode, "hits": len(hits)},
         workspace_id=workspace_id)
    g.db.commit()
    return {
        "query": body.query,
        "mode": body.mode,
        "results": [
            {"memory": memory_out(h.memory), "score": h.final, "components": h.components}
            for h in hits
        ],
    }


@router.post("/workspaces/{workspace_id}/context")
def context(workspace_id: str, body: ContextRequest, g: Guard = Depends(guard)):
    _check_ws(g, workspace_id)
    with observability.timed("context"):
        result = build_context(
            g.db, workspace_id, body.query,
            max_tokens=body.max_tokens, limit=body.limit, types=body.types,
            date_from=body.date_from, date_to=body.date_to,
        )
    emit(g.db, "ContextBuilt",
         {"query": body.query[:200], "sources": len(result["sources"]),
          "approx_tokens": result["approx_tokens"]},
         workspace_id=workspace_id)
    g.db.commit()
    return result


@router.get("/workspaces/{workspace_id}/graph")
def graph(
    workspace_id: str,
    g: Guard = Depends(guard),
    center: str | None = Query(default=None),
    hops: int = Query(default=2, ge=1, le=4),
    max_nodes: int = Query(default=150, ge=10, le=500),
):
    _check_ws(g, workspace_id)
    return build_graph(g.db, workspace_id, center_id=center, hops=hops, max_nodes=max_nodes)
