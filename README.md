# Engram

**The memory layer for AI. Every interaction becomes knowledge.**

Engram is a universal, self-hostable memory platform for AI agents and LLM applications. Instead of forgetting every conversation, your agents remember — semantically, temporally, and relationally.

```
Raw text ─▶ chunk ─▶ clean ─▶ embed ─▶ extract entities ─▶ detect relationships
        ─▶ store ─▶ update graph ─▶ update vectors ─▶ update search index
```

## Why Engram

- **Hybrid retrieval** — vector similarity + BM25 keyword search fused with Reciprocal Rank Fusion, then re-ranked by importance, recency, frequency, and relationship weight.
- **Knowledge graph** — every memory and every extracted entity (people, projects, technologies, organizations…) becomes a graph node; relationships (`mentions`, `references`, `related_to`, `belongs_to`, …) are detected automatically.
- **Temporal reasoning** — time-scoped recall ("what did I learn last week?"), recency decay, and a full memory timeline.
- **Provider-agnostic AI layer** — OpenAI, Anthropic, Gemini, or Ollama behind one abstraction; switch with an env var. Ships with a fully-local deterministic embedder so it works with **zero API keys**.
- **RAG-ready** — one call (`/v1/context`) assembles a cited, token-budgeted context block for any LLM prompt.
- **Production posture** — API-key auth, rate limiting, audit log, workspaces/multi-tenancy, OpenAPI, Docker, CI, tests.

## Monorepo layout

```
apps/web          Next.js 15 + React 19 frontend (dashboard, search, graph, timeline)
services/api      FastAPI backend (pipeline, hybrid search, graph, RAG)
sdk/python        Python SDK
sdk/typescript    TypeScript SDK
database/         SQL schema (PostgreSQL + pgvector) and ER docs
docker/           Dockerfiles
docs/             Architecture, API, deployment, contribution guides
scripts/          Dev & seed scripts
```

## Quickstart (local, no Docker)

```powershell
# backend — http://localhost:8000  (docs at /docs)
cd services/api
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000

# frontend — http://localhost:3000
cd apps/web
npm install
npm run dev

# seed demo data
python scripts/seed.py
```

By default Engram is powered by Supermemory Local for its storage engine — no external vector databases required. Point `SUPERMEMORY_URL` to your Supermemory instance to scale up. See [docs/deployment.md](docs/deployment.md) for more details.

## Quickstart (Docker)

```bash
docker compose up   # api :8000, web :3000, supermemory :6767, postgres, redis
```

## Documentation

- [Architecture](docs/architecture.md) — pipeline, ranking formula, graph model, ER diagram
- [API reference](docs/api.md) — REST endpoints (interactive OpenAPI at `/docs`)
- [Deployment](docs/deployment.md) — Docker, Postgres, provider configuration
- [Contributing](docs/contributing.md)
- [User guide](docs/user-guide.md)

## SDKs

```python
from engram import Engram
em = Engram("http://localhost:8000", api_key="...")
em.create_memory("Docker layers are cached by instruction order.", type="note")
hits = em.search("what did I learn about Docker?")
ctx  = em.retrieve_context("Docker best practices", max_tokens=1500)
```

```ts
import { Engram } from "@engram/sdk";
const em = new Engram({ baseUrl: "http://localhost:8000", apiKey: "..." });
await em.createMemory({ content: "…", type: "note" });
const hits = await em.search({ query: "docker" });
```

## License

MIT
