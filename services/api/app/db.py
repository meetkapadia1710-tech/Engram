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


def _map_to_memory(data: Dict[str, Any]) -> Any:
    from .models import Memory, Entity, MemoryEntity
    metadata = data.get("metadata", {})
    
    # Supermemory v4 search results use 'memory' as content field; fallback to 'content'
    content = data.get("content") or data.get("memory", "")
    # 'id' may come as top-level or nested under customId
    mem_id = data.get("customId") or data.get("id", uuid.uuid4().hex)
    workspace = data.get("containerTag", "") or metadata.get("workspace_id", "")
            
    m = Memory(
        id=mem_id,
        workspace_id=workspace,
        content=content,
        type=metadata.get("type", "note"),
        title=metadata.get("title", ""),
        summary=metadata.get("summary", ""),
        source=metadata.get("source"),
        author=metadata.get("author"),
        importance=float(metadata.get("importance") or 0.5),
        confidence=float(metadata.get("confidence") or 0.8),
        access_count=int(metadata.get("access_count") or 0),
        archived=int(metadata.get("archived") or 0),
        created_at=metadata.get("created_at") or data.get("createdAt", datetime.now(timezone.utc).isoformat()),
        updated_at=metadata.get("updated_at") or data.get("updatedAt", datetime.now(timezone.utc).isoformat()),
    )
    m.keywords = metadata.get("keywords", [])
    m.tags = metadata.get("tags", [])
    # Reconstruct entities if saved in metadata
    entities_data = metadata.get("entities", [])
    if entities_data:
        links = []
        for n, k in entities_data:
            e = Entity(id=uuid.uuid4().hex, name=n, kind=k)
            links.append(MemoryEntity(entity=e))
        m.entity_links = links
    else:
        m.entity_links = []
    return m

class SupermemoryStore(MemoryStore):
    def __init__(self):
        from .supermemory_client import supermemory
        self.client = supermemory
        
    def save(self, workspace_id: str, mem_id: str, content: str, metadata: Dict[str, Any]) -> None:
        self.client.create_memory(workspace_id, content, metadata, custom_id=mem_id)
        
    def search(self, workspace_id: str, query: str, limit: int) -> List[Any]:
        results = self.client.search_memory(query, container_tag=workspace_id, limit=limit)
        return [_map_to_memory(r) for r in results]
        
    def update(self, workspace_id: str, mem_id: str, content: str, metadata: Dict[str, Any]) -> None:
        self.client.update_memory(mem_id, workspace_id, content, metadata)
        
    def delete(self, workspace_id: str, mem_id: str) -> None:
        self.client.delete_memory(mem_id)
        
    def list(self, workspace_id: str, limit: int, offset: int) -> List[Any]:
        items = self.client.list_memories(workspace_id, limit, offset)
        return [_map_to_memory(i) for i in items]
        
    def timeline(self, workspace_id: str, limit: int) -> List[Any]:
        items = self.client.list_memories(workspace_id, limit=limit, offset=0)
        memories = [_map_to_memory(i) for i in items]
        memories.sort(key=lambda x: x.created_at, reverse=True)
        return memories

    def get(self, workspace_id: Optional[str], mem_id: str) -> Optional[Any]:
        data = self.client.get_memory(mem_id)
        if not data:
            return None
        if workspace_id is not None and data.get("containerTag") != workspace_id:
            return None
        return _map_to_memory(data)


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

