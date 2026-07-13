"""Pydantic request/response contracts (the public API shape)."""

from __future__ import annotations

from pydantic import BaseModel, Field

MEMORY_TYPES = [
    "conversation", "document", "website", "pdf", "code", "github_repository",
    "image_ocr", "voice_transcript", "video_transcript", "meeting_notes",
    "research_paper", "email", "calendar_event", "task", "note", "bookmark",
    "chat", "api_response",
]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(default="", max_length=200)


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    created_at: str
    memory_count: int = 0


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)
    type: str = Field(default="note")
    title: str = Field(default="", max_length=300)
    source: str = Field(default="", max_length=500)
    author: str = Field(default="", max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)


class MemoryUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    importance: float | None = Field(default=None, ge=0, le=1)
    archived: bool | None = None


class MemoryOut(BaseModel):
    id: str
    workspace_id: str
    type: str
    title: str
    content: str
    summary: str
    keywords: list[str]
    tags: list[str]
    source: str
    author: str
    importance: float
    confidence: float
    access_count: int
    archived: bool
    created_at: str
    updated_at: str
    entities: list[dict] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=50)
    mode: str = Field(default="hybrid", pattern="^(hybrid|vector|keyword)$")
    types: list[str] | None = None
    tags: list[str] | None = None
    entities: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None


class SearchHitOut(BaseModel):
    memory: MemoryOut
    score: float
    components: dict


class ContextRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    max_tokens: int = Field(default=1800, ge=100, le=8000)
    limit: int = Field(default=12, ge=1, le=30)
    types: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
