# Engram API Reference

Interactive docs: **`http://localhost:8000/docs`** · spec: **`/openapi.json`**

Auth: open in dev mode. When `ENGRAM_API_KEYS` is set, send
`X-API-Key: <key>` or `Authorization: Bearer <key>`. All endpoints are
rate-limited (default 240 req/min per key/IP → HTTP 429).

## System

| Method | Path      | Description                          |
| ------ | --------- | ------------------------------------ |
| GET    | `/health` | Status, version, active AI providers |
| GET    | `/v1/types` | The 18 supported memory types      |

## Workspaces

| Method | Path                          | Description             |
| ------ | ----------------------------- | ----------------------- |
| POST   | `/v1/workspaces`              | Create (name, slug)     |
| GET    | `/v1/workspaces`              | List with memory counts |
| DELETE | `/v1/workspaces/{id}`         | Delete (cascades)       |
| GET    | `/v1/workspaces/{id}/analytics` | Counts, by-type, 14-day activity, top entities |
| GET    | `/v1/workspaces/{id}/audit`   | Audit log               |
| POST   | `/v1/workspaces/{id}/compress`| Archive stale memories  |

## Memories

| Method | Path                              | Description                     |
| ------ | --------------------------------- | ------------------------------- |
| POST   | `/v1/workspaces/{id}/memories`    | Ingest (runs the full pipeline) |
| GET    | `/v1/workspaces/{id}/memories`    | List (paginated, type filter)   |
| GET    | `/v1/memories/{id}`               | Fetch (bumps access count)      |
| PATCH  | `/v1/memories/{id}`               | Update (content re-embeds)      |
| DELETE | `/v1/memories/{id}`               | Delete                          |
| GET    | `/v1/memories/{id}/related`       | Graph-connected memories        |

**Create request**

```json
{
  "content": "Docker layers are cached by instruction order.",
  "type": "note",
  "title": "",
  "tags": ["devops"],
  "source": "https://docs.docker.com",
  "author": "meet"
}
```

## Search & retrieval

**`POST /v1/workspaces/{id}/search`**

```json
{
  "query": "what did I learn about docker?",
  "mode": "hybrid",
  "limit": 10,
  "types": ["note", "document"],
  "tags": ["devops"],
  "date_from": "2026-07-01T00:00:00+00:00"
}
```

Response hits carry `score` plus a `components` breakdown
(`similarity, bm25, rrf, importance, recency, frequency, relationship,
confidence`) so clients can explain rankings.

**`POST /v1/workspaces/{id}/context`** — RAG context builder: returns a
token-budgeted, `[n]`-cited context block plus the `sources` array.

**`GET /v1/workspaces/{id}/graph?center=<id>&hops=2`** — knowledge graph JSON
(`nodes`, `edges`) for visualization or traversal.

## Errors

| Code | Meaning                                  |
| ---- | ---------------------------------------- |
| 401  | Missing/invalid API key (when auth is on)|
| 404  | Workspace or memory not found            |
| 409  | Duplicate workspace slug                 |
| 422  | Validation failure (empty content, unknown type, bad mode) |
| 429  | Rate limit exceeded                      |
