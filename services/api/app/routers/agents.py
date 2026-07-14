"""Multi-agent orchestration router.

Endpoints
---------
POST /v1/workspaces/{ws}/agents/run         — Start a new agent run
GET  /v1/workspaces/{ws}/agents/runs        — List runs for workspace
GET  /v1/workspaces/{ws}/agents/runs/{id}   — Get run status + messages
GET  /v1/workspaces/{ws}/agents/runs/{id}/messages  — Collaboration timeline
GET  /v1/agents/team                        — List default agent roster
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from ..agents import DEFAULT_TEAM, run_agents
from ..models_platform import AgentMessage, AgentRun
from ..security import Guard, audit, guard

router = APIRouter(prefix="/v1", tags=["agents"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentRunRequest(BaseModel):
    goal: str
    team: list[str] | None = None  # subset of DEFAULT_TEAM keys


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/agents/team")
def list_team():
    """Return the built-in agent roster with capabilities."""
    return {
        "agents": [
            {
                "name": spec.name,
                "role": spec.role,
                "focus": spec.focus,
                "capabilities": spec.capabilities,
                "tools": spec.tools,
                "memory_types": spec.types,
            }
            for spec in DEFAULT_TEAM.values()
        ]
    }


@router.post("/workspaces/{workspace_id}/agents/run", status_code=201)
def start_run(workspace_id: str, body: AgentRunRequest, g: Guard = Depends(guard)):
    """Kick off an agent collaboration run and block until conclusion.

    For long goals consider running asynchronously via a workflow trigger.
    """
    if not body.goal.strip():
        raise HTTPException(status_code=422, detail="goal must not be empty")
    invalid = [n for n in (body.team or []) if n not in DEFAULT_TEAM]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"unknown agent names: {invalid}; valid: {list(DEFAULT_TEAM)}",
        )
    run = run_agents(g.db, workspace_id, body.goal.strip(), team=body.team)
    audit(
        g.db,
        actor=g.actor,
        action="agent.run",
        workspace_id=workspace_id,
        detail=run.id,
    )
    g.db.commit()
    return _run_out(run, include_messages=True)


@router.get("/workspaces/{workspace_id}/agents/runs")
def list_runs(
    workspace_id: str,
    g: Guard = Depends(guard),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    rows = g.db.execute(
        select(AgentRun)
        .where(AgentRun.workspace_id == workspace_id)
        .order_by(desc(AgentRun.started_at))
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return {"items": [_run_out(r) for r in rows], "limit": limit, "offset": offset}


@router.get("/workspaces/{workspace_id}/agents/runs/{run_id}")
def get_run(workspace_id: str, run_id: str, g: Guard = Depends(guard)):
    run = g.db.get(AgentRun, run_id)
    if run is None or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_out(run, include_messages=True)


@router.get("/workspaces/{workspace_id}/agents/runs/{run_id}/messages")
def get_messages(
    workspace_id: str,
    run_id: str,
    g: Guard = Depends(guard),
    sender: str | None = Query(default=None),
    kind: str | None = Query(default=None),
):
    """Return the full collaboration timeline for a run."""
    run = g.db.get(AgentRun, run_id)
    if run is None or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="run not found")
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.run_id == run_id)
        .order_by(AgentMessage.seq)
    )
    if sender:
        stmt = stmt.where(AgentMessage.sender == sender)
    if kind:
        stmt = stmt.where(AgentMessage.kind == kind)
    msgs = g.db.execute(stmt).scalars().all()
    return {
        "run_id": run_id,
        "messages": [_msg_out(m) for m in msgs],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_out(run: AgentRun, *, include_messages: bool = False) -> dict:
    import json

    out: dict = {
        "id": run.id,
        "workspace_id": run.workspace_id,
        "goal": run.goal,
        "agents": json.loads(run.agents_json or "[]"),
        "status": run.status,
        "conclusion": run.conclusion,
        "conclusion_memory_id": run.conclusion_memory_id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }
    if include_messages:
        out["messages"] = [_msg_out(m) for m in run.messages]
    return out


def _msg_out(m: AgentMessage) -> dict:
    return {
        "seq": m.seq,
        "sender": m.sender,
        "recipient": m.recipient,
        "kind": m.kind,
        "content": m.content,
        "created_at": m.created_at,
    }
