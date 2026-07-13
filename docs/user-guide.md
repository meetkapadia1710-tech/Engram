# User Guide

## What Engram does

Engram is long-term memory for your AI tools. Everything you (or your agents)
store becomes searchable by meaning, connected in a knowledge graph, and
retrievable as ready-to-use LLM context.

## The web app

- **Dashboard** — memory/entity/relationship counts, 14-day activity chart,
  top entities, recent memories.
- **Search** — ask in plain English. Three modes: *Hybrid* (default, best),
  *Semantic* (pure vector), *Keyword* (pure BM25). Click a result to see the
  ranking breakdown — every score component, explained.
- **Graph** — your memories (violet) and the people/technologies/concepts
  they mention (cyan), connected by detected relationships. Click a node for
  details.
- **Timeline** — everything you've stored, newest first, grouped by day,
  filterable by type.
- **⌘K** — command palette: jump anywhere or search without leaving the page.
- **New memory** — the + button or ⌘K → "New memory". Title, keywords,
  entities, and connections are extracted automatically.

## Using it from an agent (Python)

```python
from engram import Engram

em = Engram("http://localhost:8000")

# remember
em.create_memory("User prefers TypeScript over JavaScript for new services.",
                 type="conversation", tags=["preferences"])

# recall
for hit in em.search("what language does the user prefer?"):
    print(hit.score, hit.content)

# build LLM context (cited, token-budgeted)
ctx = em.retrieve_context("user's language preferences", max_tokens=800)
prompt = ctx["context"] + "\n\nQuestion: which language should I scaffold?"
```

## Memory hygiene

- **Types** matter: they're filterable in search and the timeline.
- **Tags** are yours; entities are extracted automatically.
- **Archive** old noise with the compress endpoint — archived memories keep
  their graph links but leave search results.
- **Delete** is permanent and audited.
