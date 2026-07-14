"""First-party marketplace apps.

Each app is pure manifest: prompts, a workflow, and UI hints. All capability
comes from platform APIs (memory, search, context, tools, agents) gated by
the permissions it requests — the marketplace contract every third-party app
follows too. Seeded idempotently at startup.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .kernel import publish
from .models_platform import Plugin

FIRST_PARTY: list[dict] = [
    {
        "slug": "research-assistant",
        "name": "Research Assistant",
        "kind": "app",
        "description": "Collects sources on a topic, builds cited briefs from your memory, and files new findings back as research memories.",
        "permissions": ["memory.read", "memory.write", "search", "context", "agents.run"],
        "prompts": {
            "brief": "Using only the provided memory context, write a cited research brief on: {topic}. Cite as [n]. List open questions at the end.",
        },
        "workflows": [{
            "name": "Research brief",
            "steps": [
                {"type": "context", "query": "{topic}", "max_tokens": 2000, "out": "ctx"},
                {"type": "summarize", "text": "{ctx.context}", "out": "brief"},
                {"type": "create_memory", "content": "{brief}", "memory_type": "research_paper", "tags": ["brief"]},
            ],
        }],
        "ui": {"icon": "🔬", "accent": "#7c8cff"},
    },
    {
        "slug": "meeting-assistant",
        "name": "Meeting Assistant",
        "kind": "app",
        "description": "Turns meeting notes into decisions, action items, and follow-up memories; recalls what was agreed last time.",
        "permissions": ["memory.read", "memory.write", "search", "context"],
        "prompts": {
            "minutes": "Extract decisions, owners, and action items from these notes:\n{notes}",
            "recall": "What did we decide about {topic} in past meetings?",
        },
        "workflows": [{
            "name": "Process meeting notes",
            "trigger_event": "MemoryCreated",
            "steps": [
                {"type": "condition", "left": "{event.type}", "op": "==", "right": "meeting_notes"},
                {"type": "summarize", "text": "{event.title}", "out": "summary"},
            ],
        }],
        "ui": {"icon": "📅", "accent": "#22d3ee"},
    },
    {
        "slug": "coding-assistant",
        "name": "Coding Assistant",
        "kind": "app",
        "description": "Remembers your architecture decisions, code snippets, and gotchas; answers 'how did we solve this last time?'.",
        "permissions": ["memory.read", "memory.write", "search", "context", "graph.read"],
        "prompts": {
            "recall": "Find prior solutions, decisions, and gotchas relevant to: {problem}",
        },
        "ui": {"icon": "⌨️", "accent": "#4ade80"},
    },
    {
        "slug": "sales-intelligence",
        "name": "Sales Intelligence",
        "kind": "app",
        "description": "Tracks accounts, conversations, and commitments; briefs you before every call from memory.",
        "permissions": ["memory.read", "memory.write", "search", "context"],
        "prompts": {
            "brief": "Build a pre-call brief for {account}: relationship history, open commitments, risks.",
        },
        "ui": {"icon": "📈", "accent": "#fbbf24"},
    },
    {
        "slug": "support-assistant",
        "name": "Customer Support Assistant",
        "kind": "app",
        "description": "Learns every resolved ticket; suggests grounded answers with citations to past resolutions.",
        "permissions": ["memory.read", "memory.write", "search", "context"],
        "prompts": {
            "suggest": "Suggest a support reply for: {ticket}. Ground every claim in cited past resolutions.",
        },
        "ui": {"icon": "🎧", "accent": "#f472b6"},
    },
    {
        "slug": "personal-km",
        "name": "Personal Knowledge Manager",
        "kind": "app",
        "description": "Daily digest, knowledge-gap detection, and spaced resurfacing of things you're about to forget.",
        "permissions": ["memory.read", "search", "context", "workflows.run"],
        "workflows": [{
            "name": "Daily digest",
            "steps": [
                {"type": "search", "query": "today", "limit": 20, "out": "recent"},
                {"type": "summarize", "text": "{recent}", "out": "digest"},
                {"type": "create_memory", "content": "Daily digest: {digest}", "memory_type": "note", "tags": ["digest"]},
            ],
        }],
        "ui": {"icon": "🧠", "accent": "#7c8cff"},
    },
    {
        "slug": "education-assistant",
        "name": "Education Assistant",
        "kind": "app",
        "description": "Builds course memories, quizzes you from your own notes, and tracks concept mastery on the skill graph.",
        "permissions": ["memory.read", "memory.write", "search", "graph.read"],
        "ui": {"icon": "🎓", "accent": "#22d3ee"},
    },
    {
        "slug": "legal-assistant",
        "name": "Legal Assistant",
        "kind": "app",
        "description": "Clause and precedent recall over your document memories, with mandatory citation of sources.",
        "permissions": ["memory.read", "search", "context"],
        "ui": {"icon": "⚖️", "accent": "#8b91a3"},
    },
    {
        "slug": "finance-assistant",
        "name": "Finance Assistant",
        "kind": "app",
        "description": "Remembers invoices, budgets, and decisions; answers spend questions from memory (never advice).",
        "permissions": ["memory.read", "memory.write", "search"],
        "ui": {"icon": "🧾", "accent": "#4ade80"},
    },
    {
        "slug": "prompt-pack-starter",
        "name": "Starter Prompt Pack",
        "kind": "prompt_pack",
        "description": "Battle-tested retrieval and summarization prompts for memory-grounded agents.",
        "permissions": [],
        "prompts": {
            "grounded_answer": "Answer strictly from the memory context. Cite [n]. If absent, say 'not in memory'.",
            "merge": "Merge these findings into one conclusion; note disagreements explicitly.",
        },
        "ui": {"icon": "✨", "accent": "#fbbf24"},
    },
]


def seed_catalog(db: Session) -> int:
    """Publish any first-party app not yet in the catalog. Returns count added."""
    added = 0
    for manifest in FIRST_PARTY:
        exists = db.execute(
            select(Plugin).where(Plugin.slug == manifest["slug"])
        ).scalar_one_or_none()
        if exists is None:
            publish(db, manifest, version="1.0.0", author="Engram", first_party=True)
            added += 1
    if added:
        db.commit()
    return added
