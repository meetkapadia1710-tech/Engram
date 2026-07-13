"""Unit tests: chunking, cleaning, embedding, extraction, relationships."""

from app.ai import LocalEmbedder, cosine
from app.pipeline import (
    chunk_text,
    clean_text,
    extract_entities,
    extract_keywords,
    ingest_memory,
    score_importance,
)
from app.models import Workspace


def test_clean_text_normalizes_whitespace():
    assert clean_text("a\r\n\r\n\r\n\r\nb\t\tc  ") == "a\n\nb c"


def test_chunk_short_text_is_single_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_chunk_long_text_respects_max_and_covers_content():
    text = "\n\n".join(f"Paragraph {i} " + "x" * 300 for i in range(10))
    chunks = chunk_text(text, max_chars=900)
    assert len(chunks) > 1
    assert all(len(c) <= 900 for c in chunks)
    assert "Paragraph 0" in chunks[0]
    assert "Paragraph 9" in chunks[-1]


def test_local_embedder_deterministic_and_normalized():
    e = LocalEmbedder(dim=128)
    v1, v2 = e.embed(["docker containers", "docker containers"])
    assert v1 == v2
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-9


def test_local_embedder_similarity_ordering():
    e = LocalEmbedder(dim=256)
    a, b, c = e.embed([
        "docker container images and layers",
        "docker images are built from layers",
        "the recipe needs two cups of flour",
    ])
    assert cosine(a, b) > cosine(a, c)


def test_extract_keywords_ranks_frequency():
    kws = extract_keywords("docker docker docker kubernetes redis")
    assert kws[0] == "docker"


def test_extract_entities_finds_tech_and_people():
    ents = dict(extract_entities("Ada Lovelace deployed Postgres and Docker at Analytical Labs"))
    assert ents.get("docker") == "technology"
    assert ents.get("postgres") == "technology"
    assert "Ada Lovelace" in ents


def test_entity_aliases_canonicalize():
    a = dict(extract_entities("We chose PostgreSQL for storage"))
    b = dict(extract_entities("Postgres vacuum settings matter"))
    assert "postgres" in a and "postgres" in b
    dotted = dict(extract_entities("The app uses Next.js routing"))
    assert dotted.get("nextjs") == "technology"


def test_importance_bounds():
    assert 0.2 <= score_importance("x", "note") <= 0.95
    long_important = "This is an important decision. " * 200
    assert score_importance(long_important, "document") > score_importance("hi", "note")


def test_ingest_creates_chunks_entities_relationships(session):
    ws = Workspace(name="w", slug="w")
    session.add(ws)
    session.flush()

    m1 = ingest_memory(
        session, workspace_id=ws.id,
        content="Learned that Docker images are built from cached layers.",
        type_="note",
    )
    m2 = ingest_memory(
        session, workspace_id=ws.id,
        content="Docker layer caching makes image builds much faster.",
        type_="note",
    )
    session.commit()

    assert m1.embedding and m1.keywords
    assert any(l.entity.name == "docker" for l in m1.entity_links)

    from sqlalchemy import select
    from app.models import Relationship

    rels = session.execute(select(Relationship)).scalars().all()
    assert any({r.source_id, r.target_id} == {m1.id, m2.id} for r in rels)


def test_ingest_rejects_empty_content(session):
    ws = Workspace(name="w2", slug="w2")
    session.add(ws)
    session.flush()
    import pytest

    with pytest.raises(ValueError):
        ingest_memory(session, workspace_id=ws.id, content="   \n\n  ")
