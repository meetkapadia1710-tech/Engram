"""ORM models — the persistent shape of a memory.

Design notes
------------
* Everything is workspace-scoped for multi-tenancy.
* `Memory.embedding` holds the document-level vector (JSON list); chunks carry
  their own vectors for fine-grained retrieval.
* Entities are first-class graph nodes; MemoryEntity is the edge table between
  memories and entities; Relationship connects memory→memory with a typed edge.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return utcnow().isoformat()


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    memories: Mapped[list["Memory"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(40), default="note", index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    source: Mapped[str] = mapped_column(String(500), default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    embedding_json: Mapped[str] = mapped_column(Text, default="[]")

    importance: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[int] = mapped_column(Integer, default=0, index=True)

    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso, index=True)
    updated_at: Mapped[str] = mapped_column(String(40), default=_now_iso)
    last_accessed_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    workspace: Mapped[Workspace] = relationship(back_populates="memories")
    chunks: Mapped[list["MemoryChunk"]] = relationship(
        back_populates="memory", cascade="all, delete-orphan"
    )
    entity_links: Mapped[list["MemoryEntity"]] = relationship(
        back_populates="memory", cascade="all, delete-orphan"
    )

    # -- JSON helpers -------------------------------------------------------
    @property
    def keywords(self) -> list[str]:
        return json.loads(self.keywords_json or "[]")

    @keywords.setter
    def keywords(self, value: list[str]) -> None:
        self.keywords_json = json.dumps(value)

    @property
    def tags(self) -> list[str]:
        return json.loads(self.tags_json or "[]")

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self.tags_json = json.dumps(value)

    @property
    def embedding(self) -> list[float]:
        return json.loads(self.embedding_json or "[]")

    @embedding.setter
    def embedding(self, value: list[float]) -> None:
        self.embedding_json = json.dumps(value)


class MemoryChunk(Base):
    __tablename__ = "memory_chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding_json: Mapped[str] = mapped_column(Text, default="[]")

    memory: Mapped[Memory] = relationship(back_populates="chunks")

    @property
    def embedding(self) -> list[float]:
        return json.loads(self.embedding_json or "[]")

    @embedding.setter
    def embedding(self, value: list[float]) -> None:
        self.embedding_json = json.dumps(value)


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (Index("ix_entity_ws_name", "workspace_id", "name", unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40), default="concept")
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    memory_links: Mapped[list["MemoryEntity"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )


class MemoryEntity(Base):
    """Edge: memory --mentions--> entity."""

    __tablename__ = "memory_entities"
    __table_args__ = (
        Index("ix_memory_entity_unique", "memory_id", "entity_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )

    memory: Mapped[Memory] = relationship(back_populates="entity_links")
    entity: Mapped[Entity] = relationship(back_populates="memory_links")


class Relationship(Base):
    """Typed edge: memory --kind--> memory (references, related_to, duplicate_of…)."""

    __tablename__ = "relationships"
    __table_args__ = (
        Index("ix_rel_unique", "source_id", "target_id", "kind", unique=True),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), default="related_to")
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    actor: Mapped[str] = mapped_column(String(200), default="anonymous")
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso, index=True)
