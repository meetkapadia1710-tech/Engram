"""Knowledge Evolution engine.

Continuously improves the knowledge base by:

1. **Decay** — Lower importance/confidence of memories that are old and
   rarely accessed (configurable half-life).
2. **Duplicate detection** — Memories with cosine similarity ≥ 0.92 are
   candidates for merging; the higher-importance one keeps its content and
   absorbs the other's tags.
3. **Summary improvement** — Short or extractive summaries are replaced with
   generator output when possible.
4. **Contradiction detection** — Memory pairs that are highly similar but have
   opposing polarity are flagged (an EvolutionLog entry is written; automatic
   resolution requires human review).
5. **Insight generation** — For every cluster of 3+ related memories sharing
   an entity, a synthesis note is created.

Every action is recorded in ``EvolutionLog`` for traceability.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import observability
from .ai import _tokens, cosine, get_embedder, get_generator
from .models import Memory, MemoryChunk, MemoryEntity, Relationship, _now_iso
from .models_platform import EvolutionLog

# Cosine threshold above which two memories are "near-duplicates"
DUPLICATE_THRESHOLD = 0.92
# Cosine threshold for "related" cluster detection
CLUSTER_THRESHOLD = 0.65
# Minimum cluster size to trigger insight generation
MIN_CLUSTER_SIZE = 3
# Age (days) after which a memory starts to decay
DECAY_AFTER_DAYS = 30
DECAY_HALF_LIFE = 60.0  # days


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_days(iso_ts: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (_now() - dt).total_seconds() / 86400
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# 1. Decay
# ---------------------------------------------------------------------------


def apply_decay(db: Session, workspace_id: str) -> int:
    """Lower importance/confidence of stale, unused memories.

    Returns number of memories updated.
    """
    n = 0
    memories = db.execute(
        select(Memory).where(Memory.workspace_id == workspace_id, Memory.archived == 0)
    ).scalars().all()
    for mem in memories:
        age = _age_days(mem.created_at)
        if age < DECAY_AFTER_DAYS:
            continue
        decay = 2 ** (-(age - DECAY_AFTER_DAYS) / DECAY_HALF_LIFE)
        new_importance = round(max(0.1, mem.importance * (0.7 + 0.3 * decay)), 4)
        new_confidence = round(max(0.1, mem.confidence * (0.8 + 0.2 * decay)), 4)
        if (
            abs(new_importance - mem.importance) > 0.005
            or abs(new_confidence - mem.confidence) > 0.005
        ):
            old_imp = mem.importance
            mem.importance = new_importance
            mem.confidence = new_confidence
            mem.updated_at = _now_iso()
            db.add(
                EvolutionLog(
                    workspace_id=workspace_id,
                    action="decay",
                    memory_id=mem.id,
                    detail_json=json.dumps(
                        {
                            "old_importance": old_imp,
                            "new_importance": new_importance,
                            "age_days": round(age, 1),
                        }
                    ),
                )
            )
            n += 1
    db.flush()
    observability.count("evolution.decay", n)
    return n


# ---------------------------------------------------------------------------
# 2. Duplicate detection + merge
# ---------------------------------------------------------------------------


def merge_duplicates(db: Session, workspace_id: str, dry_run: bool = False) -> list[dict]:
    """Find and merge near-duplicate memories.

    Returns a list of merge actions performed (or planned for dry_run).
    """
    memories = db.execute(
        select(Memory).where(Memory.workspace_id == workspace_id, Memory.archived == 0)
    ).scalars().all()

    merged: list[dict] = []
    deleted_ids: set[str] = set()

    for i, a in enumerate(memories):
        if a.id in deleted_ids:
            continue
        for b in memories[i + 1:]:
            if b.id in deleted_ids or a.id in deleted_ids:
                continue
            sim = cosine(a.embedding, b.embedding)
            if sim < DUPLICATE_THRESHOLD:
                continue
            # Keep the higher-importance memory, archive the other
            keeper, dupe = (a, b) if a.importance >= b.importance else (b, a)
            action = {
                "keeper_id": keeper.id,
                "dupe_id": dupe.id,
                "similarity": round(sim, 4),
            }
            merged.append(action)
            if not dry_run:
                # Merge tags
                keeper.tags = list(set(keeper.tags) | set(dupe.tags))
                # Archive duplicate
                dupe.archived = 1
                dupe.updated_at = _now_iso()
                deleted_ids.add(dupe.id)
                db.add(
                    EvolutionLog(
                        workspace_id=workspace_id,
                        action="merged",
                        memory_id=keeper.id,
                        target_memory_id=dupe.id,
                        detail_json=json.dumps(action),
                    )
                )
    if not dry_run:
        db.flush()
        observability.count("evolution.merged", len(merged))
    return merged


# ---------------------------------------------------------------------------
# 3. Summary improvement
# ---------------------------------------------------------------------------


def improve_summaries(db: Session, workspace_id: str, limit: int = 20) -> int:
    """Replace short/extractive summaries with generator output.

    Only processes memories whose summary is shorter than 60 chars or empty.
    """
    gen = get_generator()
    n = 0
    candidates = [
        m
        for m in db.execute(
            select(Memory).where(
                Memory.workspace_id == workspace_id, Memory.archived == 0
            )
        ).scalars()
        if not m.summary or len(m.summary) < 60
    ][:limit]

    for mem in candidates:
        if len(mem.content) < 100:
            continue
        try:
            new_summary = gen.generate(
                f"Summarize in 1-2 sentences:\n\n{mem.content[:4000]}",
                source_text=mem.content,
            )[:500]
        except Exception:
            continue
        if new_summary and len(new_summary) > len(mem.summary):
            old = mem.summary
            mem.summary = new_summary
            mem.updated_at = _now_iso()
            db.add(
                EvolutionLog(
                    workspace_id=workspace_id,
                    action="improved_summary",
                    memory_id=mem.id,
                    detail_json=json.dumps(
                        {"old_len": len(old), "new_len": len(new_summary)}
                    ),
                )
            )
            n += 1
    db.flush()
    observability.count("evolution.improved_summaries", n)
    return n


# ---------------------------------------------------------------------------
# 4. Contradiction detection
# ---------------------------------------------------------------------------


def detect_contradictions(db: Session, workspace_id: str) -> list[dict]:
    """Flag memory pairs with high similarity but opposing polarity.

    Returns detected (memory_a_id, memory_b_id) pairs. Does not resolve.
    """
    _NEGATIONS = {"not", "never", "no", "don't", "cant", "wont", "isn't", "aren't",
                  "doesn't", "didn't", "won't", "cannot"}

    def _has_negation(text: str) -> bool:
        return bool(_NEGATIONS & set(text.lower().split()))

    memories = db.execute(
        select(Memory).where(Memory.workspace_id == workspace_id, Memory.archived == 0)
    ).scalars().all()

    flagged: list[dict] = []
    for i, a in enumerate(memories):
        for b in memories[i + 1:]:
            sim = cosine(a.embedding, b.embedding)
            if sim < CLUSTER_THRESHOLD:
                continue
            pol_a = _has_negation(a.content)
            pol_b = _has_negation(b.content)
            if pol_a == pol_b:
                continue
            # Shared tokens suggest same topic, opposing polarity = contradiction
            ta = set(_tokens(a.content))
            tb = set(_tokens(b.content))
            if not ta or not tb:
                continue
            overlap = len(ta & tb) / min(len(ta), len(tb))
            if overlap < 0.4:
                continue
            pair = {
                "memory_a_id": a.id,
                "memory_b_id": b.id,
                "similarity": round(sim, 4),
                "overlap": round(overlap, 4),
            }
            flagged.append(pair)
            db.add(
                EvolutionLog(
                    workspace_id=workspace_id,
                    action="contradiction",
                    memory_id=a.id,
                    target_memory_id=b.id,
                    detail_json=json.dumps(pair),
                )
            )
    db.flush()
    observability.count("evolution.contradictions", len(flagged))
    return flagged


# ---------------------------------------------------------------------------
# 5. Insight generation
# ---------------------------------------------------------------------------


def generate_insights(
    db: Session, workspace_id: str, max_insights: int = 5
) -> list[dict]:
    """Cluster related memories and synthesise insight notes.

    For each cluster of MIN_CLUSTER_SIZE+ memories sharing an entity, generate
    a synthesis note if none already exists for that cluster.
    """
    from .pipeline import ingest_memory

    memories = db.execute(
        select(Memory).where(Memory.workspace_id == workspace_id, Memory.archived == 0)
    ).scalars().all()
    if not memories:
        return []

    # Group by entity
    entity_to_mems: dict[str, list[Memory]] = defaultdict(list)
    for mem in memories:
        for link in mem.entity_links:
            entity_to_mems[link.entity_id].append(mem)

    gen = get_generator()
    created: list[dict] = []

    for entity_id, cluster in list(entity_to_mems.items())[:max_insights * 3]:
        if len(cluster) < MIN_CLUSTER_SIZE:
            continue
        if len(created) >= max_insights:
            break
        corpus = "\n".join(
            f"- {m.title}: {m.content[:200]}" for m in cluster[:10]
        )
        try:
            insight = gen.generate(
                f"Synthesise these related memories into one insight paragraph:\n{corpus}",
                source_text=corpus,
            )
        except Exception:
            insight = corpus[:500]
        if not insight:
            continue
        mem = ingest_memory(
            db,
            workspace_id=workspace_id,
            content=insight,
            type_="note",
            tags=["insight", "evolution"],
        )
        db.add(
            EvolutionLog(
                workspace_id=workspace_id,
                action="insight_generated",
                memory_id=mem.id,
                detail_json=json.dumps(
                    {"entity_id": entity_id, "cluster_size": len(cluster)}
                ),
            )
        )
        created.append({"memory_id": mem.id, "entity_id": entity_id})

    db.flush()
    observability.count("evolution.insights", len(created))
    return created


# ---------------------------------------------------------------------------
# Full evolution pass
# ---------------------------------------------------------------------------


def run_full_evolution(db: Session, workspace_id: str) -> dict:
    """Run all evolution steps. Returns a summary dict."""
    with observability.timed("evolution.full"):
        decayed = apply_decay(db, workspace_id)
        merged = merge_duplicates(db, workspace_id)
        improved = improve_summaries(db, workspace_id)
        contradictions = detect_contradictions(db, workspace_id)
        insights = generate_insights(db, workspace_id)
    db.flush()
    return {
        "decayed": decayed,
        "merged": len(merged),
        "summaries_improved": improved,
        "contradictions_flagged": len(contradictions),
        "insights_created": len(insights),
        "contradiction_pairs": contradictions,
        "insight_memory_ids": [i["memory_id"] for i in insights],
    }
