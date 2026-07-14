"""Digital Twin, Knowledge Evolution, and Evaluation API router.

Endpoints
---------
GET  /v1/workspaces/{ws}/digital-twin              — Get current twin
POST /v1/workspaces/{ws}/digital-twin/refresh      — Force recompute

GET  /v1/workspaces/{ws}/evolution/log             — Recent evolution actions
POST /v1/workspaces/{ws}/evolution/run             — Run full evolution pass
POST /v1/workspaces/{ws}/evolution/decay           — Apply decay only
POST /v1/workspaces/{ws}/evolution/merge-duplicates
POST /v1/workspaces/{ws}/evolution/improve-summaries
POST /v1/workspaces/{ws}/evolution/detect-contradictions
POST /v1/workspaces/{ws}/evolution/generate-insights

GET  /v1/workspaces/{ws}/evaluation/reports        — List evaluation reports
POST /v1/workspaces/{ws}/evaluation/run            — Run evaluation now
GET  /v1/workspaces/{ws}/evaluation/reports/{id}   — Get single report
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select

from .. import digital_twin, evaluation, knowledge_evolution
from ..models_platform import EvaluationReport, EvolutionLog
from ..security import Guard, audit, guard

router = APIRouter(prefix="/v1", tags=["intelligence"])


# ---------------------------------------------------------------------------
# Digital Twin
# ---------------------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/digital-twin")
def get_digital_twin(workspace_id: str, g: Guard = Depends(guard)):
    """Return the current Digital Twin profile for a workspace."""
    twin = digital_twin.get_or_create(g.db, workspace_id)
    g.db.commit()
    return _twin_out(twin)


@router.post("/workspaces/{workspace_id}/digital-twin/refresh")
def refresh_digital_twin(workspace_id: str, g: Guard = Depends(guard)):
    """Force a full recompute of the Digital Twin."""
    twin = digital_twin.refresh(g.db, workspace_id)
    audit(g.db, actor=g.actor, action="digital_twin.refresh", workspace_id=workspace_id)
    g.db.commit()
    return _twin_out(twin)


# ---------------------------------------------------------------------------
# Knowledge Evolution
# ---------------------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/evolution/log")
def get_evolution_log(
    workspace_id: str,
    g: Guard = Depends(guard),
    action: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    stmt = (
        select(EvolutionLog)
        .where(EvolutionLog.workspace_id == workspace_id)
        .order_by(desc(EvolutionLog.created_at))
    )
    if action:
        stmt = stmt.where(EvolutionLog.action == action)
    stmt = stmt.limit(limit).offset(offset)
    rows = g.db.execute(stmt).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "action": r.action,
                "memory_id": r.memory_id,
                "target_memory_id": r.target_memory_id,
                "detail": r.detail,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.post("/workspaces/{workspace_id}/evolution/run")
def run_evolution(workspace_id: str, g: Guard = Depends(guard)):
    """Run a full knowledge evolution pass (decay + merge + summaries + insights)."""
    result = knowledge_evolution.run_full_evolution(g.db, workspace_id)
    audit(g.db, actor=g.actor, action="evolution.full", workspace_id=workspace_id)
    g.db.commit()
    return result


@router.post("/workspaces/{workspace_id}/evolution/decay")
def apply_decay(workspace_id: str, g: Guard = Depends(guard)):
    n = knowledge_evolution.apply_decay(g.db, workspace_id)
    g.db.commit()
    return {"decayed": n}


@router.post("/workspaces/{workspace_id}/evolution/merge-duplicates")
def merge_duplicates(
    workspace_id: str,
    g: Guard = Depends(guard),
    dry_run: bool = Query(default=False),
):
    results = knowledge_evolution.merge_duplicates(g.db, workspace_id, dry_run=dry_run)
    if not dry_run:
        g.db.commit()
    return {"dry_run": dry_run, "merged": len(results), "pairs": results}


@router.post("/workspaces/{workspace_id}/evolution/improve-summaries")
def improve_summaries(workspace_id: str, g: Guard = Depends(guard)):
    n = knowledge_evolution.improve_summaries(g.db, workspace_id)
    g.db.commit()
    return {"improved": n}


@router.post("/workspaces/{workspace_id}/evolution/detect-contradictions")
def detect_contradictions(workspace_id: str, g: Guard = Depends(guard)):
    pairs = knowledge_evolution.detect_contradictions(g.db, workspace_id)
    g.db.commit()
    return {"flagged": len(pairs), "pairs": pairs}


@router.post("/workspaces/{workspace_id}/evolution/generate-insights")
def generate_insights(
    workspace_id: str,
    g: Guard = Depends(guard),
    max_insights: int = Query(default=5, ge=1, le=20),
):
    insights = knowledge_evolution.generate_insights(
        g.db, workspace_id, max_insights=max_insights
    )
    g.db.commit()
    return {"created": len(insights), "insights": insights}


# ---------------------------------------------------------------------------
# AI Evaluation
# ---------------------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/evaluation/reports")
def list_reports(
    workspace_id: str,
    g: Guard = Depends(guard),
    limit: int = Query(default=10, ge=1, le=50),
):
    reports = evaluation.list_reports(g.db, workspace_id, limit=limit)
    return {"items": [_report_out(r) for r in reports]}


@router.post("/workspaces/{workspace_id}/evaluation/run", status_code=201)
def run_evaluation(workspace_id: str, g: Guard = Depends(guard)):
    """Run an on-demand evaluation and persist the report."""
    report = evaluation.run_evaluation(g.db, workspace_id)
    audit(g.db, actor=g.actor, action="evaluation.run", workspace_id=workspace_id)
    g.db.commit()
    return _report_out(report)


@router.get("/workspaces/{workspace_id}/evaluation/reports/{report_id}")
def get_report(workspace_id: str, report_id: str, g: Guard = Depends(guard)):
    report = g.db.get(EvaluationReport, report_id)
    if report is None or report.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="report not found")
    return _report_out(report, include_samples=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _twin_out(twin) -> dict:
    return {
        "workspace_id": twin.workspace_id,
        "skills": twin.skills,
        "style": twin.style,
        "favorite_tools": twin.favorite_tools,
        "predictions": twin.predictions,
        "gaps": twin.gaps,
        "productivity": twin.productivity,
        "decision_summary": twin.decision_summary,
        "memory_count_at_last_update": twin.memory_count_at_last_update,
        "updated_at": twin.updated_at,
    }


def _report_out(r: EvaluationReport, *, include_samples: bool = False) -> dict:
    out = {
        "id": r.id,
        "workspace_id": r.workspace_id,
        "period_start": r.period_start,
        "period_end": r.period_end,
        "retrieval_quality": r.retrieval_quality,
        "hallucination_rate": r.hallucination_rate,
        "grounding_accuracy": r.grounding_accuracy,
        "citation_accuracy": r.citation_accuracy,
        "avg_latency_ms": r.avg_latency_ms,
        "ranking_ndcg": r.ranking_ndcg,
        "agent_success_rate": r.agent_success_rate,
        "summary": r.summary,
        "created_at": r.created_at,
    }
    if include_samples:
        out["samples"] = r.samples
    return out
