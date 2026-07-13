"""Search engine tests: BM25, hybrid ranking, filters, recency."""

from app.models import Workspace
from app.pipeline import ingest_memory
from app.search import bm25_scores, frequency_score, hybrid_search, recency_score


def _seed(session):
    ws = Workspace(name="s", slug="s")
    session.add(ws)
    session.flush()
    docs = [
        ("Docker layer caching speeds up image builds dramatically.", "note", ["devops"]),
        ("Kubernetes schedules pods across nodes using the kube-scheduler.", "note", ["devops"]),
        ("The pasta recipe needs basil, garlic, and fresh tomatoes.", "note", ["cooking"]),
        ("Docker Compose orchestrates multi-container development environments.", "document", ["devops"]),
        ("PostgreSQL vacuuming reclaims space from dead tuples.", "note", ["database"]),
    ]
    mems = [
        ingest_memory(session, workspace_id=ws.id, content=c, type_=t, tags=tags)
        for c, t, tags in docs
    ]
    session.commit()
    return ws, mems


def test_bm25_prefers_matching_docs(session):
    ws, mems = _seed(session)
    scores = bm25_scores("docker image caching", mems)
    assert scores, "bm25 returned nothing"
    best = max(scores, key=scores.get)
    assert best == mems[0].id


def test_hybrid_search_top_hit_is_relevant(session):
    ws, mems = _seed(session)
    hits = hybrid_search(session, ws.id, "docker caching layers")
    assert hits
    assert "Docker" in hits[0].memory.content
    assert hits[0].final >= hits[-1].final


def test_hybrid_search_modes(session):
    ws, _ = _seed(session)
    for mode in ("hybrid", "vector", "keyword"):
        hits = hybrid_search(session, ws.id, "docker", mode=mode)
        assert hits, f"no hits in mode {mode}"


def test_search_filters_by_type_and_tags(session):
    ws, _ = _seed(session)
    hits = hybrid_search(session, ws.id, "docker", types=["document"])
    assert all(h.memory.type == "document" for h in hits)
    hits = hybrid_search(session, ws.id, "recipe basil", tags=["cooking"])
    assert hits and all("cooking" in h.memory.tags for h in hits)


def test_search_updates_access_count(session):
    ws, mems = _seed(session)
    before = {m.id: m.access_count for m in mems}
    hits = hybrid_search(session, ws.id, "docker")
    assert hits[0].memory.access_count == before[hits[0].memory.id] + 1


def test_recency_decay_monotonic():
    newer = recency_score("2026-07-12T00:00:00+00:00")
    older = recency_score("2026-01-01T00:00:00+00:00")
    assert 0 <= older < newer <= 1


def test_frequency_score_bounds():
    assert frequency_score(0) == 0
    assert frequency_score(10_000) == 1.0
    assert frequency_score(5) < frequency_score(25)
