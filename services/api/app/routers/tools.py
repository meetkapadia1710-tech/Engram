"""Tool registry and execution router.

Endpoints
---------
GET  /v1/tools                              — List all registered tools (schemas)
                                              Each tool has: name, description,
                                              permission (str), schema, timeout_s
POST /v1/workspaces/{ws}/tools/{name}       — Execute a tool
GET  /v1/workspaces/{ws}/tool-executions    — Audit history
GET  /v1/workspaces/{ws}/tool-executions/{id} — Single execution detail
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from ..models_platform import ToolExecution
from ..security import Guard, audit, guard
from ..tools import ToolError, execute, list_tools

router = APIRouter(prefix="/v1", tags=["tools"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ExecuteBody(BaseModel):
    args: dict = {}
    # Caller-supplied permission list; empty means no permission override
    granted_permissions: list[str] | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/tools")
def get_tools():
    """Return all registered tools with their JSON schemas and permissions."""
    return {"tools": list_tools()}


@router.post("/workspaces/{workspace_id}/tools/{tool_name}")
def execute_tool(
    workspace_id: str,
    tool_name: str,
    body: ExecuteBody | None = None,
    g: Guard = Depends(guard),
):
    """Execute a named tool with sandboxing and audit logging."""
    args = body.args if body else {}
    granted = body.granted_permissions if body else None
    try:
        result = execute(
            g.db,
            tool_name,
            args,
            workspace_id=workspace_id,
            caller=g.actor,
            granted_permissions=granted,
        )
    except ToolError as e:
        raise HTTPException(
            status_code=403 if e.status == "denied" else 400,
            detail=e.detail,
        ) from e
    audit(
        g.db,
        actor=g.actor,
        action=f"tool.execute.{tool_name}",
        workspace_id=workspace_id,
    )
    g.db.commit()
    return {"tool": tool_name, "status": "ok", "result": result}


@router.get("/workspaces/{workspace_id}/tool-executions")
def list_executions(
    workspace_id: str,
    g: Guard = Depends(guard),
    tool: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Return the audited tool execution history for a workspace."""
    stmt = (
        select(ToolExecution)
        .where(ToolExecution.workspace_id == workspace_id)
        .order_by(desc(ToolExecution.created_at))
    )
    if tool:
        stmt = stmt.where(ToolExecution.tool == tool)
    if status:
        stmt = stmt.where(ToolExecution.status == status)
    stmt = stmt.limit(limit).offset(offset)
    rows = g.db.execute(stmt).scalars().all()
    return {
        "items": [_exec_out(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/workspaces/{workspace_id}/tool-executions/{execution_id}")
def get_execution(workspace_id: str, execution_id: str, g: Guard = Depends(guard)):
    row = g.db.get(ToolExecution, execution_id)
    if row is None or row.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="execution not found")
    return _exec_out(row, include_args=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _exec_out(row: ToolExecution, *, include_args: bool = False) -> dict:
    import json

    out: dict = {
        "id": row.id,
        "tool": row.tool,
        "caller": row.caller,
        "status": row.status,
        "duration_ms": row.duration_ms,
        "result_preview": row.result_preview,
        "created_at": row.created_at,
    }
    if include_args:
        try:
            out["args"] = json.loads(row.args_json or "{}")
        except Exception:
            out["args"] = {}
    return out
