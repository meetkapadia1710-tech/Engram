"""Shared fixtures: fresh in-memory DB per test, FastAPI test client, Supermemory mock."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db as db_module  # noqa: E402
from app.db import Base, get_db  # noqa: E402


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from app import models, models_platform  # noqa: F401

    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = TestSession()
    yield s
    s.close()


@pytest.fixture()
def client(session, mock_supermemory):
    from app.catalog import seed_catalog
    from app.main import app

    def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    # The app's own startup hook seeds the catalog via an un-overridden
    # get_db() (it isn't a route dependency, so overrides don't reach it) —
    # seed the test's own in-memory session directly instead.
    seed_catalog(session)
    session.commit()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def workspace_id(client):
    r = client.post("/v1/workspaces", json={"name": "Test Space"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


class MockSupermemoryClient:
    """In-memory mock of SupermemoryClient, shaped like the real v3 API
    (verified against a live Supermemory Local instance — see
    supermemory_client.py's module docstring): documents use `containerTags`
    (plural, array); search hits are a thinner shape keyed by `documentId`
    with content nested under `chunks[].content`, not the document shape."""

    def __init__(self):
        self._memories: dict[str, dict] = {}

    def create_memory(self, container_tag: str, content: str, metadata: dict, custom_id: str | None = None) -> dict:
        m_id = custom_id or uuid.uuid4().hex
        data = {
            "id": m_id,
            "customId": m_id,
            "containerTags": [container_tag],
            "content": content,
            "title": metadata.get("title", ""),
            "metadata": metadata,
        }
        self._memories[m_id] = data
        return {"id": m_id, "status": "queued"}

    def update_memory(self, memory_id: str, container_tag: str, content: str, metadata: dict) -> dict | None:
        if memory_id in self._memories:
            self._memories[memory_id]["content"] = content
            self._memories[memory_id]["metadata"] = metadata
            self._memories[memory_id]["title"] = metadata.get("title", "")
            return {"id": memory_id, "status": "queued"}
        # Recreate if not found (matches the real API: PATCH on a missing id 404s,
        # but tests that exercise update-before-create aren't the concern here)
        self.create_memory(container_tag, content, metadata, custom_id=memory_id)
        return {"id": memory_id, "status": "queued"}

    def delete_memory(self, memory_id: str) -> None:
        self._memories.pop(memory_id, None)

    def search_memory(self, query: str, container_tag: str | None = None, limit: int = 50) -> list[dict]:
        qs = query.lower().split()
        res = []
        for m in self._memories.values():
            if container_tag and container_tag not in m["containerTags"]:
                continue
            content_lower = m["content"].lower()
            title_lower = m["metadata"].get("title", "").lower()
            if any(q in content_lower or q in title_lower for q in qs):
                # Simulated similarity score based on matched term count
                matches = sum(1 for q in qs if q in content_lower or q in title_lower)
                sim = min(0.5 + (matches * 0.1), 0.99)

                res.append({
                    "documentId": m["id"],
                    "score": sim,
                    "title": m["title"],
                    "metadata": m["metadata"],
                    "chunks": [{"content": m["content"], "position": 0, "isRelevant": True, "score": sim}],
                    "createdAt": m["metadata"].get("created_at", ""),
                    "updatedAt": m["metadata"].get("updated_at", ""),
                })
        return res[:limit]

    def list_memories(self, container_tag: str, limit: int = 50, offset: int = 0) -> list[dict]:
        # Real API has no bulk-list endpoint; the mock matches that.
        return []

    def get_memory(self, memory_id: str) -> dict | None:
        return self._memories.get(memory_id)

    def health(self) -> dict:
        return {"status": "ok"}

    def ping(self, timeout: float = 2.0) -> tuple[bool, str]:
        return True, ""


@pytest.fixture(autouse=True)
def mock_supermemory(monkeypatch):
    """Patch the global supermemory singleton in both the client module and db module."""
    mock_client = MockSupermemoryClient()
    monkeypatch.setattr("app.supermemory_client.supermemory", mock_client)
    # Also patch the SupermemoryStore so it uses the same mock instance
    import app.db as db_mod

    original_init = db_mod.SupermemoryStore.__init__

    def patched_init(self):
        self.client = mock_client

    monkeypatch.setattr(db_mod.SupermemoryStore, "__init__", patched_init)
    return mock_client
