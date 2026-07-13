"""Knowledge-graph assembly and traversal.

Nodes: memories + entities. Edges: memory→memory typed relationships and
memory→entity mentions. Served as JSON for the frontend force-graph and for
`find_related` (1..n-hop neighborhood expansion).
"""

from __future__ import annotations

from collections import deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Entity, Memory, MemoryEntity, Relationship


def build_graph(
    db: Session,
    workspace_id: str,
    *,
    center_id: str | None = None,
    hops: int = 2,
    max_nodes: int = 150,
) -> dict:
    memories = {
        m.id: m
        for m in db.execute(
            select(Memory).where(
                Memory.workspace_id == workspace_id, Memory.archived == 0
            )
        ).scalars()
    }
    rels = list(
        db.execute(
            select(Relationship).where(Relationship.workspace_id == workspace_id)
        ).scalars()
    )
    links = list(
        db.execute(
            select(MemoryEntity)
            .join(Memory, MemoryEntity.memory_id == Memory.id)
            .where(Memory.workspace_id == workspace_id)
        ).scalars()
    )
    entities = {
        e.id: e
        for e in db.execute(
            select(Entity).where(Entity.workspace_id == workspace_id)
        ).scalars()
    }

    # adjacency over memory+entity node ids
    adj: dict[str, set[str]] = {}

    def _connect(a: str, b: str) -> None:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    for r in rels:
        _connect(r.source_id, r.target_id)
    for l in links:
        _connect(l.memory_id, l.entity_id)

    keep: set[str] = set()
    if center_id and center_id in adj or center_id in memories:
        frontier = deque([(center_id, 0)])
        seen = {center_id}
        while frontier and len(keep) < max_nodes:
            node, d = frontier.popleft()
            keep.add(node)
            if d >= hops:
                continue
            for nxt in adj.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append((nxt, d + 1))
    else:
        # whole-workspace view, capped by connectivity
        ranked = sorted(adj.items(), key=lambda kv: len(kv[1]), reverse=True)
        keep = {k for k, _ in ranked[:max_nodes]}
        keep |= set(list(memories.keys())[: max(0, max_nodes - len(keep))])

    nodes = []
    for mid in keep:
        if mid in memories:
            m = memories[mid]
            nodes.append({
                "id": m.id, "kind": "memory", "label": m.title or m.content[:40],
                "type": m.type, "importance": m.importance,
                "created_at": m.created_at, "degree": len(adj.get(m.id, ())),
            })
        elif mid in entities:
            e = entities[mid]
            nodes.append({
                "id": e.id, "kind": "entity", "label": e.name,
                "type": e.kind, "mentions": e.mention_count,
                "degree": len(adj.get(e.id, ())),
            })

    node_ids = {n["id"] for n in nodes}
    edges = [
        {"source": r.source_id, "target": r.target_id, "kind": r.kind, "weight": r.weight}
        for r in rels
        if r.source_id in node_ids and r.target_id in node_ids
    ] + [
        {"source": l.memory_id, "target": l.entity_id, "kind": "mentions", "weight": 0.3}
        for l in links
        if l.memory_id in node_ids and l.entity_id in node_ids
    ]
    return {"nodes": nodes, "edges": edges}


def find_related(db: Session, memory_id: str, limit: int = 8) -> list[dict]:
    """Directly connected memories, strongest edges first."""
    rows = list(
        db.execute(
            select(Relationship).where(
                (Relationship.source_id == memory_id)
                | (Relationship.target_id == memory_id)
            )
        ).scalars()
    )
    rows.sort(key=lambda r: r.weight, reverse=True)
    out = []
    for r in rows[:limit]:
        other_id = r.target_id if r.source_id == memory_id else r.source_id
        other = db.get(Memory, other_id)
        if other is None or other.archived:
            continue
        out.append({
            "id": other.id, "title": other.title, "type": other.type,
            "kind": r.kind, "weight": r.weight, "summary": other.summary or other.content[:160],
        })
    return out
