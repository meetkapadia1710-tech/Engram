"""Digital Twin engine.

Builds a continuously evolving user profile from workspace memories. The twin
captures coding/writing style, skills, productivity patterns, knowledge gaps,
and generates predictions about future interests.

How it works
------------
1. ``refresh(db, workspace_id)`` reads all non-archived memories.
2. Tech-entity frequency → skill graph (weighted by memory importance).
3. Memory type distribution → style metrics (code-heavy, document-heavy, etc.).
4. Hour-of-day creation timestamps → productivity heatmap.
5. Low-mention entities → knowledge gaps (entities seen only once).
6. Top-growth entities → predicted future interests.
7. All decision/task memories → decision history summary.

The result is stored in a single ``DigitalTwin`` row per workspace.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import observability
from .models import Entity, Memory, MemoryEntity
from .models_platform import DigitalTwin, EvolutionLog

# Entity kinds that represent learnable skills
_SKILL_KINDS = {"technology", "concept"}

# Minimum mention count to be considered a "gap" (low-knowledge area)
_GAP_THRESHOLD = 2

# Minimum mention count to be considered a strong skill
_SKILL_THRESHOLD = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _skill_weight(mention_count: int, importance_sum: float) -> float:
    """Combine frequency and importance into a [0, 1] skill score."""
    freq = min(math.log1p(mention_count) / math.log1p(50), 1.0)
    imp = min(importance_sum / (mention_count * 1.0), 1.0) if mention_count else 0.0
    return round(0.6 * freq + 0.4 * imp, 4)


def refresh(db: Session, workspace_id: str) -> DigitalTwin:
    """Recompute and persist the Digital Twin for a workspace."""
    with observability.timed("digital_twin.refresh"):
        memories = (
            db.execute(
                select(Memory)
                .where(Memory.workspace_id == workspace_id, Memory.archived == 0)
            )
            .scalars()
            .all()
        )
        memory_count = len(memories)

        # ------------------------------------------------------------------ #
        # 1. Skill graph from entity frequencies + importance
        # ------------------------------------------------------------------ #
        entity_rows = (
            db.execute(
                select(Entity, func.count(MemoryEntity.memory_id).label("cnt"))
                .join(MemoryEntity, MemoryEntity.entity_id == Entity.id)
                .where(Entity.workspace_id == workspace_id)
                .where(Entity.kind.in_(list(_SKILL_KINDS)))
                .group_by(Entity.id)
            )
            .all()
        )

        # importance_sum per entity
        importance_map: dict[str, float] = defaultdict(float)
        for mem in memories:
            for link in mem.entity_links:
                importance_map[link.entity_id] += mem.importance

        skills: dict[str, float] = {}
        gaps: list[str] = []
        for row in entity_rows:
            entity: Entity = row[0]
            cnt: int = row[1]
            score = _skill_weight(cnt, importance_map.get(entity.id, 0.0))
            skills[entity.name] = score
            if cnt <= _GAP_THRESHOLD:
                gaps.append(entity.name)

        # ------------------------------------------------------------------ #
        # 2. Style metrics from memory type distribution
        # ------------------------------------------------------------------ #
        type_counts: Counter = Counter(m.type for m in memories)
        total = max(len(memories), 1)
        style: dict = {
            "code_ratio": round(type_counts.get("code", 0) / total, 3),
            "document_ratio": round(type_counts.get("document", 0) / total, 3),
            "note_ratio": round(type_counts.get("note", 0) / total, 3),
            "meeting_ratio": round(type_counts.get("meeting_notes", 0) / total, 3),
            "research_ratio": round(type_counts.get("research_paper", 0) / total, 3),
            "dominant_type": type_counts.most_common(1)[0][0] if type_counts else "note",
            "avg_content_length": round(
                sum(len(m.content) for m in memories) / total, 1
            ),
        }

        # ------------------------------------------------------------------ #
        # 3. Productivity heatmap (hour-of-day buckets)
        # ------------------------------------------------------------------ #
        hour_counts: Counter = Counter()
        dow_counts: Counter = Counter()
        for m in memories:
            try:
                dt = datetime.fromisoformat(m.created_at)
                hour_counts[dt.hour] += 1
                dow_counts[dt.weekday()] += 1  # 0=Monday
            except ValueError:
                pass
        productivity = {
            "by_hour": {str(h): hour_counts.get(h, 0) for h in range(24)},
            "by_weekday": {
                str(d): dow_counts.get(d, 0)
                for d in range(7)
            },
            "peak_hour": hour_counts.most_common(1)[0][0] if hour_counts else None,
            "peak_weekday": dow_counts.most_common(1)[0][0] if dow_counts else None,
        }

        # ------------------------------------------------------------------ #
        # 4. Favourite tools — top-10 technology entities by score
        # ------------------------------------------------------------------ #
        favorite_tools = [
            k for k, _ in sorted(skills.items(), key=lambda kv: kv[1], reverse=True)
            if k in _get_tech_set(db, workspace_id)
        ][:10]

        # ------------------------------------------------------------------ #
        # 5. Predictions — entities with fastest recent growth
        # ------------------------------------------------------------------ #
        recent_entities: Counter = Counter()
        for mem in sorted(memories, key=lambda m: m.created_at, reverse=True)[:50]:
            for link in mem.entity_links:
                recent_entities[link.entity_id] += 1
        entity_id_to_name = {row[0].id: row[0].name for row in entity_rows}
        predictions = [
            entity_id_to_name[eid]
            for eid, _ in recent_entities.most_common(5)
            if eid in entity_id_to_name and entity_id_to_name[eid] not in skills
        ]

        # ------------------------------------------------------------------ #
        # 6. Decision history summary from task/meeting memories
        # ------------------------------------------------------------------ #
        decision_mems = [
            m for m in memories
            if m.type in ("task", "meeting_notes") and m.summary
        ]
        decision_summary = " | ".join(m.summary for m in decision_mems[:10])

        # ------------------------------------------------------------------ #
        # 7. Persist
        # ------------------------------------------------------------------ #
        twin = db.execute(
            select(DigitalTwin).where(DigitalTwin.workspace_id == workspace_id)
        ).scalar_one_or_none()
        if twin is None:
            twin = DigitalTwin(workspace_id=workspace_id)
            db.add(twin)

        twin.skills = skills
        twin.style = style
        twin.favorite_tools = favorite_tools
        twin.predictions = predictions
        twin.gaps = gaps[:20]
        twin.productivity = productivity
        twin.decision_summary = decision_summary[:2000]
        twin.memory_count_at_last_update = memory_count
        twin.updated_at = _now_iso()

        db.add(
            EvolutionLog(
                workspace_id=workspace_id,
                action="twin_refresh",
                detail_json=json.dumps(
                    {"memory_count": memory_count, "skills": len(skills)}
                ),
            )
        )
        db.flush()

    observability.count("digital_twin.refresh")
    return twin


def _get_tech_set(db: Session, workspace_id: str) -> set[str]:
    rows = db.execute(
        select(Entity.name)
        .where(Entity.workspace_id == workspace_id, Entity.kind == "technology")
    ).scalars().all()
    return set(rows)


def get_or_create(db: Session, workspace_id: str) -> DigitalTwin:
    """Return the existing twin or create a fresh one via refresh."""
    twin = db.execute(
        select(DigitalTwin).where(DigitalTwin.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if twin is None:
        twin = refresh(db, workspace_id)
    return twin
