"""Shared fixtures: fresh in-memory DB per test, FastAPI test client."""

from __future__ import annotations

import sys
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
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = TestSession()
    yield s
    s.close()


@pytest.fixture()
def client(session):
    from app.main import app

    def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def workspace_id(client):
    r = client.post("/v1/workspaces", json={"name": "Test Space"})
    assert r.status_code == 201, r.text
    return r.json()["id"]

@pytest.fixture(autouse=True)
def mock_supermemory(monkeypatch):
    import uuid
    from datetime import datetime, timezone
    
    class MockClient:
        def __init__(self):
            self.memories = {}
            
        def create_memory(self, container_tag, content, metadata, custom_id=None):
            m_id = custom_id or uuid.uuid4().hex
            data = {"id": m_id, "containerTag": container_tag, "content": content, "metadata": metadata}
            self.memories[m_id] = data
            return data
            
        def update_memory(self, memory_id, container_tag, content, metadata):
            if memory_id in self.memories:
                self.memories[memory_id] = {"id": memory_id, "containerTag": container_tag, "content": content, "metadata": metadata}
                return self.memories[memory_id]
            return None
            
        def delete_memory(self, memory_id):
            self.memories.pop(memory_id, None)
            
        def search_memory(self, query, container_tag=None, limit=50):
            qs = query.lower().split()
            res = []
            for m in self.memories.values():
                if m["containerTag"] != container_tag:
                    continue
                content = m["content"].lower()
                title = m["metadata"].get("title", "").lower()
                if any(q in content or q in title for q in qs):
                    res.append(m)
            return res[:limit]
            
        def list_memories(self, container_tag, limit=50, offset=0):
            return [m for m in self.memories.values() if m["containerTag"] == container_tag][offset:offset+limit]
            
        def get_memory(self, memory_id):
            return self.memories.get(memory_id)
            
    mock_client = MockClient()
    monkeypatch.setattr("app.supermemory_client.supermemory", mock_client)

