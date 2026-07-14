"""Engram API entrypoint — AI Memory Operating System.

Run locally:
    python -m uvicorn app.main:app --port 8000

Interactive OpenAPI docs at /docs, machine-readable spec at /openapi.json.
Prometheus metrics at /metrics (text/plain).
Real-time SSE stream at /v1/workspaces/{id}/stream.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .catalog import seed_catalog
from .config import settings
from .db import get_db, init_db
from .memory_streaming import router as streaming_router
from .routers import memories, search, workspaces
from .routers.agents import router as agents_router
from .routers.events import router as events_router
from .routers.intelligence import router as intelligence_router
from .routers.observability import router as observability_router
from .routers.plugins import router as plugins_router
from .routers.tools import router as tools_router
from .routers.workflows import router as workflows_router

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("engram")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Seed first-party marketplace apps (idempotent)
    db_gen = get_db()
    db = next(db_gen)
    try:
        added = seed_catalog(db)
        if added:
            log.info("seeded %d first-party catalog apps", added)
    except Exception as exc:
        log.warning("catalog seed failed (non-fatal): %s", exc)
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

    log.info(
        "engram %s ready (db=%s, embed=%s, gen=%s, auth=%s)",
        __version__,
        settings.database_url.split("://")[0],
        settings.embedding_provider,
        settings.generation_provider,
        "api-key" if settings.api_keys else "open/dev",
    )
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Engram — AI Memory Operating System",
    version=__version__,
    description=(
        "The memory layer for AI. Hybrid semantic search, knowledge graph, "
        "temporal recall, RAG context assembly, multi-agent orchestration, "
        "workflow automation, plugin marketplace, digital twin, and "
        "knowledge evolution — over everything your agents have ever seen."
    ),
    contact={"name": "Engram", "url": "https://github.com/engram"},
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    dur_ms = (time.perf_counter() - start) * 1000
    log.info("%s %s -> %s (%.1fms)", request.method, request.url.path, response.status_code, dur_ms)
    response.headers["x-response-time-ms"] = f"{dur_ms:.1f}"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal error"})


@app.get("/health", tags=["system"])
def health():
    return {
        "status": "ok",
        "version": __version__,
        "embedding_provider": settings.embedding_provider,
        "generation_provider": settings.generation_provider,
    }


# ---------------------------------------------------------------------------
# Core platform routers (existing)
# ---------------------------------------------------------------------------
app.include_router(workspaces.router)
app.include_router(memories.router)
app.include_router(search.router)

# ---------------------------------------------------------------------------
# Extended platform routers (new)
# ---------------------------------------------------------------------------
app.include_router(plugins_router)       # /v1/catalog, /v1/workspaces/{ws}/plugins
app.include_router(agents_router)        # /v1/workspaces/{ws}/agents
app.include_router(workflows_router)     # /v1/workspaces/{ws}/workflows
app.include_router(tools_router)         # /v1/tools, /v1/workspaces/{ws}/tools
app.include_router(events_router)        # /v1/events, /v1/workspaces/{ws}/events
app.include_router(observability_router) # /metrics, /v1/metrics
app.include_router(intelligence_router)  # /v1/workspaces/{ws}/digital-twin, /evolution, /evaluation
app.include_router(streaming_router)     # /v1/workspaces/{ws}/stream (SSE)
