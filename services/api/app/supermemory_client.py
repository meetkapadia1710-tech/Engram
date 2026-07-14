import logging
import httpx
from typing import Dict, Any, List, Optional
from .config import settings

logger = logging.getLogger(__name__)

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
        memory_item = {
            "content": content,
            "metadata": metadata,
            "isStatic": False
        }
        if custom_id:
            memory_item["customId"] = custom_id
        
        payload = {
            "containerTag": container_tag,
            "memories": [memory_item]
        }
            
        try:
            resp = self.client.post("/v4/memories", json=payload)
            resp.raise_for_status()
            logger.info("Received response... Memory saved.")
            return resp.json()
        except httpx.HTTPError as e:
            self._handle_error(e)

    def update_memory(self, memory_id: str, container_tag: str, content: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Updating... id={memory_id}")
        payload = {
            "content": content,
            "metadata": metadata
        }
        try:
            resp = self.client.patch(f"/v4/memories/{memory_id}", json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            # Fallback to delete + create if PATCH is not supported
            self.delete_memory(memory_id)
            return self.create_memory(container_tag, content, metadata, custom_id=memory_id)

    def delete_memory(self, memory_id: str) -> None:
        logger.info(f"Deleting... id={memory_id}")
        try:
            resp = self.client.delete(f"/v4/memories/{memory_id}")
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()
            logger.info("Received response... Memory deleted (or already absent).")
        except httpx.HTTPError as e:
            self._handle_error(e)

    def search_memory(self, query: str, container_tag: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        logger.info(f"Searching... query={query}")
        payload = {"query": query, "limit": limit}
        if container_tag:
            payload["containerTag"] = container_tag
            
        try:
            resp = self.client.post("/v4/search", json=payload)
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
        logger.info(f"Calling Supermemory... (list_memories) container={container_tag}")
        params = {"containerTag": container_tag, "limit": limit, "offset": offset}
        try:
            resp = self.client.get("/v4/memories", params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            elif isinstance(data, dict) and "memories" in data:
                return data["memories"]
            elif isinstance(data, list):
                return data
            return []
        except httpx.HTTPError as e:
            self._handle_error(e)
            
    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        logger.info(f"Calling Supermemory... (get_memory) id={memory_id}")
        try:
            resp = self.client.get(f"/v4/memories/{memory_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            self._handle_error(e)

    def profile(self):
        try:
            resp = self.client.get("/v4/profile")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            self._handle_error(e)
            
    def health(self):
        try:
            resp = self.client.get("/health")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            self._handle_error(e)

supermemory = SupermemoryClient()
