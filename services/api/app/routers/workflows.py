"""Workflow CRUD + run + history router.

Endpoints
---------
POST /v1/workspaces/{ws}/workflows              — Create workflow
GET  /v1/workspaces/{ws}/workflows              — List workflows
GET  /v1/workspaces/{ws}/workflows/{id}         — Get workflow
PATCH /v1/workspaces/{ws}/workflows/{id}        — Update workflow
DELETE /v1/workspaces/{ws}/workflows/{id}       — Delete workflow
POST /v1/workspaces/{ws}/workflows/{id}/trigger — Manual trigger
GET  /v1/workspaces/{ws}/workflow-runs          — List recent runs
GET  /v1/workspaces/{ws}/workflow-runs/{rid}    — Get run detail + log
GET  /v1/events                                 — Available event types (for trigger picker)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from ..events import EVENT_TYPES
from ..models import _now_iso
from ..models_platform import Workflow, WorkflowRun
from ..security import Guard, audit, guard
from ..workflows import run_workflow

router = APIRouter(prefix="/v1", tags=["workflows"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    trigger_event: str = ""   # "" = manual only; event type string otherwise
    steps: list[dict]
    enabled: bool = True


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_event: str | None = None
    steps: list[dict] | None = None
    enabled: bool | None = None


class TriggerBody(BaseModel):
    variables: dict = {}


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------


def _get_workflow(g: Guard, workspace_id: str, workflow_id: str) -> Workflow:
    wf = g.db.get(Workflow, workflow_id)
    if wf is None or wf.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workflow not found")
    return wf


@router.post("/workspaces/{workspace_id}/workflows", status_code=201)
def create_workflow(
    workspace_id: str, body: WorkflowCreate, g: Guard = Depends(guard)
):
    import json

    if body.trigger_event and body.trigger_event not in EVENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown event type {body.trigger_event!r}; valid: {EVENT_TYPES}",
        )
    if len(body.steps) > 50:
        raise HTTPException(status_code=422, detail="maximum 50 steps per workflow")

    wf = Workflow(
        workspace_id=workspace_id,
        name=body.name[:200],
        description=body.description[:1000],
        trigger_event=body.trigger_event,
        steps_json=json.dumps(body.steps),
        enabled=1 if body.enabled else 0,
    )
    g.db.add(wf)
    audit(g.db, actor=g.actor, action="workflow.create",
          workspace_id=workspace_id, detail=body.name)
    g.db.commit()
    g.db.refresh(wf)
    return _workflow_out(wf)


@router.get("/workspaces/{workspace_id}/workflows")
def list_workflows(
    workspace_id: str,
    g: Guard = Depends(guard),
    enabled_only: bool = False,
):
    stmt = select(Workflow).where(Workflow.workspace_id == workspace_id)
    if enabled_only:
        stmt = stmt.where(Workflow.enabled == 1)
    stmt = stmt.order_by(desc(Workflow.created_at))
    rows = g.db.execute(stmt).scalars().all()
    return {"items": [_workflow_out(w) for w in rows]}


@router.get("/workspaces/{workspace_id}/workflows/{workflow_id}")
def get_workflow(workspace_id: str, workflow_id: str, g: Guard = Depends(guard)):
    return _workflow_out(_get_workflow(g, workspace_id, workflow_id))


@router.patch("/workspaces/{workspace_id}/workflows/{workflow_id}")
def update_workflow(
    workspace_id: str,
    workflow_id: str,
    body: WorkflowUpdate,
    g: Guard = Depends(guard),
):
    import json

    wf = _get_workflow(g, workspace_id, workflow_id)
    if body.name is not None:
        wf.name = body.name[:200]
    if body.description is not None:
        wf.description = body.description[:1000]
    if body.trigger_event is not None:
        if body.trigger_event and body.trigger_event not in EVENT_TYPES:
            raise HTTPException(status_code=422, detail=f"unknown event type {body.trigger_event!r}")
        wf.trigger_event = body.trigger_event
    if body.steps is not None:
        wf.steps_json = json.dumps(body.steps)
    if body.enabled is not None:
        wf.enabled = 1 if body.enabled else 0
    wf.updated_at = _now_iso()
    audit(g.db, actor=g.actor, action="workflow.update",
          workspace_id=workspace_id, detail=workflow_id)
    g.db.commit()
    return _workflow_out(wf)


@router.delete("/workspaces/{workspace_id}/workflows/{workflow_id}", status_code=204)
def delete_workflow(workspace_id: str, workflow_id: str, g: Guard = Depends(guard)):
    wf = _get_workflow(g, workspace_id, workflow_id)
    g.db.delete(wf)
    audit(g.db, actor=g.actor, action="workflow.delete",
          workspace_id=workspace_id, detail=workflow_id)
    g.db.commit()


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


@router.post("/workspaces/{workspace_id}/workflows/{workflow_id}/trigger")
def trigger_workflow(
    workspace_id: str,
    workflow_id: str,
    body: TriggerBody | None = None,
    g: Guard = Depends(guard),
):
    """Manually trigger a workflow run."""
    wf = _get_workflow(g, workspace_id, workflow_id)
    if not wf.enabled:
        raise HTTPException(status_code=409, detail="workflow is disabled")
    run = run_workflow(
        g.db, wf,
        variables=(body.variables if body else {}),
        trigger="manual",
    )
    audit(g.db, actor=g.actor, action="workflow.trigger",
          workspace_id=workspace_id, detail=f"{workflow_id}→{run.id}")
    g.db.commit()
    return _run_out(run)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/workflow-runs")
def list_runs(
    workspace_id: str,
    g: Guard = Depends(guard),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
):
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.workspace_id == workspace_id)
        .order_by(desc(WorkflowRun.started_at))
    )
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    stmt = stmt.limit(limit).offset(offset)
    rows = g.db.execute(stmt).scalars().all()
    return {"items": [_run_out(r) for r in rows], "limit": limit, "offset": offset}


@router.get("/workspaces/{workspace_id}/workflow-runs/{run_id}")
def get_run(workspace_id: str, run_id: str, g: Guard = Depends(guard)):
    run = g.db.get(WorkflowRun, run_id)
    if run is None or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_out(run, include_log=True)


# ---------------------------------------------------------------------------
# Event type catalogue (for UI trigger picker)
# ---------------------------------------------------------------------------


@router.get("/workflow-event-types")
def event_types():
    return {"event_types": EVENT_TYPES}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _workflow_out(wf: Workflow) -> dict:
    return {
        "id": wf.id,
        "workspace_id": wf.workspace_id,
        "name": wf.name,
        "description": wf.description,
        "trigger_event": wf.trigger_event,
        "steps": wf.steps,
        "enabled": bool(wf.enabled),
        "created_at": wf.created_at,
        "updated_at": wf.updated_at,
    }


def _run_out(run: WorkflowRun, *, include_log: bool = False) -> dict:
    out = {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "workspace_id": run.workspace_id,
        "status": run.status,
        "trigger": run.trigger,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }
    if include_log:
        out["log"] = run.log
    return out
