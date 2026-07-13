"""Ingestion pipeline: raw text → stored, embedded, connected memory.

    raw ─▶ clean ─▶ chunk ─▶ embed ─▶ keywords ─▶ entities ─▶ relationships

Entity extraction is heuristic by design (capitalized spans, a curated
technology lexicon, emails/URLs) so it is fast, deterministic, and free; a
generation provider, when configured, only improves summaries/titles — the
pipeline never *depends* on an LLM.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai import _raw_tokens, _tokens, cosine, get_embedder, get_generator
from .models import Entity, Memory, MemoryChunk, MemoryEntity, Relationship

# --------------------------------------------------------------------------
# Cleaning & chunking
# --------------------------------------------------------------------------


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    """Paragraph-aware sliding-window chunking."""
    if len(text) <= max_chars:
        return [text] if text else []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = f"{buf}\n\n{p}" if buf else p
            continue
        if buf:
            chunks.append(buf)
        # paragraph itself too big → hard-split with overlap
        while len(p) > max_chars:
            chunks.append(p[:max_chars])
            p = p[max_chars - overlap :]
        buf = p
    if buf:
        chunks.append(buf)
    return chunks


# --------------------------------------------------------------------------
# Keywords & entities
# --------------------------------------------------------------------------

TECH_LEXICON = {
    "docker", "kubernetes", "terraform", "postgres", "postgresql", "redis",
    "neo4j", "python", "typescript", "javascript", "react", "nextjs", "fastapi",
    "nestjs", "tailwind", "sqlite", "pgvector", "ollama", "openai", "anthropic",
    "claude", "gemini", "gpt", "llm", "rag", "embedding", "embeddings", "vector",
    "graphql", "rest", "websocket", "oauth", "jwt", "github", "linux", "windows",
    "macos", "aws", "azure", "gcp", "vercel", "node", "rust", "golang", "java",
    "sql", "nosql", "grafana", "prometheus", "sentry", "opentelemetry", "bm25",
    "hnsw", "transformer", "pytorch", "tensorflow", "numpy", "pandas", "api",
}

_CAP_SPAN = re.compile(r"\b([A-Z][a-zA-Z0-9+.#-]*(?:\s+[A-Z][a-zA-Z0-9+.#-]*){0,3})\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_URL = re.compile(r"https?://[^\s)>\]]+")

_ENTITY_KIND_HINTS = {
    "person": {"mr", "ms", "dr", "prof"},
    "organization": {"inc", "corp", "ltd", "labs", "university", "team"},
}


def extract_keywords(text: str, top_k: int = 8) -> list[str]:
    # unstemmed: keywords are shown in the UI, so keep the surface form
    counts = Counter(t for t in _raw_tokens(text) if len(t) > 2)
    return [w for w, _ in counts.most_common(top_k)]


def extract_entities(text: str) -> list[tuple[str, str]]:
    """Return (name, kind) pairs. Deterministic heuristics, deduplicated."""
    found: dict[str, str] = {}

    # raw tokens: lexicon entries are surface forms ("postgres", not "postgre")
    for tok in _raw_tokens(text):
        if tok in TECH_LEXICON:
            found.setdefault(tok, "technology")

    for m in _CAP_SPAN.finditer(text):
        name = m.group(1).strip()
        words = name.split()
        # skip sentence-initial single common words
        if len(words) == 1 and m.start() == 0:
            continue
        if name.lower() in _tokens(name.lower()) and len(words) == 1 and len(name) < 3:
            continue
        low = name.lower()
        if low in TECH_LEXICON:
            found.setdefault(low, "technology")
            continue
        kind = "concept"
        tail = words[-1].lower().strip(".")
        if tail in _ENTITY_KIND_HINTS["organization"]:
            kind = "organization"
        elif len(words) == 2 and all(w[0].isupper() and w[1:].islower() for w in words):
            kind = "person"
        found.setdefault(name, kind)

    for m in _EMAIL.finditer(text):
        found.setdefault(m.group(0).lower(), "email")
    for m in _URL.finditer(text):
        found.setdefault(m.group(0), "url")

    return list(found.items())[:24]


def score_importance(text: str, type_: str) -> float:
    """Length- and signal-based prior in [0.2, 0.95]."""
    base = {
        "conversation": 0.45, "document": 0.6, "research_paper": 0.7,
        "meeting_notes": 0.65, "task": 0.6, "code": 0.55, "note": 0.5,
    }.get(type_, 0.5)
    length_bonus = min(len(text) / 4000, 0.2)
    signal = 0.1 if any(k in text.lower() for k in ("decision", "important", "deadline", "must")) else 0.0
    return round(min(0.95, max(0.2, base + length_bonus + signal)), 3)


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_or_create_entity(db: Session, workspace_id: str, name: str, kind: str) -> Entity:
    ent = db.execute(
        select(Entity).where(Entity.workspace_id == workspace_id, Entity.name == name)
    ).scalar_one_or_none()
    if ent is None:
        ent = Entity(workspace_id=workspace_id, name=name, kind=kind)
        db.add(ent)
        db.flush()
    ent.mention_count += 1
    return ent


def detect_relationships(
    db: Session, memory: Memory, max_links: int = 6
) -> list[Relationship]:
    """Connect a new memory to existing ones.

    * cosine ≥ 0.92 → duplicate_of
    * cosine ≥ 0.55 → related_to (weight = similarity)
    * ≥ 1 shared entity with some semantic overlap → mentions edge (Jaccard-weighted)
    """
    own_vec = memory.embedding
    own_entities = {l.entity_id for l in memory.entity_links}
    created: list[Relationship] = []

    others = (
        db.execute(
            select(Memory)
            .where(Memory.workspace_id == memory.workspace_id)
            .where(Memory.id != memory.id, Memory.archived == 0)
        )
        .scalars()
        .all()
    )
    scored: list[tuple[float, str, Memory]] = []
    for other in others:
        sim = cosine(own_vec, other.embedding)
        other_entities = {l.entity_id for l in other.entity_links}
        shared = own_entities & other_entities
        if sim >= 0.92:
            scored.append((sim, "duplicate_of", other))
        elif sim >= 0.55:
            scored.append((sim, "related_to", other))
        elif shared and (sim >= 0.15 or len(shared) >= 2):
            union = own_entities | other_entities
            jacc = len(shared) / (len(union) or 1)
            scored.append((0.3 + 0.5 * jacc, "mentions", other))

    scored.sort(key=lambda t: t[0], reverse=True)
    for weight, kind, other in scored[:max_links]:
        rel = Relationship(
            workspace_id=memory.workspace_id,
            source_id=memory.id,
            target_id=other.id,
            kind=kind,
            weight=round(min(weight, 1.0), 4),
        )
        db.add(rel)
        created.append(rel)
    return created


def ingest_memory(
    db: Session,
    *,
    workspace_id: str,
    content: str,
    type_: str = "note",
    title: str = "",
    source: str = "",
    author: str = "",
    tags: list[str] | None = None,
) -> Memory:
    """Run the full pipeline and persist one memory. Commits are the caller's job."""
    content = clean_text(content)
    if not content:
        raise ValueError("content is empty after cleaning")

    chunks = chunk_text(content)
    embedder = get_embedder()
    vectors = embedder.embed(chunks + [content[:2000]])
    chunk_vecs, doc_vec = vectors[:-1], vectors[-1]

    keywords = extract_keywords(content)
    if not title:
        first_line = content.split("\n", 1)[0]
        title = (first_line[:80] + "…") if len(first_line) > 80 else first_line
    summary = ""
    if len(content) > 280:
        try:
            gen = get_generator()
            summary = gen.generate(
                f"Summarize in 1-2 sentences:\n\n{content[:4000]}", source_text=content
            )[:500]
        except Exception:
            summary = content[:280]

    memory = Memory(
        workspace_id=workspace_id,
        type=type_,
        title=title,
        content=content,
        summary=summary,
        source=source,
        author=author,
        importance=score_importance(content, type_),
    )
    memory.keywords = keywords
    memory.tags = tags or []
    memory.embedding = doc_vec
    db.add(memory)
    db.flush()

    for i, (chunk, vec) in enumerate(zip(chunks, chunk_vecs)):
        mc = MemoryChunk(memory_id=memory.id, position=i, content=chunk)
        mc.embedding = vec
        db.add(mc)

    for name, kind in extract_entities(content):
        ent = _get_or_create_entity(db, workspace_id, name, kind)
        db.add(MemoryEntity(memory_id=memory.id, entity_id=ent.id))
    db.flush()

    detect_relationships(db, memory)
    db.flush()
    return memory


# --------------------------------------------------------------------------
# Compression (archive old, low-value memories)
# --------------------------------------------------------------------------


def compress_workspace(db: Session, workspace_id: str, older_than_days: int = 90) -> int:
    """Archive stale, rarely-accessed memories; keep embeddings + graph intact."""
    cutoff = datetime.now(timezone.utc).timestamp() - older_than_days * 86400
    n = 0
    for mem in (
        db.execute(
            select(Memory).where(
                Memory.workspace_id == workspace_id, Memory.archived == 0
            )
        )
        .scalars()
        .all()
    ):
        try:
            created = datetime.fromisoformat(mem.created_at).timestamp()
        except ValueError:
            continue
        if created < cutoff and mem.access_count < 2 and mem.importance < 0.6:
            if not mem.summary:
                mem.summary = mem.content[:280]
            mem.archived = 1
            n += 1
    return n
