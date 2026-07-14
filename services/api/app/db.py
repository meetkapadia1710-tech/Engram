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
    from .models import Memory
    metadata = data.get("metadata", {})
    # Mock entities to avoid SQLAlchemy relationship errors
    class MockEntity:
        def __init__(self, name, kind):
            self.id = uuid.uuid4().hex
            self.name = name
            self.kind = kind
    class MockLink:
        def __init__(self, name, kind):
            self.entity = MockEntity(name, kind)
            
    m = Memory(
        id=data.get("id", data.get("customId", uuid.uuid4().hex)),
        workspace_id=data.get("containerTag", ""),
        type=metadata.get("type", "note"),
        title=metadata.get("title", ""),
        content=data.get("content", ""),
        summary=metadata.get("summary", ""),
        source=metadata.get("source", ""),
        author=metadata.get("author", ""),
        importance=float(metadata.get("importance", 0.5)),
        confidence=float(metadata.get("confidence", 0.8)),
        access_count=int(metadata.get("access_count", 0)),
        archived=int(metadata.get("archived", 0)),
        created_at=metadata.get("created_at", datetime.now(timezone.utc).isoformat()),
        updated_at=metadata.get("updated_at", datetime.now(timezone.utc).isoformat())
    )
    m.keywords = metadata.get("keywords", [])
    m.tags = metadata.get("tags", [])
    # Reconstruct entities if saved in metadata
    entities_data = metadata.get("entities", [])
    m.entity_links = [MockLink(n, k) for n, k in entities_data] if entities_data else []
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

    def get(self, workspace_id: str, mem_id: str) -> Optional[Any]:
        data = self.client.get_memory(mem_id)
        if data:
            return _map_to_memory(data)
        return None


class SQLiteStore(MemoryStore):
    def __init__(self, db: Session):
        self.db = db
        
    def save(self, workspace_id: str, mem_id: str, content: str, metadata: Dict[str, Any]) -> None:
        pass  # Migration required: no new memory is stored in SQLite
        
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


def get_memory_store(db: Optional[Session] = None) -> MemoryStore:
    return SupermemoryStore()

