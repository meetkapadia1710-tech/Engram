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
    from .db import get_memory_store
    store = get_memory_store(db)
    items = store.list(workspace_id, limit=max_nodes*2, offset=0)
    memories = {m.id: m for m in items}
    
    nodes = []
    edges = []
    entities_map = {}
    
    for m in items:
        # Build memory nodes
        nodes.append({
            "id": m.id, "kind": "memory", "label": m.title or m.content[:40],
            "type": m.type, "importance": m.importance,
            "created_at": m.created_at, "degree": len(m.entity_links)
        })
        
        # Build entity nodes and links
        for l in m.entity_links:
            ent = l.entity
            if ent.id not in entities_map:
                entities_map[ent.id] = {
                    "id": ent.id, "kind": "entity", "label": ent.name,
                    "type": ent.kind, "mentions": 1,
                    "degree": 1
                }
            else:
                entities_map[ent.id]["mentions"] += 1
                entities_map[ent.id]["degree"] += 1
                
            edges.append({
                "source": m.id, "target": ent.id, "kind": "mentions", "weight": 0.3
            })
            
    nodes.extend(entities_map.values())
    
    return {"nodes": nodes[:max_nodes*2], "edges": edges}


def find_related(db: Session, memory_id: str, limit: int = 8) -> list[dict]:
    """Find related memories via Supermemory search."""
    from .db import get_memory_store
    store = get_memory_store(db)
    # Get the memory
    m = store.get(None, memory_id)
    if not m:
        return []
        
    # Search for similar content
    q = m.title if m.title else m.content[:100]
    results = store.search(m.workspace_id, q, limit=limit+1)
    
    out = []
    for r in results:
        if r.id == memory_id:
            continue
        out.append({
            "id": r.id, "title": r.title, "type": r.type,
            "kind": "related_to", "weight": 0.8, "summary": r.summary or r.content[:160],
        })
    return out[:limit]
