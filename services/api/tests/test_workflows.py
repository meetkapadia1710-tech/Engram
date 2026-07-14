"""Workflow engine: interpolation, step types, conditions, loops, retries,
event triggers."""

import json

from sqlalchemy import select

from app import events, tools, workflows
from app.models import Memory, Workspace
from app.models_platform import Workflow, WorkflowRun
from app.pipeline import ingest_memory


def _ws(session, slug="wf-ws"):
    ws = Workspace(name=slug, slug=slug)
    session.add(ws)
    session.flush()
    return ws


def _wf(session, ws, steps, **kw) -> Workflow:
    wf = Workflow(workspace_id=ws.id, name=kw.pop("name", "wf"), **kw)
    wf.steps_json = json.dumps(steps)
    session.add(wf)
    session.flush()
    return wf


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------


def test_interpolate_whole_string_placeholder_keeps_native_type():
    result = workflows.interpolate("{items}", {"items": [1, 2, 3]})
    assert result == [1, 2, 3]


def test_interpolate_embedded_placeholder_stringifies():
    result = workflows.interpolate("hello {name}!", {"name": "world"})
    assert result == "hello world!"


def test_interpolate_missing_var_becomes_empty_string():
    result = workflows.interpolate("value: {missing}", {})
    assert result == "value: "


def test_interpolate_dotted_lookup():
    result = workflows.interpolate("{event.type}", {"event": {"type": "MemoryCreated"}})
    assert result == "MemoryCreated"


def test_interpolate_recurses_through_dict_and_list():
    result = workflows.interpolate(
        {"a": "{x}", "b": ["{y}", "plain"]}, {"x": "1", "y": "2"}
    )
    assert result == {"a": "1", "b": ["2", "plain"]}


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------


def test_search_then_create_memory_chain(session):
    ws = _ws(session)
    ingest_memory(session, workspace_id=ws.id,
                  content="Docker layers are cached by instruction order.")
    session.flush()

    wf = _wf(session, ws, [
        {"type": "search", "query": "docker", "limit": 3, "out": "hits"},
        {"type": "create_memory", "content": "found {hits}", "memory_type": "note",
         "out": "created"},
    ])

    run = workflows.run_workflow(session, wf)
    assert run.status == "ok"
    assert len(run.log) == 2
    assert all(entry["status"] == "ok" for entry in run.log)


def test_condition_false_stops_run_without_failing(session):
    ws = _ws(session, "wf-ws-2")
    wf = _wf(session, ws, [
        {"type": "condition", "left": "{flag}", "op": "==", "right": "go"},
        {"type": "create_memory", "content": "should never run"},
    ])

    run = workflows.run_workflow(session, wf, variables={"flag": "stop"})
    assert run.status == "ok"
    assert len(run.log) == 1  # second step never executed
    assert run.log[0]["status"] == "stopped"


def test_condition_true_continues(session):
    ws = _ws(session, "wf-ws-3")
    wf = _wf(session, ws, [
        {"type": "condition", "left": "{flag}", "op": "==", "right": "go"},
        {"type": "create_memory", "content": "Ada Lovelace enjoys gardening."},
    ])

    run = workflows.run_workflow(session, wf, variables={"flag": "go"})
    assert run.status == "ok"
    assert len(run.log) == 2


def test_unknown_step_type_fails_run(session):
    ws = _ws(session, "wf-ws-4")
    wf = _wf(session, ws, [{"type": "not_a_real_step"}])

    run = workflows.run_workflow(session, wf)
    assert run.status == "failed"
    assert run.log[0]["status"] == "failed"
    assert "not_a_real_step" in run.log[0]["error"]


def test_for_each_runs_substeps_per_item(session):
    ws = _ws(session, "wf-ws-5")
    wf = _wf(session, ws, [
        {"type": "for_each", "items": ["a", "b", "c"],
         "steps": [{"type": "create_memory", "content": "item {item}"}]},
    ])

    run = workflows.run_workflow(session, wf)
    assert run.status == "ok"
    # sub-step entries (one per item) are appended before the for_each's own
    # summary entry, so the iteration count lands on the last log entry.
    assert run.log[-1]["iterations"] == 3

    created = session.execute(
        select(Memory).where(Memory.workspace_id == ws.id)
    ).scalars().all()
    contents = {m.content for m in created}
    assert {"item a", "item b", "item c"} <= contents


def test_step_retries_before_succeeding(session):
    ws = _ws(session, "wf-ws-6")
    calls = {"n": 0}

    @tools.tool("test.flaky", description="fails twice then succeeds",
                permission="search", schema={})
    def _flaky(*, db, workspace_id):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("not yet")
        return {"ok": True}

    try:
        wf = _wf(session, ws, [
            {"type": "tool", "tool": "test.flaky", "args": {}, "retry": 3},
        ])
        run = workflows.run_workflow(session, wf)
        assert run.status == "ok"
        assert calls["n"] == 3
    finally:
        del tools.REGISTRY["test.flaky"]


# ---------------------------------------------------------------------------
# Event-triggered workflows
# ---------------------------------------------------------------------------


def test_event_trigger_runs_matching_workflow(session):
    ws = _ws(session, "wf-ws-7")
    wf = _wf(session, ws, [
        {"type": "create_memory", "content": "triggered by {event.reason}"},
    ], name="on-trigger", trigger_event="TestWorkflowTrigger")

    events.emit(session, "TestWorkflowTrigger", {"reason": "unit-test"}, workspace_id=ws.id)

    runs = session.execute(
        select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == "ok"
    assert runs[0].trigger == "TestWorkflowTrigger"


def test_disabled_workflow_does_not_trigger(session):
    ws = _ws(session, "wf-ws-8")
    wf = _wf(session, ws, [], name="disabled",
             trigger_event="TestWorkflowTrigger2", enabled=0)

    events.emit(session, "TestWorkflowTrigger2", {}, workspace_id=ws.id)

    runs = session.execute(
        select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
    ).scalars().all()
    assert runs == []
