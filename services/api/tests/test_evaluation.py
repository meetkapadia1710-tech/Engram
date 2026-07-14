"""AI evaluation framework: retrieval quality, grounding, hallucination,
citation, agent success rate."""

from app import evaluation
from app.models import Workspace
from app.models_platform import AgentRun
from app.pipeline import ingest_memory


def _ws(session, slug="eval-ws"):
    ws = Workspace(name=slug, slug=slug)
    session.add(ws)
    session.flush()
    return ws


def test_run_evaluation_on_empty_workspace_is_trivially_optimistic(session):
    ws = _ws(session)
    report = evaluation.run_evaluation(session, ws.id)
    assert report.retrieval_quality == 1.0
    assert report.citation_accuracy == 1.0
    assert report.agent_success_rate == 1.0
    assert report.summary


def test_run_evaluation_with_content_produces_bounded_scores(session):
    ws = _ws(session, "eval-ws-2")
    for i in range(6):
        ingest_memory(session, workspace_id=ws.id,
                      content=f"Docker layer caching note number {i} about builds.")
    session.flush()

    report = evaluation.run_evaluation(session, ws.id)
    for score in (report.retrieval_quality, report.grounding_accuracy,
                  report.hallucination_rate, report.citation_accuracy,
                  report.agent_success_rate, report.ranking_ndcg):
        assert 0.0 <= score <= 1.0
    assert report.samples


def test_agent_success_rate_reflects_agent_runs(session):
    ws = _ws(session, "eval-ws-3")
    session.add(AgentRun(workspace_id=ws.id, goal="g1", status="ok"))
    session.add(AgentRun(workspace_id=ws.id, goal="g2", status="failed"))
    session.flush()

    rate = evaluation._agent_success_rate(session, ws.id)
    assert rate == 0.5


def test_list_reports_orders_newest_first(session):
    ws = _ws(session, "eval-ws-4")
    r1 = evaluation.run_evaluation(session, ws.id)
    r2 = evaluation.run_evaluation(session, ws.id)

    reports = evaluation.list_reports(session, ws.id)
    assert len(reports) == 2
    assert reports[0].id == r2.id
    assert reports[1].id == r1.id


def test_grounding_accuracy_high_for_self_similar_content(session):
    ws = _ws(session, "eval-ws-5")
    for i in range(5):
        ingest_memory(session, workspace_id=ws.id,
                      content=f"Kubernetes scheduling and pod placement notes {i}.")
    session.flush()

    score = evaluation._grounding_accuracy(session, ws.id)
    assert score > 0.0
