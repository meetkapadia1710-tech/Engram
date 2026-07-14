"""Observability router.

Endpoints
---------
GET /metrics          — Prometheus text exposition (process-local)
GET /v1/metrics       — JSON snapshot of counters + latency histograms
GET /v1/metrics/agent-timelines — Recent agent run durations
GET /v1/metrics/search          — Search-specific metrics
GET /v1/metrics/pipeline        — Memory pipeline metrics
GET /v1/metrics/workers         — Worker/queue health stub
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import desc, func, select

from .. import observability
from ..models_platform import AgentRun, WorkflowRun
from ..security import Guard, guard

router = APIRouter(tags=["observability"])


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
def prometheus_metrics():
    """Prometheus text-format metrics endpoint (scrape target)."""
    return PlainTextResponse(
        content=observability.prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/v1/metrics")
def json_metrics(g: Guard = Depends(guard)):
    """JSON snapshot of all platform counters and latency histograms."""
    snap = observability.snapshot()
    return {
        "uptime_s": snap["uptime_s"],
        "counters": snap["counters"],
        "latency": snap["latency"],
    }


@router.get("/v1/metrics/agent-timelines")
def agent_timelines(g: Guard = Depends(guard)):
    """Recent agent run durations and statuses for the timeline view."""
    runs = g.db.execute(
        select(AgentRun)
        .order_by(desc(AgentRun.started_at))
        .limit(50)
    ).scalars().all()

    items = []
    for r in runs:
        started = r.started_at or ""
        finished = r.finished_at or ""
        duration_ms: float | None = None
        if started and finished:
            try:
                from datetime import datetime, timezone
                s = datetime.fromisoformat(started)
                f = datetime.fromisoformat(finished)
                duration_ms = round((f - s).total_seconds() * 1000, 1)
            except ValueError:
                pass
        items.append({
            "id": r.id,
            "workspace_id": r.workspace_id,
            "status": r.status,
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
        })
    return {"agent_runs": items}


@router.get("/v1/metrics/search")
def search_metrics(g: Guard = Depends(guard)):
    """Search-related metrics extracted from the observability snapshot."""
    snap = observability.snapshot()
    counters = snap["counters"]
    latency = snap["latency"]
    return {
        "searches_total": counters.get("events.SearchExecuted", 0),
        "context_built_total": counters.get("events.ContextBuilt", 0),
        "retrieval_completed_total": counters.get("events.RetrievalCompleted", 0),
        "hybrid_search_latency": latency.get("search", {}),
        "rag_build_latency": latency.get("rag", {}),
    }


@router.get("/v1/metrics/pipeline")
def pipeline_metrics(g: Guard = Depends(guard)):
    """Memory ingestion pipeline metrics."""
    snap = observability.snapshot()
    counters = snap["counters"]
    latency = snap["latency"]
    return {
        "memories_created": counters.get("events.MemoryCreated", 0),
        "memories_updated": counters.get("events.MemoryUpdated", 0),
        "memories_deleted": counters.get("events.MemoryDeleted", 0),
        "embeddings_generated": counters.get("events.EmbeddingGenerated", 0),
        "graph_updates": counters.get("events.GraphUpdated", 0),
        "pipeline_latency": latency.get("pipeline", {}),
    }


@router.get("/v1/metrics/workers")
def worker_health(g: Guard = Depends(guard)):
    """Workflow and agent run health summary (queue-depth proxy)."""
    snap = observability.snapshot()
    counters = snap["counters"]
    latency = snap["latency"]

    # Count pending/running workflow runs
    running_workflows = g.db.execute(
        select(func.count(WorkflowRun.id)).where(WorkflowRun.status == "running")
    ).scalar_one()
    running_agents = g.db.execute(
        select(func.count(AgentRun.id)).where(AgentRun.status == "running")
    ).scalar_one()

    return {
        "workflows": {
            "running": running_workflows,
            "ok": counters.get("workflows.ok", 0),
            "failed": counters.get("workflows.failed", 0),
            "avg_latency_ms": latency.get("workflow", {}).get("avg_ms", 0),
        },
        "agents": {
            "running": running_agents,
            "total_runs": counters.get("agents.runs", 0),
            "avg_latency_ms": latency.get("agent_run", {}).get("avg_ms", 0),
        },
        "tools": {
            k.replace("tools.", ""): v
            for k, v in counters.items()
            if k.startswith("tools.")
        },
        "events": {
            k.replace("events.", ""): v
            for k, v in counters.items()
            if k.startswith("events.")
        },
    }
