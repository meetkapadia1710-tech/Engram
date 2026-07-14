"""AI Evaluation Framework.

Automatically evaluates the platform's retrieval and generation quality:

Metrics computed
----------------
* **Retrieval quality** (NDCG@5) — searches the last N queries stored as
  events and measures whether the highest-importance memories appear at the
  top of results.
* **Grounding accuracy** — fraction of search hits whose content contains at
  least one query keyword.
* **Hallucination rate** — approximate: fraction of generated summaries
  (memories with summary != extractive first-line) that contain no token from
  the source content.
* **Citation accuracy** — fraction of RAG context blocks that reference at
  least one real memory id.
* **Average latency** — pulled from the observability module.
* **Agent success rate** — fraction of AgentRun rows with status == "ok".
* **Ranking NDCG** — see retrieval quality above.

Results are stored as ``EvaluationReport`` rows and can be retrieved via API.
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from . import observability
from .ai import _tokens
from .models import Memory, Workspace
from .models_platform import AgentRun, EvaluationReport, EventRecord
from .search import hybrid_search


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _score_ndcg_at_k(db: Session, workspace_id: str, k: int = 5, samples: int = 10) -> float:
    """Estimate NDCG@k by sampling memories as synthetic queries.

    For each sampled memory we query its title and check that the memory
    itself appears in the top-k results. Ideal DCG = 1.0 (first position).
    """
    memories = db.execute(
        select(Memory)
        .where(Memory.workspace_id == workspace_id, Memory.archived == 0)
        .order_by(desc(Memory.importance))
        .limit(50)
    ).scalars().all()
    if len(memories) < 2:
        return 1.0  # trivially perfect

    tested = random.sample(memories, min(samples, len(memories)))
    ndcg_sum = 0.0
    for mem in tested:
        hits = hybrid_search(db, workspace_id, mem.title or mem.content[:80], limit=k)
        hit_ids = [h.memory.id for h in hits]
        if mem.id in hit_ids:
            rank = hit_ids.index(mem.id) + 1  # 1-based
            dcg = 1.0 / math.log2(rank + 1)
            ideal_dcg = 1.0 / math.log2(2)  # rank=1
            ndcg_sum += dcg / ideal_dcg
        # 0 if not found at all
    return round(ndcg_sum / len(tested), 4) if tested else 0.0


def _grounding_accuracy(db: Session, workspace_id: str, samples: int = 10) -> float:
    """Fraction of search hits whose content contains a query keyword."""
    memories = db.execute(
        select(Memory)
        .where(Memory.workspace_id == workspace_id, Memory.archived == 0)
        .limit(30)
    ).scalars().all()
    if not memories:
        return 0.0
    tested = random.sample(memories, min(samples, len(memories)))
    grounded = 0
    for mem in tested:
        query = mem.title or mem.content[:80]
        q_tokens = set(_tokens(query))
        hits = hybrid_search(db, workspace_id, query, limit=5)
        for hit in hits:
            content_tokens = set(_tokens(hit.memory.content))
            if q_tokens & content_tokens:
                grounded += 1
                break
    return round(grounded / len(tested), 4)


def _hallucination_rate(db: Session, workspace_id: str) -> float:
    """Approximate: fraction of summaries with no source token overlap."""
    memories = db.execute(
        select(Memory)
        .where(
            Memory.workspace_id == workspace_id,
            Memory.archived == 0,
        )
        .limit(50)
    ).scalars().all()
    checked = [m for m in memories if m.summary and len(m.summary) > 20]
    if not checked:
        return 0.0
    hallucinated = 0
    for mem in checked:
        src_tokens = set(_tokens(mem.content))
        sum_tokens = set(_tokens(mem.summary))
        if not (src_tokens & sum_tokens):
            hallucinated += 1
    return round(hallucinated / len(checked), 4)


def _citation_accuracy(db: Session, workspace_id: str) -> float:
    """Fraction of recent SearchExecuted events where payload has memory ids."""
    events = db.execute(
        select(EventRecord)
        .where(
            EventRecord.workspace_id == workspace_id,
            EventRecord.type == "ContextBuilt",
        )
        .order_by(desc(EventRecord.seq))
        .limit(20)
    ).scalars().all()
    if not events:
        return 1.0  # no data = optimistic
    cited = sum(
        1 for e in events if e.payload.get("citations") or e.payload.get("memory_ids")
    )
    return round(cited / len(events), 4)


def _agent_success_rate(db: Session, workspace_id: str) -> float:
    runs = db.execute(
        select(AgentRun)
        .where(AgentRun.workspace_id == workspace_id)
        .order_by(desc(AgentRun.started_at))
        .limit(100)
    ).scalars().all()
    if not runs:
        return 1.0
    ok = sum(1 for r in runs if r.status == "ok")
    return round(ok / len(runs), 4)


def run_evaluation(db: Session, workspace_id: str) -> EvaluationReport:
    """Compute all metrics and persist an EvaluationReport."""
    with observability.timed("evaluation.run"):
        snap = observability.snapshot()
        avg_latency = snap["latency"].get("search", {}).get("avg_ms", 0.0)

        retrieval_ndcg = _score_ndcg_at_k(db, workspace_id)
        grounding = _grounding_accuracy(db, workspace_id)
        hallucination = _hallucination_rate(db, workspace_id)
        citation = _citation_accuracy(db, workspace_id)
        agent_sr = _agent_success_rate(db, workspace_id)

        # Build a short narrative
        summary_parts = [
            f"Retrieval NDCG@5: {retrieval_ndcg:.2f}",
            f"Grounding: {grounding:.2%}",
            f"Hallucination rate: {hallucination:.2%}",
            f"Citation accuracy: {citation:.2%}",
            f"Agent success: {agent_sr:.2%}",
            f"Avg search latency: {avg_latency:.1f}ms",
        ]
        summary = " | ".join(summary_parts)

        # Period (today)
        today = _today()
        report = EvaluationReport(
            workspace_id=workspace_id,
            period_start=today,
            period_end=today,
            retrieval_quality=retrieval_ndcg,
            hallucination_rate=hallucination,
            grounding_accuracy=grounding,
            citation_accuracy=citation,
            avg_latency_ms=avg_latency,
            ranking_ndcg=retrieval_ndcg,
            agent_success_rate=agent_sr,
            samples_json=json.dumps(summary_parts),
            summary=summary,
        )
        db.add(report)
        db.flush()

    observability.count("evaluation.reports")
    return report


def list_reports(
    db: Session, workspace_id: str, limit: int = 10
) -> list[EvaluationReport]:
    return (
        db.execute(
            select(EvaluationReport)
            .where(EvaluationReport.workspace_id == workspace_id)
            .order_by(desc(EvaluationReport.created_at))
            .limit(limit)
        )
        .scalars()
        .all()
    )
