"""Knowledge evolution: decay, duplicate merge, contradiction detection,
insight generation."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import knowledge_evolution as evo
from app.models import Memory, Workspace
from app.models_platform import EvolutionLog
from app.pipeline import ingest_memory


def _ws(session, slug="evo-ws"):
    ws = Workspace(name=slug, slug=slug)
    session.add(ws)
    session.flush()
    return ws


def _backdate(mem: Memory, days: int) -> None:
    mem.created_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_apply_decay_lowers_importance_of_old_unused_memories(session):
    ws = _ws(session)
    mem = ingest_memory(session, workspace_id=ws.id,
                        content="An old note nobody has looked at in a while.")
    session.flush()
    _backdate(mem, evo.DECAY_AFTER_DAYS + 30)
    before = mem.importance

    n = evo.apply_decay(session, ws.id)
    assert n == 1
    assert mem.importance < before

    logs = session.execute(
        select(EvolutionLog).where(EvolutionLog.action == "decay", EvolutionLog.memory_id == mem.id)
    ).scalars().all()
    assert len(logs) == 1


def test_apply_decay_skips_recent_memories(session):
    ws = _ws(session, "evo-ws-2")
    mem = ingest_memory(session, workspace_id=ws.id, content="A brand new note.")
    session.flush()
    n = evo.apply_decay(session, ws.id)
    assert n == 0


def test_merge_duplicates_archives_the_lower_importance_one(session):
    ws = _ws(session, "evo-ws-3")
    a = ingest_memory(session, workspace_id=ws.id,
                      content="Docker layer caching speeds up CI builds significantly.")
    b = ingest_memory(session, workspace_id=ws.id,
                      content="Docker layer caching speeds up CI builds significantly.")
    session.flush()
    a.importance, b.importance = 0.4, 0.9

    merged = evo.merge_duplicates(session, ws.id)
    assert len(merged) == 1
    assert merged[0]["keeper_id"] == b.id
    assert merged[0]["dupe_id"] == a.id
    assert a.archived == 1
    assert b.archived == 0


def test_merge_duplicates_dry_run_does_not_archive(session):
    ws = _ws(session, "evo-ws-4")
    a = ingest_memory(session, workspace_id=ws.id, content="Identical content here for dupes.")
    b = ingest_memory(session, workspace_id=ws.id, content="Identical content here for dupes.")
    session.flush()

    merged = evo.merge_duplicates(session, ws.id, dry_run=True)
    assert len(merged) == 1
    assert a.archived == 0 and b.archived == 0


def test_detect_contradictions_flags_opposing_similar_memories(session):
    ws = _ws(session, "evo-ws-5")
    ingest_memory(session, workspace_id=ws.id,
                  content="The deployment pipeline is stable and reliable.")
    ingest_memory(session, workspace_id=ws.id,
                  content="The deployment pipeline is not stable and reliable.")
    session.flush()

    flagged = evo.detect_contradictions(session, ws.id)
    assert len(flagged) >= 1

    logs = session.execute(
        select(EvolutionLog).where(EvolutionLog.action == "contradiction")
    ).scalars().all()
    assert len(logs) == len(flagged)


def test_generate_insights_creates_synthesis_for_entity_cluster(session):
    ws = _ws(session, "evo-ws-6")
    for i in range(3):
        ingest_memory(session, workspace_id=ws.id,
                      content=f"Docker note number {i}: layer caching and image builds.")
    session.flush()

    before_count = len(session.execute(
        select(Memory).where(Memory.workspace_id == ws.id)
    ).scalars().all())

    created = evo.generate_insights(session, ws.id, max_insights=3)
    assert len(created) >= 1

    after_count = len(session.execute(
        select(Memory).where(Memory.workspace_id == ws.id)
    ).scalars().all())
    assert after_count == before_count + len(created)

    logs = session.execute(
        select(EvolutionLog).where(EvolutionLog.action == "insight_generated")
    ).scalars().all()
    assert len(logs) == len(created)


def test_run_full_evolution_returns_summary(session):
    ws = _ws(session, "evo-ws-7")
    ingest_memory(session, workspace_id=ws.id, content="Some workspace content to evolve.")
    session.flush()

    summary = evo.run_full_evolution(session, ws.id)
    assert set(summary) >= {
        "decayed", "merged", "summaries_improved",
        "contradictions_flagged", "insights_created",
    }
