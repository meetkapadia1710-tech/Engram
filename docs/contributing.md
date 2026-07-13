# Contributing

## Setup

```bash
git clone <repo> && cd engram
cd services/api && pip install -r requirements.txt pytest
cd ../../apps/web && npm install
```

## Development loop

```bash
# backend with reload
cd services/api && python -m uvicorn app.main:app --port 8000 --reload

# frontend
cd apps/web && npm run dev

# tests — must be green before every PR
cd services/api && python -m pytest tests -q
cd apps/web && npm run build
```

## Project conventions

- **Backend**: SQLAlchemy 2.x typed mappings, Pydantic v2 schemas, routers
  thin / logic in `pipeline.py` · `search.py` · `graph.py` · `rag.py`.
  Docstrings explain *why*, not *what*.
- **Frontend**: server components by default; `"use client"` only where
  interactivity requires it. Design tokens live in `app/globals.css`
  (`@theme`); no inline hex colors.
- **Commits**: conventional commits (`feat:`, `fix:`, `docs:`, `test:`).
- **Tests**: every new endpoint gets a happy-path test and at least one
  malformed-input test. Pipeline/search changes need unit coverage.

## Adding an AI provider

1. Implement `embed(texts) -> list[vector]` and/or `generate(prompt) -> str`
   in `services/api/app/ai.py`.
2. Register it in `_EMBEDDERS` / `_GENERATORS`.
3. Document the env vars in `docs/deployment.md`.

No other file should need to change — that's the point of the abstraction.
