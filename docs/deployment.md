# Deployment

## Local (zero dependencies)

```powershell
cd services/api
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000

cd apps/web
npm install && npm run dev        # http://localhost:3000
python scripts/seed.py            # optional demo data
```

Runs on SQLite (WAL) + the built-in local embedder. No keys, no services.

## Docker Compose (Postgres + pgvector + Redis)

```bash
docker compose up --build
```

- `api` → :8000, `web` → :3000, `postgres` (pgvector/pg17) → :5432, `redis` → :6379
- `database/schema.sql` is applied on first Postgres boot (includes the HNSW
  vector index).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENGRAM_DATABASE_URL` | `sqlite:///<repo>/data/engram.db` | Any SQLAlchemy URL; use `postgresql+psycopg://…` for Postgres |
| `ENGRAM_EMBEDDING_PROVIDER` | `local` | `local` \| `openai` \| `gemini` \| `ollama` |
| `ENGRAM_GENERATION_PROVIDER` | `local` | + `anthropic` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | — | provider credentials |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | local models |
| `ENGRAM_API_KEYS` | — (open dev mode) | comma-separated accepted keys; enables auth |
| `ENGRAM_RATE_LIMIT` | `240` | requests/min per key/IP |
| `ENGRAM_CORS_ORIGINS` | `http://localhost:3000` | comma-separated |
| `ENGRAM_RECENCY_HALF_LIFE_DAYS` | `14` | ranking recency decay |
| `NEXT_PUBLIC_API_URL` (web) | `http://localhost:8000` | API base for the frontend |

> ⚠️ Changing the embedding provider changes vector space — re-ingest (PATCH
> content or re-create memories) after switching.

## Cloud targets

- **API**: any container host (Fly.io, Railway, AWS ECS, Cloud Run). One
  stateless container + Postgres. Health check: `GET /health`.
- **Web**: Vercel (`apps/web`, set `NEXT_PUBLIC_API_URL`) or the provided
  Docker image.
- **CI**: `.github/workflows/ci.yml` runs API tests, web build, SDK builds,
  and the Docker image build on every push/PR.

## Production checklist

- [ ] Set `ENGRAM_API_KEYS` (long random strings; rotate by adding/removing)
- [ ] Postgres with backups; apply `database/schema.sql`
- [ ] Restrict `ENGRAM_CORS_ORIGINS` to your web origin
- [ ] Put the API behind TLS (reverse proxy / platform TLS)
- [ ] Ship logs somewhere durable — the API logs structured JSON to stdout
