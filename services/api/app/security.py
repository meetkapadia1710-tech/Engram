"""API-key auth, sliding-window rate limiting, and audit logging.

Dev mode (no ENGRAM_API_KEYS set) is open, so a fresh clone works instantly;
setting the env var flips every route to require `Authorization: Bearer <key>`
or `X-API-Key: <key>`. The rate limiter is in-process (per worker); swap in
Redis for multi-instance deployments — the interface is a single callable.
"""

from __future__ import annotations

import hmac
import time
from collections import deque

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuditLog

_windows: dict[str, deque[float]] = {}


def _client_id(request: Request) -> str:
    key = request.headers.get("x-api-key") or ""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        key = auth[7:]
    return key or (request.client.host if request.client else "unknown")


def rate_limit(request: Request) -> None:
    ident = _client_id(request)
    now = time.monotonic()
    q = _windows.setdefault(ident, deque())
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= settings.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    q.append(now)


def require_api_key(request: Request) -> str:
    """Returns the actor id ('dev' in open mode, the key otherwise)."""
    if not settings.api_keys:
        return "dev"
    supplied = _client_id(request)
    for valid in settings.api_keys:
        if hmac.compare_digest(supplied, valid):
            return supplied[:8] + "…"
    raise HTTPException(status_code=401, detail="invalid or missing API key")


def audit(
    db: Session,
    *,
    actor: str,
    action: str,
    workspace_id: str = "",
    detail: str = "",
) -> None:
    db.add(AuditLog(actor=actor, action=action, workspace_id=workspace_id, detail=detail[:2000]))


class Guard:
    """FastAPI dependency bundle: rate-limit + auth + db session."""

    def __init__(self, actor: str, db: Session):
        self.actor = actor
        self.db = db


def guard(
    request: Request,
    db: Session = Depends(get_db),
) -> Guard:
    rate_limit(request)
    actor = require_api_key(request)
    return Guard(actor=actor, db=db)
