"""Environment-driven configuration.

Every knob has a safe local default so a fresh clone runs with zero setup:
SQLite storage, the built-in deterministic embedder, no auth. Production
deployments override via ENGRAM_* environment variables (see docs/deployment.md).
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("ENGRAM_DATA_DIR", REPO_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    database_url: str = os.environ.get(
        "ENGRAM_DATABASE_URL", f"sqlite:///{DATA_DIR / 'engram.db'}"
    )

    # AI layer -------------------------------------------------------------
    # embedding: local | openai | gemini | ollama
    embedding_provider: str = os.environ.get("ENGRAM_EMBEDDING_PROVIDER", "local")
    # generation (summaries/titles): local | openai | anthropic | gemini | ollama
    generation_provider: str = os.environ.get("ENGRAM_GENERATION_PROVIDER", "local")

    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")
    ollama_base_url: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    openai_embedding_model: str = os.environ.get(
        "ENGRAM_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
    )
    ollama_embedding_model: str = os.environ.get(
        "ENGRAM_OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"
    )
    generation_model: str = os.environ.get("ENGRAM_GENERATION_MODEL", "")

    local_embedding_dim: int = int(os.environ.get("ENGRAM_LOCAL_EMBEDDING_DIM", "256"))

    # Security -------------------------------------------------------------
    # Comma-separated list of accepted API keys. Empty = open dev mode.
    api_keys: list[str] = [
        k.strip() for k in os.environ.get("ENGRAM_API_KEYS", "").split(",") if k.strip()
    ]
    rate_limit_per_minute: int = int(os.environ.get("ENGRAM_RATE_LIMIT", "240"))
    cors_origins: list[str] = [
        o.strip()
        for o in os.environ.get(
            "ENGRAM_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if o.strip()
    ]

    # Search / ranking weights ----------------------------------------------
    w_similarity: float = 0.42
    w_importance: float = 0.16
    w_recency: float = 0.16
    w_frequency: float = 0.10
    w_relationship: float = 0.10
    w_confidence: float = 0.06
    recency_half_life_days: float = float(
        os.environ.get("ENGRAM_RECENCY_HALF_LIFE_DAYS", "14")
    )


settings = Settings()
