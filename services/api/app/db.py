"""Database engine + session management (SQLAlchemy 2.x).

SQLite by default; swap to PostgreSQL (+pgvector) via ENGRAM_DATABASE_URL.
Vectors are stored as JSON arrays in a TEXT column so the same models run on
both engines; on Postgres the DDL in database/schema.sql adds a real
pgvector column + HNSW index for large deployments.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import abc
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone


from .config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register mappings)

    Base.metadata.create_all(engine)


class MemoryStore(abc.ABC):
    @abc.abstractmethod
    def save(self, workspace_id: str, mem_id: str, content: str, metadata: Dict[str, Any]) -> None:
        pass
        
    @abc.abstractmethod
    def search(self, workspace_id: str, query: str, limit: int) -> List[Any]:
        pass
        
    @abc.abstractmethod
    def update(self, workspace_id: str, mem_id: str, content: str, metadata: Dict[str, Any]) -> None:
        pass
        
    @abc.abstractmethod
    def delete(self, workspace_id: str, mem_id: str) -> None:
        pass
        
    @abc.abstractmethod
    def list(self, workspace_id: str, limit: int, offset: int) -> List[Any]:
        pass
        
    @abc.abstractmethod
    def timeline(self, workspace_id: str, limit: int) -> List[Any]:
        pass
        
    @abc.abstractmethod
    def get(self, workspace_id: str, mem_id: str) -> Optional[Any]:
        pass


def _map_document(data: Dict[str, Any], workspace_id: str = "") -> Any:
    """Map a full document (GET /v3/documents/{id} or create response shape)
    to a transient Memory. Workspace scoping uses `containerTags` (plural,
    array) — that's the real field name, confirmed against a live server."""
    from .models import Memory, Entity, MemoryEntity
    metadata = data.get("metadata", {}) or {}

    content = data.get("content", "")
    mem_id = data.get("customId") or data.get("id") or uuid.uuid4().hex
    container_tags = data.get("containerTags") or []
    workspace = workspace_id or (container_tags[0] if container_tags else "") or metadata.get("workspace_id", "")

    m = Memory(
        id=mem_id,
        workspace_id=workspace,
        content=content,
        type=metadata.get("type", "note"),
        title=data.get("title") or metadata.get("title", ""),
        summary=metadata.get("summary", ""),
        source=metadata.get("source"),
        author=metadata.get("author"),
        importance=float(metadata.get("importance") or 0.5),
        confidence=float(metadata.get("confidence") or 0.8),
        access_count=int(metadata.get("access_count") or 0),
        archived=int(metadata.get("archived") or 0),
        created_at=metadata.get("created_at") or data.get("createdAt") or datetime.now(timezone.utc).isoformat(),
        updated_at=metadata.get("updated_at") or data.get("updatedAt") or datetime.now(timezone.utc).isoformat(),
    )
    m.keywords = metadata.get("keywords", [])
    m.tags = metadata.get("tags", [])
    m.entity_links = [
        MemoryEntity(entity=Entity(id=uuid.uuid4().hex, name=n, kind=k))
        for n, k in _decode_entities(metadata.get("entities", []))
    ]
    m._similarity = 0.0
    return m


def _decode_entities(raw: list) -> list[tuple[str, str]]:
    """Reverse build_full_metadata's "name::kind" flattening (Supermemory's
    metadata schema rejects nested arrays, so entities can't round-trip as
    (name, kind) tuples directly)."""
    out = []
    for item in raw or []:
        if isinstance(item, str) and "::" in item:
            name, _, kind = item.partition("::")
            out.append((name, kind))
    return out


def _map_search_hit(item: Dict[str, Any], workspace_id: str = "") -> Any:
    """Map a /v3/search result item to a transient Memory.

    Search hits carry a much thinner shape than a full document — content
    lives under `chunks[].content`, not a top-level `content` field, and
    there's no `containerTags`. This is only ever used as a fallback in
    hybrid_search when a candidate has no local mirror (the common path
    instead uses the local row and only borrows `_similarity` from here), so
    "reasonable to display" is the bar, not "complete".
    """
    from .models import Entity, Memory, MemoryEntity

    metadata = item.get("metadata", {}) or {}
    chunks = item.get("chunks") or []
    content = "\n".join(c.get("content", "") for c in chunks if c.get("content")) or item.get("title", "")
    mem_id = item.get("documentId") or item.get("id") or uuid.uuid4().hex

    m = Memory(
        id=mem_id,
        workspace_id=workspace_id,
        content=content,
        type=metadata.get("type", "note"),
        title=item.get("title") or metadata.get("title", ""),
        summary=metadata.get("summary", ""),
        importance=float(metadata.get("importance") or 0.5),
        confidence=float(metadata.get("confidence") or 0.8),
        created_at=item.get("createdAt") or datetime.now(timezone.utc).isoformat(),
        updated_at=item.get("updatedAt") or datetime.now(timezone.utc).isoformat(),
    )
    m.keywords = metadata.get("keywords", [])
    m.tags = metadata.get("tags", [])
    m.entity_links = [
        MemoryEntity(entity=Entity(id=uuid.uuid4().hex, name=n, kind=k))
        for n, k in _decode_entities(metadata.get("entities", []))
    ]
    m._similarity = float(item.get("score", 0.0))
    return m

class SupermemoryStore(MemoryStore):
    def __init__(self):
        from .supermemory_client import supermemory
        self.client = supermemory

    def save(self, workspace_id: str, mem_id: str, content: str, metadata: Dict[str, Any]) -> None:
        self.client.create_memory(workspace_id, content, metadata, custom_id=mem_id)

    def search(self, workspace_id: str, query: str, limit: int) -> List[Any]:
        results = self.client.search_memory(query, container_tag=workspace_id, limit=limit)
        return [_map_search_hit(r, workspace_id=workspace_id) for r in results]

    def update(self, workspace_id: str, mem_id: str, content: str, metadata: Dict[str, Any]) -> None:
        self.client.update_memory(mem_id, workspace_id, content, metadata)

    def delete(self, workspace_id: str, mem_id: str) -> None:
        self.client.delete_memory(mem_id)

    def list(self, workspace_id: str, limit: int, offset: int) -> List[Any]:
        # Supermemory Local's v3 API has no bulk-list endpoint (confirmed:
        # GET /v3/documents with no id 404s). Engram's local SQLite mirror is
        # the source of truth for listing/timeline; nothing in the app calls
        # this method, but it stays honest rather than faking a result.
        return []

    def timeline(self, workspace_id: str, limit: int) -> List[Any]:
        return []

    def get(self, workspace_id: Optional[str], mem_id: str) -> Optional[Any]:
        data = self.client.get_memory(mem_id)
        if not data:
            return None
        container_tags = data.get("containerTags") or []
        if workspace_id is not None and container_tags and workspace_id not in container_tags:
            return None
        return _map_document(data, workspace_id=workspace_id or (container_tags[0] if container_tags else ""))


class SQLiteStore(MemoryStore):
    def __init__(self, db: Session):
        self.db = db
        
    def save(self, workspace_id: str, mem_id: str, content: str, metadata: Dict[str, Any]) -> None:
        pass  # Migration complete: no new memory is stored in SQLite
        
    def search(self, workspace_id: str, query: str, limit: int) -> List[Dict[str, Any]]:
        return []
        
    def update(self, workspace_id: str, mem_id: str, content: str, metadata: Dict[str, Any]) -> None:
        pass
        
    def delete(self, workspace_id: str, mem_id: str) -> None:
        pass
        
    def list(self, workspace_id: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        return []
        
    def timeline(self, workspace_id: str, limit: int) -> List[Dict[str, Any]]:
        return []

    def get(self, workspace_id: Optional[str], mem_id: str) -> Optional[Any]:
        return None

def get_memory_store(db: Optional[Session] = None) -> MemoryStore:
    return SupermemoryStore()


def build_full_metadata(m: Any) -> Dict[str, Any]:
    """Serialize every field a local Memory row carries into a Supermemory
    metadata dict.

    Every write to the store must go through this (never a hand-rolled
    subset) — Supermemory's PATCH replaces the metadata object wholesale, so
    a partial dict silently deletes whatever fields it omits (this previously
    wiped `entities` and `created_at` on every search/read that happened to
    touch a memory).

    Supermemory's metadata schema only accepts scalars and flat string
    arrays as values — a nested array (e.g. a list of (name, kind) tuples)
    gets rejected with a 400 (confirmed against a live server). Entities are
    therefore flattened to "name::kind" strings; `_map_document`/
    `_map_search_hit` in db.py decode this same format back on the read side.
    """
    return {
        "title": m.title,
        "type": m.type,
        "summary": m.summary,
        "source": m.source,
        "author": m.author,
        "importance": m.importance,
        "confidence": m.confidence,
        "keywords": m.keywords,
        "tags": m.tags,
        "entities": [f"{l.entity.name}::{l.entity.kind}" for l in m.entity_links],
        "created_at": m.created_at,
        "updated_at": m.updated_at,
        "access_count": m.access_count,
        "archived": m.archived,
    }

