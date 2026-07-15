# Engram

<div align="center">

**The memory layer for AI. Every interaction becomes knowledge.**

[![Tests](https://img.shields.io/badge/tests-115%20passed-brightgreen)](#testing)
[![CI](https://github.com/engram/engram/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](#quickstart)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](#license)
[![Powered by Supermemory](https://img.shields.io/badge/powered%20by-Supermemory-8B5CF6)](https://supermemory.ai)

</div>

Engram is a universal, self-hostable memory platform for AI agents and LLM applications. Instead of forgetting every conversation, your agents remember — **semantically, temporally, and relationally** — across every session, tool, and model.

Engram is an intelligent application layer built on top of **[Supermemory Local](https://supermemory.ai)**. Supermemory handles the heavy lifting of vector storage and semantic retrieval; Engram provides the higher-level platform: workspaces, knowledge graphs, multi-agent orchestration, workflow automation, RAG context assembly, and a full web dashboard.

```
  Your Agent / Application
               │
               ▼
    ┌─────────────────────┐
    │      Engram API      │  workspaces · search · graph · RAG
    │   (FastAPI :8000)    │  agents · workflows · plugins · eval
    └─────────────────────┘
               │
               ▼
    ┌─────────────────────┐
    │  Supermemory Local   │  vector storage · semantic search
    │     (:6767)          │  container tagging · v3 API
    └─────────────────────┘
```

---

## Why Engram

| Capability | Details |
|---|---|
| 🧠 **Supermemory Native** | Supermemory Local is the durable content + semantic search engine — no separate vector DB to run or manage |
| 🕸 **Knowledge Graph** | Every memory's extracted entities (people, projects, tech, orgs) become graph nodes, auto-linked by cosine similarity and co-occurrence |
| ⏱ **Temporal Reasoning** | Recency decay, time-scoped recall, full memory timeline, and `forgetAfter` TTL support via Supermemory container tags |
| 🤖 **Multi-Agent Orchestration** | Define agent teams with goals; Engram routes tasks and merges their conclusions back into memory |
| ⚡ **Workflow Automation** | Event-driven workflows triggered by memory events (MemoryCreated, SearchExecuted, …) |
| 🔌 **Plugin Marketplace** | First-party and third-party plugins extend the platform — install, enable/disable, roll back, per workspace |
| 🪄 **RAG-Ready** | `/v1/context` assembles a cited, token-budgeted context block for any LLM prompt in one HTTP call |
| 👤 **Digital Twin** | Infers skill scores, productivity patterns, cognitive gaps, and future predictions from your memory history |
| 📊 **AI Evaluation** | On-demand evaluation reports: retrieval quality, hallucination rate, grounding accuracy, NDCG ranking |
| 🔒 **Production Ready** | API-key auth, rate limiting, audit log, multi-tenancy, OpenAPI docs, Docker Compose, 115-test CI suite |

---

## Monorepo Layout

```
apps/web/           Next.js 15 + React 19 dashboard
  ├── search/         Semantic search UI
  ├── timeline/       Memory timeline
  ├── graph/          Interactive knowledge graph
  ├── agents/         Multi-agent run viewer
  ├── workflows/      Workflow builder
  ├── marketplace/    Plugin catalog
  ├── digital-twin/   Personal AI profile
  ├── observability/  Metrics & traces
  ├── events/         Real-time SSE event stream
  ├── settings/       Settings configuration
  └── tools/          Tool management

services/api/       FastAPI backend
  ├── app/routers/    memories · search · workspaces · agents · workflows
  │                   plugins · tools · events · intelligence · observability
  ├── app/pipeline.py Ingestion: clean → chunk → embed → keywords → entities
  ├── app/search.py   Hybrid search (vector + BM25 + RRF + re-ranking)
  ├── app/rag.py      RAG context builder
  ├── app/graph.py    Knowledge graph builder
  ├── app/db.py       MemoryStore abstraction → SupermemoryStore
  ├── app/supermemory_client.py  Supermemory v3 HTTP client
  ├── app/evaluation.py  AI Evaluation Engine
  ├── app/digital_twin.py Digital Twin profile generation
  ├── app/knowledge_evolution.py Knowledge evolution & insights
  ├── app/ai.py       LLM provider integrations
  └── app/tools.py    Tool execution engine

sdk/go/             Go SDK
  ├── engram/         High-level Engram API client
  └── supermemory/    Low-level Supermemory v3 client

sdk/cli/            Python CLI (engram workspace/memory/search/agent/…)
sdk/python/         Python SDK (Engram class)
sdk/typescript/     TypeScript SDK (@engram/sdk)

scripts/
  ├── seed.py                    Seed demo workspace & memories
  └── migrate_to_supermemory.py  Bulk-migrate SQLite → Supermemory

database/           SQL schema (Postgres + pgvector)
docker/             Dockerfiles (api · web)
docs/               Architecture · API · deployment · contributing
```

---

## Quickstart

### Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.11+ | Engram API |
| Node.js | 18+ | Web dashboard |
| Supermemory Local | latest | Durable storage + semantic search (**must be running before the API** — the API's `/health` reports `degraded` and memory create/update/delete/search will fail without it) |
| Docker + Compose | optional | Only for Option A |

### Option A — Docker (recommended)

```bash
docker compose up
```

Services started:

| Service | URL | Description |
|---|---|---|
| Engram API | http://localhost:8000 | REST API + OpenAPI docs at `/docs` |
| Web Dashboard | http://localhost:3000 | Next.js frontend |
| Supermemory Local | http://localhost:6767 | Vector storage engine |
| Postgres | localhost:5432 | Workspace & audit metadata |

### Option B — Local (no Docker)

Start these **in order** — each later step depends on the one before it.

**1. Start Supermemory Local**

```bash
# via npm
npm install -g supermemory
supermemory local
# → prints your API key and listens on :6767
```

**2. Start the API**

```bash
cd services/api
pip install -r requirements.txt

# point Engram at your local Supermemory (PowerShell)
$env:SUPERMEMORY_URL = "http://localhost:6767"
$env:SUPERMEMORY_API_KEY = "<key-from-step-1>"   # optional if open mode

# bash/zsh equivalent:
# export SUPERMEMORY_URL="http://localhost:6767"
# export SUPERMEMORY_API_KEY="<key-from-step-1>"

py -m uvicorn app.main:app --port 8000 --reload
# → API docs at http://localhost:8000/docs
```

**3. Start the web dashboard**

```bash
cd apps/web
npm install
npm run dev
# → Dashboard at http://localhost:3000
```

**4. Seed demo data**

```bash
py scripts/seed.py
```

### Verify it's working

```bash
# Health — "status" is "ok" only when Supermemory is actually reachable
curl http://localhost:8000/health

# Create a workspace
curl -X POST http://localhost:8000/v1/workspaces \
  -H "Content-Type: application/json" \
  -d '{"name": "Demo"}'
# → {"id": "<ws-id>", "name": "Demo", "slug": "demo", ...}

# Store a memory (runs the full pipeline: clean → chunk → embed → entities → Supermemory)
curl -X POST http://localhost:8000/v1/workspaces/<ws-id>/memories \
  -H "Content-Type: application/json" \
  -d '{"content": "Docker layers are cached by instruction order.", "type": "note"}'

# Search it (Supermemory indexes asynchronously — allow a few seconds after
# creation before it's guaranteed to show up in results)
curl -X POST http://localhost:8000/v1/workspaces/<ws-id>/search \
  -H "Content-Type: application/json" \
  -d '{"query": "docker caching"}'
```

---

## Supermemory Integration

Engram is a **dual-store architecture**: Supermemory Local is the durable, semantically-searchable content store; a local SQLite mirror is the source of truth for everything the knowledge graph and ranking depend on (entity identity, relationships, access/recency signals). Reads (list, get, graph, analytics) are served locally and stay correct even if Supermemory is temporarily unreachable; only create/update/delete and semantic search candidate discovery talk to Supermemory.

Verified against a live Supermemory Local instance (the real **v3 API**, not the docs-implied v4 — `POST /v3/documents`, `POST /v3/search`, `GET /v3/health`). Engram maps its workspace/memory model to Supermemory's `containerTags` + `metadata` model:

| Engram field | Supermemory field | Notes |
|---|---|---|
| `workspace_id` | `containerTags` (array) | Each workspace = one container tag |
| `content` | `content` | Memory body (up to 10k chars) |
| `id` | `customId` | Deterministic ID for idempotent writes; also usable as the lookup id |
| `type`, `title`, `tags`, … | `metadata.*` | Metadata values must be scalars or flat string arrays — entities are flattened to `"name::kind"` strings, since Supermemory's schema rejects nested arrays |
| `created_at` | `metadata.created_at` | Original timestamp preserved |

Indexing is asynchronous: a document can briefly reject an update/delete with `409 "Document is still processing"` right after creation. Engram retries once, then treats it as non-fatal — the local mirror already reflects the change.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SUPERMEMORY_URL` | `http://localhost:6767` | Supermemory Local base URL |
| `SUPERMEMORY_API_KEY` | _(empty)_ | Bearer token (leave empty for open/dev mode) |
| `SUPERMEMORY_CONTAINER` | `default-container` | Fallback container tag |
| `SUPERMEMORY_TIMEOUT` | `10` | HTTP request timeout (seconds) |

### Other Configuration

| Variable | Default | Description |
|---|---|---|
| `ENGRAM_DATABASE_URL` | `sqlite:///data/engram.db` | Postgres URL for workspace/audit metadata |
| `ENGRAM_API_KEYS` | _(empty = open)_ | Comma-separated API keys to require auth |
| `ENGRAM_EMBEDDING_PROVIDER` | `local` | `local` · `openai` · `gemini` · `ollama` |
| `ENGRAM_GENERATION_PROVIDER` | `local` | `local` · `openai` · `anthropic` · `gemini` · `ollama` |
| `ENGRAM_CORS_ORIGINS` | `http://localhost:3000` | Allowed CORS origins |
| `OPENAI_API_KEY` | _(empty)_ | Required if using OpenAI provider |
| `ANTHROPIC_API_KEY` | _(empty)_ | Required if using Anthropic provider |
| `GEMINI_API_KEY` | _(empty)_ | Required if using Gemini provider |

### Cognitive Ranking Configuration

Engram re-ranks Supermemory's baseline semantic results using a configurable cognitive formula. You can tune these weights via environment variables without changing code:

| Variable | Default | Description |
|---|---|---|
| `ENGRAM_WEIGHT_SIMILARITY` | `0.42` | Weight of Supermemory's raw vector similarity |
| `ENGRAM_WEIGHT_IMPORTANCE` | `0.16` | Weight of the memory's intrinsic importance score |
| `ENGRAM_WEIGHT_RECENCY`    | `0.16` | Weight of temporal recency decay |
| `ENGRAM_WEIGHT_FREQUENCY`  | `0.10` | Weight of access frequency (log-scaled) |
| `ENGRAM_WEIGHT_RELATIONSHIP`| `0.10`| Weight of graph centrality (relationships) |
| `ENGRAM_RECENCY_HALF_LIFE_DAYS` | `14` | How many days until a memory's recency score halves |

---

## Migrating Existing SQLite Data

If you have memories in a pre-migration `data/engram.db`, run the one-time migration script:

```bash
# Preview what will be migrated (no writes)
py scripts/migrate_to_supermemory.py --dry-run

# Run the migration
py scripts/migrate_to_supermemory.py \
  --supermemory-url http://localhost:6767 \
  --api-key <your-key> \
  --batch-size 50

# Resume interrupted runs safely — already-migrated IDs are tracked in:
#   data/migration_log.json
```

---

## Benchmarks & Evaluation

Engram ships with a built-in **AI Evaluation Engine** to empirically prove that its cognitive re-ranking improves upon raw baseline vector search. 

Instead of static benchmarks, trigger the `/v1/workspaces/{ws}/evaluation/run` endpoint at any time. It will dynamically evaluate your live workspace and generate an `EvaluationReport` containing:
- `retrieval_quality`: The relevance of returned context blocks.
- `ranking_ndcg`: The Normalized Discounted Cumulative Gain, proving the re-ranking algorithm's effectiveness against baseline semantic search.
- `hallucination_rate` and `grounding_accuracy`

---

## API Reference

Interactive docs at **http://localhost:8000/docs**

### Core Endpoints

```
# Workspaces
POST   /v1/workspaces                     Create workspace
GET    /v1/workspaces                     List workspaces
DELETE /v1/workspaces/{id}                Delete workspace

# Memories
POST   /v1/workspaces/{ws}/memories       Create memory (runs full ingestion pipeline)
GET    /v1/workspaces/{ws}/memories       List memories (filter by type, archived)
GET    /v1/memories/{id}                  Get memory (increments access_count)
PATCH  /v1/memories/{id}                  Update memory (content, tags, importance…)
DELETE /v1/memories/{id}                  Delete memory
GET    /v1/memories/{id}/related          Semantically related memories

# Search & RAG
POST   /v1/workspaces/{ws}/search         Hybrid cognitive search (Semantic + Re-ranking)
POST   /v1/workspaces/{ws}/context        Build RAG context block (cited, token-budgeted)
GET    /v1/workspaces/{ws}/graph          Knowledge graph (nodes + edges)

# Intelligence & Benchmarks
GET    /v1/workspaces/{ws}/digital-twin            Get AI profile
POST   /v1/workspaces/{ws}/digital-twin/refresh    Recompute profile
POST   /v1/workspaces/{ws}/evolution/run           Full knowledge evolution pass
POST   /v1/workspaces/{ws}/evolution/merge-duplicates
POST   /v1/workspaces/{ws}/evolution/generate-insights
POST   /v1/workspaces/{ws}/evaluation/run          Run AI quality evaluation (NDCG benchmarks)

# Agents & Workflows
POST   /v1/workspaces/{ws}/agents/run     Start multi-agent run
GET    /v1/workspaces/{ws}/workflows      List workflows
POST   /v1/workspaces/{ws}/workflows/{id}/trigger

# Marketplace
GET    /v1/catalog                        Browse plugin catalog
POST   /v1/workspaces/{ws}/plugins/{slug}/install

# Tools
GET    /v1/tools                              List all registered tools
POST   /v1/workspaces/{ws}/tools/{name}       Execute a tool
GET    /v1/workspaces/{ws}/tool-executions    Execution history

# Observability
GET    /metrics                           Prometheus metrics
GET    /v1/metrics                        JSON snapshot
GET    /v1/workspaces/{ws}/analytics      Memory stats + activity
GET    /v1/workspaces/{ws}/audit          Audit log
```

---

## SDKs

### Python CLI

```bash
engram workspace list
engram workspace create "My Project"

engram memory add --workspace <ws-id> --type note --tags "k8s,infra"
# → prompts for content, stores to Supermemory

engram search "kubernetes liveness probes" --workspace <ws-id> --limit 5
engram context "docker best practices" --workspace <ws-id>

engram agent run "Analyse our architecture decisions" --workspace <ws-id>
engram evolution --workspace <ws-id>
engram eval run --workspace <ws-id>
engram metrics
```

### Python SDK

```python
from engram import Engram

em = Engram("http://localhost:8000", api_key="...")

# Store a memory (runs full pipeline: clean → embed → entities → Supermemory)
mem = em.memories.create(workspace_id, content="Docker layers are cached by instruction order.", type="note")

# Semantic search
hits = em.search.search(workspace_id, "docker layer caching", limit=5)

# RAG context block for an LLM prompt
ctx = em.search.context(workspace_id, "docker best practices", max_tokens=1500)
print(ctx["context"])   # Cited, token-budgeted block ready to paste into a prompt
```

### TypeScript SDK

```ts
import { Engram } from "@engram/sdk";

const em = new Engram({ baseUrl: "http://localhost:8000", apiKey: "..." });

await em.memories.create(workspaceId, {
  content: "Use hexagonal architecture to separate domain from infra.",
  type: "note",
  tags: ["architecture"],
});

const { results } = await em.search.search(workspaceId, { query: "hexagonal architecture", limit: 5 });
const { context } = await em.search.context(workspaceId, { query: "architecture patterns", maxTokens: 2000 });
```

### Go SDK — Supermemory Direct

```go
import "github.com/engram/sdk-go/supermemory"

client := supermemory.NewClient(supermemory.Config{
    BaseURL: "http://localhost:6767",
    APIKey:  os.Getenv("SUPERMEMORY_API_KEY"),
})

// Create a memory
resp, err := client.CreateMemory(ctx, "my-project", []supermemory.Memory{
    {
        Content: "Use hexagonal architecture for clean separation of concerns.",
        Metadata: map[string]any{
            "type":    "architecture",
            "session": "session-123",
        },
    },
})

// Search
results, err := client.SearchMemory(ctx, supermemory.SearchRequest{
    Query:        "hexagonal architecture",
    ContainerTag: "my-project",
    Limit:        5,
})

// Update
_, err = client.UpdateMemory(ctx, "my-project", results.Results[0].ID, "Updated content...")

// Delete (soft — marks as forgotten in Supermemory)
_, err = client.DeleteMemory(ctx, results.Results[0].ID)
```

### Go SDK — Engram API

```go
import "github.com/engram/sdk-go/engram"

client := engram.New("http://localhost:8000", engram.WithAPIKey("..."))

// Workspaces
ws, _ := client.Workspaces.Create(ctx, "My Project", "my-project")

// Memories
mem, _ := client.Memories.Create(ctx, ws.ID, engram.MemoryCreate{
    Content: "Kubernetes liveness probes restart containers on failure.",
    Type:    "note",
    Tags:    []string{"k8s", "ops"},
})

// Search
hits, _ := client.Search.Search(ctx, ws.ID, "kubernetes health checks", 10)
ctx_block, _ := client.Search.Context(ctx, ws.ID, "k8s best practices", 2000)

// Agents
run, _ := client.Agents.Run(ctx, ws.ID, "Analyse our deployment strategy", nil)
```

---

## Ingestion Pipeline

Every memory passes through the full pipeline on creation:

```
raw text
   │
   ▼  clean_text()         normalise whitespace, strip CRLF
   │
   ▼  chunk_text()         paragraph-aware sliding window (900 chars, 120 overlap)
   │
   ▼  embed()              local (256-dim hash) | OpenAI | Gemini | Ollama
   │
   ▼  extract_keywords()   top-8 unstemmed terms by frequency
   │
   ▼  extract_entities()   heuristic NER: tech lexicon + capitalized spans + emails/URLs
   │
   ▼  score_importance()   length + type + signal keywords → [0.2, 0.95]
   │
   ▼  generate_summary()   LLM summary for content > 280 chars (optional)
   │
   ▼  resync_entities_and_relationships()   local SQLite mirror: entity
   │                                        identity + graph edges (also
   │                                        re-run on every content edit)
   │
   ▼  SupermemoryStore.save()   POST /v3/documents  → Supermemory Local
```

---

## Testing

```bash
cd services/api
pip install -r requirements.txt pytest
py -m pytest tests/ -v
# → 115 passed in ~10s (an in-memory Supermemory mock stands in for the real
#   server, shaped to match its actual v3 responses — no server needed)
```

| File | Tests | Covers |
|---|---|---|
| `test_platform_api.py` | 20 | End-to-end HTTP surface: marketplace, agents, workflows, tools, events, observability, digital twin, evolution, evaluation |
| `test_api.py` | 14 | Memory CRUD lifecycle, search, context, graph, analytics, audit log |
| `test_pipeline.py` | 13 | Chunking, embeddings, entity extraction, importance scoring, content-edit resync |
| `test_workflows.py` | 13 | Interpolation, step types, conditions, loops, retries, event triggers |
| `test_kernel.py` | 11 | Plugin publish/install/update/rollback lifecycle, permissions, quotas, feature flags |
| `test_search.py` | 7 | BM25, hybrid ranking, type/tag filters, access count, recency decay |
| `test_events.py` | 7 | Emit/subscribe, retry-to-dead-letter, replay |
| `test_tools.py` | 7 | Sandbox permission gates, fs jail + path traversal, http allowlist |
| `test_knowledge_evolution.py` | 7 | Decay, duplicate merge, contradiction detection, insight generation |
| `test_agents.py` | 6 | Multi-agent plan → research → debate → vote → merge lifecycle |
| `test_digital_twin.py` | 5 | Skill graph, style ratios, knowledge gaps |
| `test_evaluation.py` | 5 | Retrieval NDCG, grounding accuracy, agent success rate |

Every fix in this repo's history started from a failing test written against the *real* Supermemory Local API contract (verified live, not assumed) — including the async-indexing race on delete/update, which a mock alone would never have caught.

---

## Documentation

| Doc | Description |
|---|---|
| [Architecture](docs/architecture.md) | Pipeline, ranking formula, graph model, ER diagram |
| [API Reference](docs/api.md) | All REST endpoints (interactive at `/docs`) |
| [Deployment](docs/deployment.md) | Docker, Postgres, AI provider configuration |
| [Contributing](docs/contributing.md) | How to add features, run tests, open PRs |
| [User Guide](docs/user-guide.md) | End-to-end usage walkthrough |

---

## License

MIT
