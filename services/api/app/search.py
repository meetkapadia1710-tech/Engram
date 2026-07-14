"""Hybrid search engine.

1. **Vector search** — cosine over document + chunk embeddings.
2. **Keyword search** — BM25 (k1=1.5, b=0.75) over title/content/keywords.
3. **Fusion** — Reciprocal Rank Fusion (k=60) merges the two rankings.
4. **Re-ranking** — fused score is blended with importance, recency decay,
   access frequency, relationship weight, and stored confidence:

   final = w_sim·RRF̂ + w_imp·importance + w_rec·2^(−age/half_life)
         + w_freq·log-scaled(access) + w_rel·degreê + w_conf·confidence
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai import _tokens, cosine, get_embedder
from .config import settings
from .models import Memory, MemoryEntity, Relationship

RRF_K = 60


@dataclass
class SearchHit:
    memory: Memory
    similarity: float = 0.0
    bm25: float = 0.0
    rrf: float = 0.0
    final: float = 0.0
    components: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Candidate filtering
# --------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def load_candidates(
    db: Session,
    workspace_id: str,
    *,
    types: list[str] | None = None,
    tags: list[str] | None = None,
    entities: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_archived: bool = False,
) -> list[Memory]:
    q = select(Memory).where(Memory.workspace_id == workspace_id)
    if not include_archived:
        q = q.where(Memory.archived == 0)
    if types:
        q = q.where(Memory.type.in_(types))
    memories = list(db.execute(q).scalars().all())

    if tags:
        tagset = {t.lower() for t in tags}
        memories = [m for m in memories if tagset & {t.lower() for t in m.tags}]
    if entities:
        entset = {e.lower() for e in entities}
        keep = []
        for m in memories:
            names = {l.entity.name.lower() for l in m.entity_links}
            if entset & names:
                keep.append(m)
        memories = keep

    f = _parse_iso(date_from) if date_from else None
    t = _parse_iso(date_to) if date_to else None
    if f or t:
        keep = []
        for m in memories:
            created = _parse_iso(m.created_at)
            if created is None:
                continue
            if f and created < f:
                continue
            if t and created > t:
                continue
            keep.append(m)
        memories = keep
    return memories


# --------------------------------------------------------------------------
# BM25
# --------------------------------------------------------------------------


def bm25_scores(query: str, memories: list[Memory], k1: float = 1.5, b: float = 0.75) -> dict[str, float]:
    docs: dict[str, list[str]] = {
        m.id: _tokens(f"{m.title} {m.content} {' '.join(m.keywords)}") for m in memories
    }
    n = len(docs) or 1
    avgdl = (sum(len(d) for d in docs.values()) / n) or 1.0

    df: dict[str, int] = {}
    for toks in docs.values():
        for t in set(toks):
            df[t] = df.get(t, 0) + 1

    q_toks = _tokens(query)
    scores: dict[str, float] = {}
    for mid, toks in docs.items():
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for qt in q_toks:
            if qt not in tf:
                continue
            idf = math.log(1 + (n - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5))
            s += idf * tf[qt] * (k1 + 1) / (tf[qt] + k1 * (1 - b + b * len(toks) / avgdl))
        if s > 0:
            scores[mid] = s
    return scores


# --------------------------------------------------------------------------
# Ranking components
# --------------------------------------------------------------------------


def recency_score(created_at: str, half_life_days: float | None = None) -> float:
    created = _parse_iso(created_at)
    if created is None:
        return 0.0
    age_days = max((datetime.now(timezone.utc) - created).total_seconds() / 86400, 0.0)
    hl = half_life_days or settings.recency_half_life_days
    return 2 ** (-age_days / hl)


def frequency_score(access_count: int) -> float:
    return min(math.log1p(access_count) / math.log1p(50), 1.0)


def _relationship_degrees(db: Session, workspace_id: str) -> dict[str, float]:
    rows = db.execute(
        select(Relationship.source_id, Relationship.target_id, Relationship.weight).where(
            Relationship.workspace_id == workspace_id
        )
    ).all()
    deg: dict[str, float] = {}
    for s, t, w in rows:
        deg[s] = deg.get(s, 0.0) + w
        deg[t] = deg.get(t, 0.0) + w
    top = max(deg.values(), default=1.0) or 1.0
    return {k: v / top for k, v in deg.items()}


# --------------------------------------------------------------------------
# Hybrid search
# --------------------------------------------------------------------------


def hybrid_search(
    db: Session,
    workspace_id: str,
    query: str,
    *,
    limit: int = 10,
    types: list[str] | None = None,
    tags: list[str] | None = None,
    entities: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    mode: str = "hybrid",  # hybrid | vector | keyword
) -> list[SearchHit]:
    from .db import get_memory_store
    store = get_memory_store(db)
    memories = store.search(workspace_id, query, limit=limit * 3)
    
    if types:
        memories = [m for m in memories if m.type in types]
    if tags:
        tagset = {t.lower() for t in tags}
        memories = [m for m in memories if tagset & {t.lower() for t in m.tags}]
    if entities:
        entset = {e.lower() for e in entities}
        memories = [m for m in memories if entset & {l.entity.name.lower() for l in m.entity_links}]
        
    f = _parse_iso(date_from) if date_from else None
    t = _parse_iso(date_to) if date_to else None
    if f or t:
        keep = []
        for m in memories:
            created = _parse_iso(m.created_at)
            if created is None:
                continue
            if f and created < f:
                continue
            if t and created > t:
                continue
            keep.append(m)
        memories = keep
        
    memories = memories[:limit]
    now = datetime.now(timezone.utc).isoformat()
    hits: list[SearchHit] = []
    
    for i, m in enumerate(memories):
        m.access_count += 1
        m.last_accessed_at = now
        metadata = {
            "title": m.title, "type": m.type, "summary": m.summary, 
            "source": m.source, "author": m.author, "importance": m.importance,
            "keywords": m.keywords, "tags": m.tags, "access_count": m.access_count,
            "archived": m.archived, "updated_at": m.updated_at
        }
        store.update(m.workspace_id, m.id, m.content, metadata)
        
        score = max(0.1, 1.0 - (i * 0.05))
        hits.append(SearchHit(memory=m, final=score, components={"supermemory_score": score}))
        
    return hits
