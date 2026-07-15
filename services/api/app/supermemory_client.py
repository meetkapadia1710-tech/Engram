"""Thin client for Supermemory Local's real v3 API.

Verified against a live instance (not just docs) — the actual contract is:

    POST   /v3/documents          create   -> {"id": <internal-id>, "status": "queued"} (async)
    GET    /v3/documents/{id}     get      -> full document; {id} may be OUR customId
                                              or Supermemory's own internal id, both work
    PATCH  /v3/documents/{id}     update   -> same {"id","status":"queued"} shape as create
    DELETE /v3/documents/{id}     delete   -> 204, idempotent (404 if already gone)
    POST   /v3/search             search   -> {"results":[{"documentId","score","metadata",
                                              "chunks":[{"content",...}], ...}], "timing","total"}
    GET    /v3/health             health   -> 200 when reachable

Workspace scoping uses `containerTags` (plural, array) everywhere — the create
endpoint tolerates the singular `containerTag` too, but `containerTags` is
what search filters on and what GET actually returns, so it's used
consistently on write.

There is no bulk-list endpoint in this API version (`GET /v3/documents`
without an id 404s) — Engram's local SQLite mirror is the source of truth
for listing/timeline, so `list_memories` is intentionally unused by the app.

Indexing is asynchronous ("status": "queued" on create/update): a document
may not be immediately searchable. This is inherent to the real system, not
something this client works around.
"""

import logging
import time
import httpx
from typing import Dict, Any, List, Optional
from .config import settings

logger = logging.getLogger(__name__)


class DocumentProcessingConflict(Exception):
    """Raised when Supermemory rejects an update/delete with 409 "Document is
    still processing" — a document briefly can't be mutated while async
    indexing finishes right after create.

    Confirmed against a live server that this window is NOT short — it can
    run well past 15 seconds under load — so blocking the request with
    retries until it clears is the wrong fix. Instead: one cheap retry to
    catch the fast case, then raise this so the caller (the memories router)
    can treat it as non-fatal. The local SQLite mirror already reflects the
    user's intended state regardless of whether Supermemory's copy has
    caught up yet.
    """


_STILL_PROCESSING_RETRY_DELAY_S = 1.0


def _is_still_processing(e: httpx.HTTPStatusError) -> bool:
    if e.response.status_code != 409:
        return False
    try:
        return "still processing" in e.response.json().get("error", "").lower()
    except Exception:  # noqa: BLE001 - best-effort sniff, fall through to re-raise
        return False

class SupermemoryClient:
    def __init__(self):
        self.base_url = settings.supermemory_url.rstrip("/")
        self.api_key = settings.supermemory_api_key
        self.timeout = settings.supermemory_timeout

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            limits=httpx.Limits(max_keepalive_connections=50)
        )

    def _handle_error(self, e: httpx.HTTPError):
        if isinstance(e, httpx.HTTPStatusError):
            logger.error(f"Supermemory API error: {e.response.status_code} {e.response.text}")
        else:
            logger.error(f"Supermemory connection error: {str(e)}")
        raise e

    def create_memory(self, container_tag: str, content: str, metadata: Dict[str, Any], custom_id: Optional[str] = None) -> Dict[str, Any]:
        logger.info(f"Saving memory... container={container_tag}")
        payload: Dict[str, Any] = {
            "content": content,
            "containerTags": [container_tag],
            "metadata": metadata,
        }
        if custom_id:
            payload["customId"] = custom_id

        try:
            resp = self.client.post("/v3/documents", json=payload)
            resp.raise_for_status()
            logger.info("Received response... Memory queued for indexing.")
            return resp.json()
        except httpx.HTTPError as e:
            self._handle_error(e)

    def update_memory(self, memory_id: str, container_tag: str, content: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Updating... id={memory_id}")
        payload = {
            "content": content,
            "metadata": metadata
        }
        for attempt in (0, 1):
            try:
                resp = self.client.patch(f"/v3/documents/{memory_id}", json=payload)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if attempt == 0 and _is_still_processing(e):
                    time.sleep(_STILL_PROCESSING_RETRY_DELAY_S)
                    continue
                if _is_still_processing(e):
                    raise DocumentProcessingConflict(memory_id) from e
                self._handle_error(e)
            except httpx.HTTPError as e:
                self._handle_error(e)

    def delete_memory(self, memory_id: str) -> None:
        logger.info(f"Deleting... id={memory_id}")
        for attempt in (0, 1):
            try:
                resp = self.client.delete(f"/v3/documents/{memory_id}")
                if resp.status_code not in (200, 204, 404):
                    resp.raise_for_status()
                logger.info("Received response... Memory deleted (or already absent).")
                return
            except httpx.HTTPStatusError as e:
                if attempt == 0 and _is_still_processing(e):
                    time.sleep(_STILL_PROCESSING_RETRY_DELAY_S)
                    continue
                if _is_still_processing(e):
                    raise DocumentProcessingConflict(memory_id) from e
                self._handle_error(e)
            except httpx.HTTPError as e:
                self._handle_error(e)

    def search_memory(self, query: str, container_tag: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        logger.info(f"Searching... query={query}")
        payload: Dict[str, Any] = {"q": query, "limit": limit}
        if container_tag:
            payload["containerTags"] = [container_tag]

        try:
            resp = self.client.post("/v3/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info("Received response... Search complete.")

            if isinstance(data, dict) and "results" in data:
                return data["results"]
            elif isinstance(data, list):
                return data
            return []
        except httpx.HTTPError as e:
            self._handle_error(e)

    def list_memories(self, container_tag: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """No bulk-list endpoint exists in this API version — always empty.
        Kept only so callers that still hold a reference to this method don't
        hit an AttributeError; nothing in the app relies on it (listing is
        local-first, see module docstring)."""
        logger.debug("list_memories has no server-side equivalent; returning []")
        return []

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        logger.info(f"Calling Supermemory... (get_memory) id={memory_id}")
        try:
            resp = self.client.get(f"/v3/documents/{memory_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            self._handle_error(e)

    def health(self):
        try:
            resp = self.client.get("/v3/health")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            self._handle_error(e)

    def ping(self, timeout: float = 2.0) -> tuple[bool, str]:
        """Best-effort reachability check. Never raises — a down Supermemory
        must not take the whole API down with it, and a health check that
        blocks for the full request timeout defeats the point of a health
        check."""
        try:
            resp = self.client.get("/v3/health", timeout=timeout)
            resp.raise_for_status()
            return True, ""
        except httpx.HTTPError as e:
            logger.warning(f"Supermemory unreachable: {e}")
            return False, str(e)
        except Exception as e:  # noqa: BLE001 - health checks must never crash the endpoint
            logger.warning(f"Supermemory ping failed: {e}")
            return False, str(e)

supermemory = SupermemoryClient()
