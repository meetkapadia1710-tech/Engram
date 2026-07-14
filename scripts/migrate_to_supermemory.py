#!/usr/bin/env python3
"""migrate_to_supermemory.py — Bulk-migrate Engram SQLite observations → Supermemory.

Usage:
    python scripts/migrate_to_supermemory.py \
        --db data/engram.db \
        --supermemory-url http://localhost:6767 \
        --api-key <key>          # optional \
        --batch-size 50          # memories per API call (default 50) \
        --dry-run                # print without sending

The script reads all non-migrated workspaces and their memories from the
SQLite database, converts each Memory row to a Supermemory v4 payload, and
POSTs them in batches to /v4/memories.

A `migrated` marker is written to `data/migration_log.json` so the script
is safely re-runnable (already-migrated IDs are skipped).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Bootstrap: add the service API app to path so we can reuse config/models
# ---------------------------------------------------------------------------
_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_root / "services" / "api"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("migrate")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_migration_log(path: Path) -> Dict[str, str]:
    """Load {sqlite_id: supermemory_id} mapping from previous runs."""
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_migration_log(path: Path, log_data: Dict[str, str]) -> None:
    path.write_text(json.dumps(log_data, indent=2))


def _row_to_payload(row: Any) -> Dict[str, Any]:
    """Convert a SQLAlchemy Memory row to a Supermemory memory entry dict."""
    import json as _json

    def _load(val: str | None, default: Any) -> Any:
        if not val:
            return default
        try:
            return _json.loads(val)
        except Exception:
            return default

    return {
        "content": (row.title + "\n\n" + row.content).strip() if row.title else row.content,
        "customId": row.id,
        "isStatic": False,
        "metadata": {
            "title": row.title or "",
            "type": row.type or "note",
            "summary": row.summary or "",
            "source": row.source or "",
            "author": row.author or "",
            "importance": float(row.importance or 0.5),
            "confidence": float(row.confidence or 0.8),
            "access_count": int(row.access_count or 0),
            "archived": int(row.archived or 0),
            "keywords": _load(row.keywords_json, []),
            "tags": _load(row.tags_json, []),
            "created_at": row.created_at or "",
            "updated_at": row.updated_at or "",
            "workspace_id": row.workspace_id or "",
        },
    }


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

def migrate(
    db_url: str,
    supermemory_url: str,
    api_key: str,
    batch_size: int,
    dry_run: bool,
    log_path: Path,
) -> None:
    import httpx
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    # Import ORM models
    from app.models import Memory, Workspace

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()

    migration_log = _load_migration_log(log_path)
    already_done = set(migration_log.keys())
    log.info("Loaded %d previously migrated IDs.", len(already_done))

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    client = httpx.Client(base_url=supermemory_url.rstrip("/"), headers=headers, timeout=30)

    workspaces = list(db.execute(select(Workspace)).scalars())
    log.info("Found %d workspace(s).", len(workspaces))

    total_migrated = 0
    total_skipped = 0
    total_errors = 0

    for ws in workspaces:
        memories = list(
            db.execute(
                select(Memory).where(Memory.workspace_id == ws.id)
            ).scalars()
        )
        log.info("Workspace [%s] %s → %d memories", ws.id, ws.name, len(memories))

        batch: List[Dict[str, Any]] = []

        def flush_batch(container_tag: str, batch: List[Dict[str, Any]]) -> int:
            if not batch:
                return 0
            if dry_run:
                log.info("  DRY-RUN: would POST %d memories to container=%s", len(batch), container_tag)
                for entry in batch:
                    migration_log[entry["customId"]] = "dry-run"
                return len(batch)

            payload = {"containerTag": container_tag, "memories": batch}
            try:
                resp = client.post("/v4/memories", json=payload)
                resp.raise_for_status()
                data = resp.json()
                created = data.get("memories", [])
                for mem_info in created:
                    # Match by customId → supermemory id
                    cid = mem_info.get("customId", mem_info.get("id", ""))
                    migration_log[cid] = mem_info.get("id", "")
                log.info("  ✓ Stored batch of %d", len(batch))
                return len(batch)
            except Exception as exc:
                log.error("  ✗ Batch failed: %s", exc)
                return 0

        for mem in memories:
            if mem.id in already_done:
                total_skipped += 1
                continue
            batch.append(_row_to_payload(mem))
            if len(batch) >= batch_size:
                n = flush_batch(ws.id, batch)
                total_migrated += n
                total_errors += (len(batch) - n)
                batch = []
                time.sleep(0.1)  # gentle rate limiting

        # flush remainder
        if batch:
            n = flush_batch(ws.id, batch)
            total_migrated += n
            total_errors += (len(batch) - n)

        _save_migration_log(log_path, migration_log)

    db.close()
    client.close()

    log.info(
        "\nMigration complete:\n"
        "  Migrated : %d\n"
        "  Skipped  : %d (already done)\n"
        "  Errors   : %d\n"
        "  Log file : %s",
        total_migrated, total_skipped, total_errors, log_path,
    )
    if total_errors:
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Engram SQLite → Supermemory")
    parser.add_argument(
        "--db",
        default=str(_root / "data" / "engram.db"),
        help="SQLite database path or URL (default: data/engram.db)",
    )
    parser.add_argument(
        "--supermemory-url",
        default="http://localhost:6767",
        help="Supermemory Local base URL (default: http://localhost:6767)",
    )
    parser.add_argument("--api-key", default="", help="Supermemory API key (optional)")
    parser.add_argument("--batch-size", type=int, default=50, help="Memories per API batch")
    parser.add_argument("--dry-run", action="store_true", help="Print without sending to API")
    parser.add_argument(
        "--log-file",
        default=str(_root / "data" / "migration_log.json"),
        help="Path to migration progress log (default: data/migration_log.json)",
    )
    args = parser.parse_args()

    db_url = args.db if "://" in args.db else f"sqlite:///{args.db}"
    log_path = Path(args.log_file)

    log.info("Starting Engram → Supermemory migration")
    log.info("  DB          : %s", db_url)
    log.info("  Supermemory : %s", args.supermemory_url)
    log.info("  Batch size  : %d", args.batch_size)
    log.info("  Dry run     : %s", args.dry_run)

    migrate(
        db_url=db_url,
        supermemory_url=args.supermemory_url,
        api_key=args.api_key,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        log_path=log_path,
    )


if __name__ == "__main__":
    main()
