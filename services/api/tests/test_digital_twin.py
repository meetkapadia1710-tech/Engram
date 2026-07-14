"""Digital Twin: skill graph, style metrics, gaps, predictions."""

from app import digital_twin
from app.models import Workspace
from app.pipeline import ingest_memory


def _ws(session, slug="twin-ws"):
    ws = Workspace(name=slug, slug=slug)
    session.add(ws)
    session.flush()
    return ws


def test_refresh_builds_skill_graph_from_tech_entities(session):
    ws = _ws(session)
    for _ in range(4):
        ingest_memory(session, workspace_id=ws.id,
                      content="Docker layer caching and Kubernetes scheduling notes.",
                      type_="code")
    session.flush()

    twin = digital_twin.refresh(session, ws.id)
    assert "docker" in twin.skills
    assert twin.skills["docker"] > 0
    assert twin.memory_count_at_last_update == 4


def test_refresh_computes_style_ratios(session):
    ws = _ws(session, "twin-ws-2")
    ingest_memory(session, workspace_id=ws.id, content="def foo(): pass", type_="code")
    ingest_memory(session, workspace_id=ws.id, content="A plain note.", type_="note")
    session.flush()

    twin = digital_twin.refresh(session, ws.id)
    assert twin.style["code_ratio"] == 0.5
    assert twin.style["note_ratio"] == 0.5
    assert twin.style["dominant_type"] in ("code", "note")


def test_refresh_flags_low_mention_entities_as_gaps(session):
    ws = _ws(session, "twin-ws-3")
    ingest_memory(session, workspace_id=ws.id, content="A single mention of Redis here.")
    session.flush()

    twin = digital_twin.refresh(session, ws.id)
    assert "redis" in twin.gaps


def test_get_or_create_creates_on_first_call_and_reuses_after(session):
    ws = _ws(session, "twin-ws-4")
    ingest_memory(session, workspace_id=ws.id, content="Some content to seed the twin.")
    session.flush()

    twin1 = digital_twin.get_or_create(session, ws.id)
    twin2 = digital_twin.get_or_create(session, ws.id)
    assert twin1.id == twin2.id


def test_refresh_on_empty_workspace_does_not_error(session):
    ws = _ws(session, "twin-ws-5")
    twin = digital_twin.refresh(session, ws.id)
    assert twin.skills == {}
    assert twin.memory_count_at_last_update == 0
