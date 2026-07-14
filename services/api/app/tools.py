"""Tool registry + sandboxed execution.

Every tool declares a JSON schema, a required permission, and a timeout.
Execution is audited (ToolExecution rows) and metered. Sandboxing:

* ``fs.read``  — jailed to the Engram data directory; path traversal refused.
* ``http.get`` — outbound requests only to the configured domain allowlist
  (ENGRAM_TOOL_HTTP_ALLOWLIST, default localhost) with a hard timeout and
  response-size cap; private-IP literals are refused.
* memory tools — scoped to the caller's workspace, permission-gated.

New tools register with @tool; agents/workflows call `execute()`.
"""

from __future__ import annotations

import ipaddress
import json
import os
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from . import observability
from .config import DATA_DIR
from .models_platform import ToolExecution

HTTP_ALLOWLIST = [
    d.strip().lower()
    for d in os.environ.get("ENGRAM_TOOL_HTTP_ALLOWLIST", "localhost,127.0.0.1").split(",")
    if d.strip()
]
HTTP_MAX_BYTES = 256 * 1024
DEFAULT_TIMEOUT_S = 15.0


class ToolError(Exception):
    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status = status  # denied | error | timeout
        self.detail = detail


class Tool:
    def __init__(self, name: str, description: str, permission: str,
                 schema: dict, fn: Callable, timeout_s: float):
        self.name = name
        self.description = description
        self.permission = permission
        self.schema = schema
        self.fn = fn
        self.timeout_s = timeout_s


REGISTRY: dict[str, Tool] = {}


def tool(name: str, *, description: str, permission: str, schema: dict,
         timeout_s: float = DEFAULT_TIMEOUT_S):
    def deco(fn: Callable) -> Callable:
        REGISTRY[name] = Tool(name, description, permission, schema, fn, timeout_s)
        return fn
    return deco


def execute(
    db: Session,
    name: str,
    args: dict,
    *,
    workspace_id: str = "",
    caller: str = "user",
    granted_permissions: list[str] | None = None,
) -> dict:
    """Run a tool with permission check, timing, and audit. Raises ToolError."""
    t = REGISTRY.get(name)
    rec = ToolExecution(
        workspace_id=workspace_id, tool=name, caller=caller,
        args_json=json.dumps(args, default=str)[:2000],
    )
    db.add(rec)
    start = time.perf_counter()
    try:
        if t is None:
            raise ToolError("error", f"unknown tool {name!r}")
        if granted_permissions is not None and t.permission not in granted_permissions:
            raise ToolError("denied", f"caller lacks permission {t.permission!r}")
        result = t.fn(db=db, workspace_id=workspace_id, **args)
        rec.status = "ok"
        rec.result_preview = json.dumps(result, default=str)[:500]
        observability.count(f"tools.{name}.ok")
        return result
    except ToolError as e:
        rec.status = e.status
        rec.result_preview = e.detail[:500]
        observability.count(f"tools.{name}.{e.status}")
        raise
    except TypeError as e:  # bad args against the schema
        rec.status = "error"
        rec.result_preview = str(e)[:500]
        observability.count(f"tools.{name}.error")
        raise ToolError("error", f"invalid arguments: {e}") from e
    except Exception as e:  # noqa: BLE001
        rec.status = "error"
        rec.result_preview = f"{type(e).__name__}: {e}"[:500]
        observability.count(f"tools.{name}.error")
        raise ToolError("error", str(e)) from e
    finally:
        rec.duration_ms = round((time.perf_counter() - start) * 1000, 2)
        observability.observe_ms(f"tools.{name}", rec.duration_ms)
        # session doesn't autoflush; a caller auditing tool_executions in the
        # same transaction must see this row immediately
        db.flush()


def list_tools() -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "permission": t.permission,
         "schema": t.schema, "timeout_s": t.timeout_s}
        for t in REGISTRY.values()
    ]


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------


@tool("memory.search", description="Hybrid search over workspace memories",
      permission="search",
      schema={"query": "string", "limit": "int (default 5)"})
def _memory_search(*, db: Session, workspace_id: str, query: str, limit: int = 5):
    from .search import hybrid_search

    hits = hybrid_search(db, workspace_id, query, limit=min(int(limit), 25))
    return {"results": [
        {"id": h.memory.id, "title": h.memory.title,
         "content": h.memory.content[:400], "score": h.final}
        for h in hits
    ]}


@tool("memory.create", description="Store a new memory (full pipeline)",
      permission="memory.write",
      schema={"content": "string", "memory_type": "string (default note)",
              "tags": "list[str]"})
def _memory_create(*, db: Session, workspace_id: str, content: str,
                   memory_type: str = "note", tags: list | None = None):
    from .pipeline import ingest_memory

    mem = ingest_memory(db, workspace_id=workspace_id, content=str(content)[:100_000],
                        type_=memory_type, tags=list(tags or [])[:10])
    return {"id": mem.id, "title": mem.title}


@tool("context.build", description="Build a cited RAG context block",
      permission="context",
      schema={"query": "string", "max_tokens": "int (default 1200)"})
def _context_build(*, db: Session, workspace_id: str, query: str, max_tokens: int = 1200):
    from .rag import build_context

    return build_context(db, workspace_id, query,
                         max_tokens=max(100, min(int(max_tokens), 4000)))


@tool("fs.read", description="Read a file inside the Engram data directory (sandboxed)",
      permission="tools.fs",
      schema={"path": "string (relative to data dir)"})
def _fs_read(*, db: Session, workspace_id: str, path: str):
    base = Path(DATA_DIR).resolve()
    target = (base / str(path)).resolve()
    if base != target and base not in target.parents:
        raise ToolError("denied", "path escapes the sandbox")
    if not target.is_file():
        raise ToolError("error", f"no such file: {path}")
    data = target.read_bytes()[:HTTP_MAX_BYTES]
    return {"path": str(path), "size": target.stat().st_size,
            "content": data.decode("utf-8", errors="replace")}


def _host_allowed(host: str) -> bool:
    host = host.lower()
    try:
        ip = ipaddress.ip_address(host)
        # allow only the loopback literals that are explicitly allowlisted
        return str(ip) in HTTP_ALLOWLIST
    except ValueError:
        pass
    return any(host == d or host.endswith("." + d) for d in HTTP_ALLOWLIST)


@tool("http.get", description="HTTP GET against the domain allowlist (sandboxed)",
      permission="tools.http",
      schema={"url": "string"}, timeout_s=10.0)
def _http_get(*, db: Session, workspace_id: str, url: str):
    parsed = urllib.parse.urlparse(str(url))
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ToolError("error", "invalid url")
    if not _host_allowed(parsed.hostname):
        raise ToolError("denied", f"host {parsed.hostname!r} is not allowlisted")
    try:
        r = httpx.get(url, timeout=8.0, follow_redirects=False)
    except httpx.TimeoutException as e:
        raise ToolError("timeout", "request timed out") from e
    body = r.text[:HTTP_MAX_BYTES]
    return {"status": r.status_code, "body": body,
            "content_type": r.headers.get("content-type", "")}
