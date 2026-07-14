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
    "ai", "ml", "api", "ui", "ux", "db", "sql", "json", "xml", "html", "css",
    "nestjs", "tailwind", "sqlite", "pgvector", "ollama", "openai", "anthropic",
    "llm", "rag", "embedding", "embeddings", "vector",
    "graphql", "rest", "websocket", "oauth", "jwt", "github", "linux", "windows",
    "macos", "aws", "azure", "gcp", "vercel", "node", "rust", "golang", "java",
    "sql", "nosql", "grafana", "prometheus", "sentry", "opentelemetry", "bm25",
    "hnsw", "transformer", "pytorch", "tensorflow", "numpy", "pandas", "api",
}

# canonical entity names: variants collapse to one graph node
_ALIASES = {
    "postgresql": "postgres", "k8s": "kubernetes", "js": "javascript",
    "ts": "typescript", "py": "python", "golang": "go",
    "embeddings": "embedding",
}
# dotted/multiword tech names the tokenizer would split apart
_DOTTED_FORMS = {
    "next.js": "nextjs", "node.js": "node", "vue.js": "vue", "nest.js": "nestjs",
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

    lowered = text.lower()
    for dotted, canonical in _DOTTED_FORMS.items():
        if dotted in lowered:
            found.setdefault(canonical, "technology")

    # raw tokens: lexicon entries are surface forms ("postgres", not "postgre")
    for tok in _raw_tokens(text):
        tok = _ALIASES.get(tok, tok)
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
        low = _ALIASES.get(name.lower(), name.lower())
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
    * ≥ 1 shared entity → mentions edge (Jaccard-weighted; capped by max_links
      so hub entities like "python" can't turn the graph into a hairball)
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
        elif shared:
            union = own_entities | other_entities
            jacc = len(shared) / (len(union) or 1)
            scored.append((0.25 + 0.5 * jacc + 0.25 * max(sim, 0), "mentions", other))

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


def resync_entities_and_relationships(db: Session, memory: Memory) -> None:
    """Recompute entity links and relationships from ``memory.content`` /
    ``memory.embedding`` — call after both already hold the current text.

    Drops this memory's existing entity links and relationships first (so an
    edit can't leave it linked to entities/edges computed from text that's no
    longer there), decrementing each dropped entity's mention_count, then
    re-extracts and re-detects from scratch.

    Uses ``memory.entity_links.append/.remove`` (not raw ``db.add``) so the
    in-memory relationship collection stays consistent with the database
    without depending on a fresh lazy-load — needed on the update path, where
    the collection may already be loaded before this runs.

    Note: this only recomputes *this* memory's own relationship edges
    (source_id == memory.id and edges pointing at it are dropped, but other
    memories' own outward edges into this one are left stale until they are
    themselves re-ingested or edited). Recomputing the whole graph on every
    edit would be a much more expensive, unbounded operation and isn't what
    this fixes.
    """
    stale_rels = db.execute(
        select(Relationship).where(
            (Relationship.source_id == memory.id) | (Relationship.target_id == memory.id)
        )
    ).scalars().all()
    for rel in stale_rels:
        db.delete(rel)

    for link in list(memory.entity_links):
        link.entity.mention_count = max(0, link.entity.mention_count - 1)
        memory.entity_links.remove(link)
    db.flush()

    for name, kind in extract_entities(memory.content):
        ent = _get_or_create_entity(db, memory.workspace_id, name, kind)
        memory.entity_links.append(MemoryEntity(entity=ent))
    db.flush()

    detect_relationships(db, memory)
    db.flush()


def apply_content_update(db: Session, memory: Memory, new_content: str) -> None:
    """Update a memory's content and recompute everything derived from it:
    keywords, embedding, entity links, and relationships.

    Raises ValueError if the cleaned content is empty. Without this, editing
    a memory's content left keywords/embedding/entities/relationships frozen
    from the OLD text forever — search, the graph, and re-ranking would all
    silently drift from what the memory now actually says.
    """
    content = clean_text(new_content)
    if not content:
        raise ValueError("content is empty after cleaning")

    memory.content = content
    memory.keywords = extract_keywords(content)

    chunks = chunk_text(content)
    vectors = get_embedder().embed(chunks + [content[:2000]])
    memory.embedding = vectors[-1]

    resync_entities_and_relationships(db, memory)


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
    """Run the full pipeline and persist one memory.

    Written to two places: Supermemory Local (durable, semantically-searchable
    content) and Engram's local SQLite mirror (the source of truth for the
    knowledge graph and ranking signals — entity identity across memories,
    relationships, access/recency/importance). Commits are the caller's job.
    """
    content = clean_text(content)
    if not content:
        raise ValueError("content is empty after cleaning")

    chunks = chunk_text(content)
    embedder = get_embedder()
    vectors = embedder.embed(chunks + [content[:2000]])
    _chunk_vecs, doc_vec = vectors[:-1], vectors[-1]

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

    now = datetime.now(timezone.utc).isoformat()
    memory = Memory(
        workspace_id=workspace_id,
        type=type_,
        title=title,
        content=content,
        summary=summary,
        source=source,
        author=author,
        importance=score_importance(content, type_),
        confidence=0.8,
        created_at=now,
        updated_at=now,
    )
    memory.keywords = keywords
    memory.tags = tags or []
    memory.embedding = doc_vec
    db.add(memory)
    db.flush()  # assigns memory.id; makes the row visible to queries below

    # Entities are resolved (not recreated) per workspace so the same
    # concept — "docker" mentioned in ten memories — is one graph node,
    # not ten disconnected ones.
    resync_entities_and_relationships(db, memory)

    from .db import build_full_metadata, get_memory_store

    store = get_memory_store(db)
    store.save(workspace_id, memory.id, content, build_full_metadata(memory))

    return memory


# --------------------------------------------------------------------------
# Compression (archive old, low-value memories)
# --------------------------------------------------------------------------


def compress_workspace(db: Session, workspace_id: str, older_than_days: int = 90) -> int:
    """Archive stale, rarely-accessed memories via the memory store.

    Archiving logic has moved to the /compress router endpoint which operates
    directly on SupermemoryStore. This function is kept as a stub for any
    callers that import it but is now a no-op — return 0 to signal no
    local-DB archiving was performed.
    """
    return 0
