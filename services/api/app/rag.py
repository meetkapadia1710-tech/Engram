"""RAG context builder.

Turns a question into a token-budgeted, citation-annotated context block ready
to paste into any LLM prompt. Sources are numbered [1]..[n] and returned
alongside the block so the caller can render attributions and prevent
hallucinated citations (the model can only cite what we handed it).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .search import hybrid_search

CHARS_PER_TOKEN = 4  # conservative heuristic


def build_context(
    db: Session,
    workspace_id: str,
    query: str,
    *,
    max_tokens: int = 1800,
    limit: int = 12,
    types: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    hits = hybrid_search(
        db, workspace_id, query,
        limit=limit, types=types, date_from=date_from, date_to=date_to,
    )
    budget = max_tokens * CHARS_PER_TOKEN
    parts: list[str] = []
    sources: list[dict] = []

    for i, hit in enumerate(hits, start=1):
        m = hit.memory
        body = m.summary if (m.summary and len(m.content) > 800) else m.content
        entry = f"[{i}] ({m.type}, {m.created_at[:10]}) {m.title}\n{body}".strip()
        if sum(len(p) for p in parts) + len(entry) > budget:
            remaining = budget - sum(len(p) for p in parts)
            if remaining < 200:
                break
            entry = entry[:remaining] + "…"
        parts.append(entry)
        sources.append({
            "n": i, "id": m.id, "title": m.title, "type": m.type,
            "created_at": m.created_at, "score": hit.final,
        })
        if sum(len(p) for p in parts) >= budget:
            break

    context_block = (
        "You are answering using the user's long-term memory. "
        "Cite sources as [n]. If the memories do not contain the answer, say so "
        "instead of guessing.\n\n--- MEMORIES ---\n\n" + "\n\n".join(parts)
    )
    return {
        "query": query,
        "context": context_block,
        "sources": sources,
        "approx_tokens": len(context_block) // CHARS_PER_TOKEN,
    }
