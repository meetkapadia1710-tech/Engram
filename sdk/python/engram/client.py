"""Synchronous Engram client (stdlib-only: urllib, zero dependencies)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class EngramError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"[{status}] {detail}")
        self.status = status
        self.detail = detail


@dataclass
class MemoryRecord:
    id: str
    title: str
    content: str
    type: str
    summary: str = ""
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    created_at: str = ""
    entities: list[dict] = field(default_factory=list)

    @classmethod
    def from_json(cls, d: dict) -> "MemoryRecord":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class SearchHit:
    memory: MemoryRecord
    score: float
    components: dict[str, float]

    @property
    def content(self) -> str:
        return self.memory.content


class Engram:
    """Client for one Engram workspace.

    If ``workspace`` is omitted the first workspace on the server is used
    (created as "Personal" when none exists) — mirroring the web app.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        api_key: str = "",
        workspace: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._workspace = workspace

    # -- plumbing -----------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Content-Type": "application/json",
                **({"X-API-Key": self.api_key} if self.api_key else {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail", str(e))
            except Exception:  # noqa: BLE001
                detail = str(e)
            raise EngramError(e.code, str(detail)) from e

    @property
    def workspace(self) -> str:
        if not self._workspace:
            items = self._request("GET", "/v1/workspaces")["items"]
            if items:
                self._workspace = items[0]["id"]
            else:
                created = self._request("POST", "/v1/workspaces", {"name": "Personal"})
                self._workspace = created["id"]
        return self._workspace

    # -- memories -----------------------------------------------------------

    def create_memory(
        self,
        content: str,
        *,
        type: str = "note",
        title: str = "",
        tags: list[str] | None = None,
        source: str = "",
    ) -> MemoryRecord:
        d = self._request(
            "POST",
            f"/v1/workspaces/{self.workspace}/memories",
            {"content": content, "type": type, "title": title,
             "tags": tags or [], "source": source},
        )
        return MemoryRecord.from_json(d)

    def get_memory(self, memory_id: str) -> MemoryRecord:
        return MemoryRecord.from_json(self._request("GET", f"/v1/memories/{memory_id}"))

    def update_memory(self, memory_id: str, **fields: Any) -> MemoryRecord:
        return MemoryRecord.from_json(
            self._request("PATCH", f"/v1/memories/{memory_id}", fields)
        )

    def delete_memory(self, memory_id: str) -> None:
        self._request("DELETE", f"/v1/memories/{memory_id}")

    # -- retrieval ----------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        mode: str = "hybrid",
        types: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[SearchHit]:
        d = self._request(
            "POST",
            f"/v1/workspaces/{self.workspace}/search",
            {"query": query, "limit": limit, "mode": mode, "types": types,
             "date_from": date_from, "date_to": date_to},
        )
        return [
            SearchHit(
                memory=MemoryRecord.from_json(r["memory"]),
                score=r["score"],
                components=r["components"],
            )
            for r in d["results"]
        ]

    def retrieve_context(self, query: str, *, max_tokens: int = 1800) -> dict:
        """Returns {'context': str, 'sources': [...]} ready for prompt assembly."""
        return self._request(
            "POST",
            f"/v1/workspaces/{self.workspace}/context",
            {"query": query, "max_tokens": max_tokens},
        )

    def find_related(self, memory_id: str, *, limit: int = 8) -> list[dict]:
        return self._request(
            "GET", f"/v1/memories/{memory_id}/related?limit={limit}"
        )["items"]

    def knowledge_graph(self, *, center: str | None = None) -> dict:
        q = f"?center={center}" if center else ""
        return self._request("GET", f"/v1/workspaces/{self.workspace}/graph{q}")

    def analytics(self) -> dict:
        return self._request("GET", f"/v1/workspaces/{self.workspace}/analytics")
