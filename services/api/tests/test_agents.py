"""Multi-agent orchestrator: plan/research/debate/vote/merge lifecycle."""

import pytest
from sqlalchemy import select

from app import agents
from app.models import Memory, Workspace
from app.models_platform import AgentMessage
from app.pipeline import ingest_memory


def _ws(session, slug="agent-ws"):
    ws = Workspace(name=slug, slug=slug)
    session.add(ws)
    session.flush()
    return ws


def test_contradicts_detects_opposing_polarity_over_shared_topic():
    a = "Docker layers are cached and builds are fast"
    b = "Docker layers are not cached and builds are fast"
    assert agents._contradicts(a, b) is True


def test_contradicts_ignores_unrelated_text():
    a = "Docker layers are cached and builds are fast"
    b = "The pasta recipe needs basil and garlic"
    assert agents._contradicts(a, b) is False


def test_run_agents_end_to_end(session):
    ws = _ws(session)
    ingest_memory(session, workspace_id=ws.id,
                  content="Docker layer caching makes CI builds dramatically faster.",
                  type_="research_paper")
    session.flush()

    run = agents.run_agents(session, ws.id, "what do we know about docker caching?",
                            team=["research", "memory"])

    assert run.status == "ok"
    assert run.conclusion
    assert run.conclusion_memory_id
    assert session.get(Memory, run.conclusion_memory_id) is not None

    messages = session.execute(
        select(AgentMessage).where(AgentMessage.run_id == run.id).order_by(AgentMessage.seq)
    ).scalars().all()
    kinds = [m.kind for m in messages]
    assert "plan" in kinds
    assert "finding" in kinds
    assert kinds[-1] == "merge"
    # seq is strictly increasing
    assert [m.seq for m in messages] == sorted(m.seq for m in messages)


def test_run_agents_raises_on_all_unknown_team_names(session):
    ws = _ws(session, "agent-ws-2")
    with pytest.raises(ValueError):
        agents.run_agents(session, ws.id, "goal", team=["not-a-real-agent"])


def test_run_agents_filters_unknown_names_but_keeps_valid_ones(session):
    ws = _ws(session, "agent-ws-3")
    run = agents.run_agents(session, ws.id, "goal",
                            team=["research", "not-a-real-agent"])
    assert run.status == "ok"
    import json

    assert json.loads(run.agents_json) == ["research"]


def test_run_agents_handles_no_relevant_memories(session):
    ws = _ws(session, "agent-ws-4")
    run = agents.run_agents(session, ws.id, "an obscure topic nobody wrote about",
                            team=["research"])
    assert run.status == "ok"
    assert run.conclusion
