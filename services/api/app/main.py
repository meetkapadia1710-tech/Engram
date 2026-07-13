"""Engram API entrypoint.

Run locally:
    python -m uvicorn app.main:app --port 8000

Interactive OpenAPI docs at /docs, machine-readable spec at /openapi.json.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import settings
from .db import init_db
from .routers import memories, search, workspaces

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("engram")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
    title="Engram API",
    version=__version__,
    description=(
        "The memory layer for AI. Hybrid semantic search, knowledge graph, "
        "temporal recall, and RAG context assembly over everything your "
        "agents have ever seen."
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


app.include_router(workspaces.router)
app.include_router(memories.router)
app.include_router(search.router)
