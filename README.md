# Engram

**The memory layer for AI. Every interaction becomes knowledge.**

Engram is a universal, self-hostable memory platform for AI agents and LLM applications. Instead of forgetting every conversation, your agents remember — semantically, temporally, and relationally.

Engram is an intelligent client and application layer that sits on top of **Supermemory Local**. While Supermemory handles the heavy lifting of vector storage and retrieval, Engram provides the higher-level capabilities: API routing, workspaces, knowledge graphs, and RAG context assembly.

```text
Claude / Codex / Cursor
            │
            ▼
        Engram CLI
            │
            ▼
     Memory Service Layer
            │
            ▼
   Supermemory Local API
            │
            ▼
    Supermemory Storage
```

## Why Engram

- **Supermemory Native** — Uses Supermemory Local as its primary storage engine, meaning no separate vector databases or complex indexing infrastructure to manage.
- **Knowledge graph** — Every memory and every extracted entity (people, projects, technologies, organizations…) becomes a graph node, built automatically from metadata.
- **Temporal reasoning** — Time-scoped recall, recency decay, and a full memory timeline powered by Supermemory's container tagging.
- **Provider-agnostic AI layer** — OpenAI, Anthropic, Gemini, or Ollama behind one abstraction; switch with an env var. Ships with a fully-local deterministic embedder so it works with **zero API keys**.
- **RAG-ready** — one call (`/v1/context`) assembles a cited, token-budgeted context block for any LLM prompt.
- **Production posture** — API-key auth, rate limiting, audit log, workspaces/multi-tenancy, OpenAPI, Docker, CI, tests.

## Monorepo layout

```
apps/web          Next.js 15 + React 19 frontend (dashboard, search, graph, timeline)
services/api      FastAPI backend (pipeline, hybrid search, graph, RAG)
sdk/python        Python SDK
sdk/typescript    TypeScript SDK
database/         Supermemory configuration and schemas
docker/           Dockerfiles including Supermemory Local
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

By default Engram is powered entirely by Supermemory Local for its storage engine — no external vector databases or SQL engines required. Point `SUPERMEMORY_URL` to your Supermemory instance to scale up. See [docs/deployment.md](docs/deployment.md) for more details.

## Quickstart (Docker)

```bash
docker compose up   # api :8000, web :3000, supermemory :6767, redis
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
