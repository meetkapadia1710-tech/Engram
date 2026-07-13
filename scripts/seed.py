"""Seed Engram with a realistic demo workspace.

    python scripts/seed.py [--base http://localhost:8000]

Idempotent-ish: skips seeding if the workspace already has >= 10 memories.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

from engram import Engram  # noqa: E402

MEMORIES: list[tuple[str, str, list[str]]] = [
    ("Docker builds cache each layer; ordering COPY after RUN pip install keeps the dependency layer cached between code changes.", "note", ["devops", "docker"]),
    ("Kubernetes liveness probes restart containers, readiness probes gate traffic. Confusing the two causes rolling-deploy outages.", "note", ["devops", "kubernetes"]),
    ("Team decision: we standardize on PostgreSQL with pgvector for embeddings storage instead of a separate vector database. Simpler ops, one backup story.", "meeting_notes", ["architecture", "decision"]),
    ("HNSW indexes trade memory for speed: ef_construction controls build quality, ef_search controls query recall. Start with m=16.", "research_paper", ["vector-search"]),
    ("Reciprocal Rank Fusion: score(d) = sum over rankers of 1/(k + rank_r(d)), k=60. Robust because it ignores raw score scales entirely.", "research_paper", ["search", "ranking"]),
    ("BM25 saturates term frequency with k1 (usually 1.2-2.0) and normalizes by document length with b (usually 0.75).", "note", ["search"]),
    ("Sarah Chen suggested we expose the ranking components in the API response so the UI can explain WHY a memory surfaced. Shipped in v0.1.", "conversation", ["product", "explainability"]),
    ("def cosine(a, b): return dot(a, b) / (norm(a) * norm(b))  # remember: normalize embeddings once at write time, then dot product is enough", "code", ["python", "embeddings"]),
    ("Bookmarked: 'The Illustrated Transformer' — best visual explanation of attention mechanisms I've found.", "bookmark", ["ml", "reading"]),
    ("TODO: benchmark local embedder vs nomic-embed-text on the recall@10 eval set before the demo.", "task", ["eval"]),
    ("Meeting with the platform team: agreed the memory API stays workspace-scoped; org-level sharing lands in Q3.", "meeting_notes", ["planning"]),
    ("Anthropic's context editing guidance: keep tool results small, summarize aggressively, and let the model re-fetch details on demand.", "website", ["llm", "context"]),
    ("Ollama serves an OpenAI-compatible API on :11434 — /api/embed for embeddings, /api/generate for completions. qwen2.5:3b is a good small default.", "note", ["ollama", "local-llm"]),
    ("Redis sliding-window rate limiting: ZADD timestamp, ZREMRANGEBYSCORE older than window, ZCARD to count. Atomic with a Lua script.", "code", ["redis", "backend"]),
    ("Postgres VACUUM reclaims dead tuples; autovacuum thresholds need lowering on high-churn tables like audit logs.", "note", ["postgres", "database"]),
    ("Insight from user interviews: people don't want to organize memories into folders. They want search that just works and a timeline for browsing.", "document", ["product", "ux"]),
    ("Next.js 15 app router: server components by default, 'use client' only where interactivity lives. Keeps First Load JS around 100kB.", "note", ["nextjs", "frontend"]),
    ("Tailwind v4 theme tokens live in @theme blocks in CSS now — no tailwind.config.js needed for simple design systems.", "note", ["tailwind", "frontend"]),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args()

    em = Engram(args.base)
    stats = em.analytics()
    if stats["memories"] >= 10:
        print(f"workspace already has {stats['memories']} memories — skipping seed")
        return 0

    for i, (content, type_, tags) in enumerate(MEMORIES, 1):
        m = em.create_memory(content, type=type_, tags=tags)
        print(f"[{i:2}/{len(MEMORIES)}] {m.type:<15} {m.title[:60]}")

    stats = em.analytics()
    print(
        f"\nseeded. workspace now has {stats['memories']} memories, "
        f"{stats['entities']} entities, {stats['relationships']} relationships."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
