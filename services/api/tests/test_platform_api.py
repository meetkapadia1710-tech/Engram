"""API-level smoke coverage for the platform routers: marketplace, agents,
workflows, tools, events, observability, intelligence."""


def _add_memory(client, ws, content, **kw):
    body = {"content": content, "type": "note", **kw}
    r = client.post(f"/v1/workspaces/{ws}/memories", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Marketplace / plugins
# ---------------------------------------------------------------------------


def test_catalog_lists_first_party_apps(client):
    r = client.get("/v1/catalog")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    slugs = {p["slug"] for p in data["items"]}
    assert "research-assistant" in slugs


def test_catalog_detail_includes_versions(client):
    r = client.get("/v1/catalog/research-assistant")
    assert r.status_code == 200
    assert r.json()["versions"]


def test_catalog_detail_404_for_unknown_slug(client):
    assert client.get("/v1/catalog/does-not-exist").status_code == 404


def test_plugin_publish_and_install_lifecycle(client, workspace_id):
    manifest = {"slug": "api-test-app", "name": "API Test App",
                "permissions": ["memory.read"]}
    r = client.post("/v1/catalog", json={"manifest": manifest, "version": "1.0.0"})
    assert r.status_code == 201

    r = client.post(f"/v1/workspaces/{workspace_id}/plugins/api-test-app/install")
    assert r.status_code == 201
    assert r.json()["version"] == "1.0.0"

    r = client.get(f"/v1/workspaces/{workspace_id}/plugins")
    assert any(i["plugin_id"] for i in r.json()["items"])

    r = client.get(f"/v1/workspaces/{workspace_id}/plugins/api-test-app/permissions")
    assert r.json()["granted"] == ["memory.read"]

    assert client.post(f"/v1/workspaces/{workspace_id}/plugins/api-test-app/disable").json()["enabled"] is False
    assert client.post(f"/v1/workspaces/{workspace_id}/plugins/api-test-app/enable").json()["enabled"] is True
    assert client.delete(f"/v1/workspaces/{workspace_id}/plugins/api-test-app").status_code == 204


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


def test_agent_team_roster(client):
    r = client.get("/v1/agents/team")
    assert r.status_code == 200
    names = {a["name"] for a in r.json()["agents"]}
    assert "research" in names


def test_agent_run_lifecycle(client, workspace_id):
    _add_memory(client, workspace_id, "Docker layer caching speeds up CI builds.",
                type="research_paper")

    r = client.post(f"/v1/workspaces/{workspace_id}/agents/run",
                    json={"goal": "what do we know about docker?", "team": ["research"]})
    assert r.status_code == 201
    run = r.json()
    assert run["status"] == "ok"
    assert run["messages"]

    r = client.get(f"/v1/workspaces/{workspace_id}/agents/runs")
    assert any(x["id"] == run["id"] for x in r.json()["items"])

    r = client.get(f"/v1/workspaces/{workspace_id}/agents/runs/{run['id']}")
    assert r.status_code == 200

    r = client.get(f"/v1/workspaces/{workspace_id}/agents/runs/{run['id']}/messages")
    assert r.json()["messages"]


def test_agent_run_rejects_unknown_team_and_empty_goal(client, workspace_id):
    r = client.post(f"/v1/workspaces/{workspace_id}/agents/run",
                    json={"goal": "x", "team": ["bogus"]})
    assert r.status_code == 422

    r = client.post(f"/v1/workspaces/{workspace_id}/agents/run", json={"goal": "   "})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


def test_workflow_crud_and_trigger(client, workspace_id):
    body = {
        "name": "test workflow",
        "steps": [{"type": "create_memory", "content": "hello from a workflow"}],
    }
    r = client.post(f"/v1/workspaces/{workspace_id}/workflows", json=body)
    assert r.status_code == 201
    wf = r.json()
    assert wf["steps"]

    r = client.get(f"/v1/workspaces/{workspace_id}/workflows")
    assert any(w["id"] == wf["id"] for w in r.json()["items"])

    r = client.patch(f"/v1/workspaces/{workspace_id}/workflows/{wf['id']}",
                     json={"description": "updated"})
    assert r.json()["description"] == "updated"

    r = client.post(f"/v1/workspaces/{workspace_id}/workflows/{wf['id']}/trigger")
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "ok"

    r = client.get(f"/v1/workspaces/{workspace_id}/workflow-runs")
    assert any(x["id"] == run["id"] for x in r.json()["items"])

    r = client.get(f"/v1/workspaces/{workspace_id}/workflow-runs/{run['id']}")
    assert "log" in r.json()

    assert client.delete(f"/v1/workspaces/{workspace_id}/workflows/{wf['id']}").status_code == 204


def test_workflow_rejects_unknown_trigger_event(client, workspace_id):
    body = {"name": "bad trigger", "trigger_event": "NotARealEvent", "steps": []}
    r = client.post(f"/v1/workspaces/{workspace_id}/workflows", json=body)
    assert r.status_code == 422


def test_disabled_workflow_cannot_be_triggered(client, workspace_id):
    body = {"name": "disabled wf", "steps": [], "enabled": False}
    wf = client.post(f"/v1/workspaces/{workspace_id}/workflows", json=body).json()
    r = client.post(f"/v1/workspaces/{workspace_id}/workflows/{wf['id']}/trigger")
    assert r.status_code == 409


def test_workflow_event_types_listed(client):
    r = client.get("/v1/workflow-event-types")
    assert "MemoryCreated" in r.json()["event_types"]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def test_tools_listed_and_executed(client, workspace_id):
    r = client.get("/v1/tools")
    names = {t["name"] for t in r.json()["tools"]}
    assert "memory.create" in names

    r = client.post(
        f"/v1/workspaces/{workspace_id}/tools/memory.create",
        json={"args": {"content": "created via the tools API"},
              "granted_permissions": ["memory.write"]},
    )
    assert r.status_code == 200
    assert r.json()["result"]["id"]

    r = client.get(f"/v1/workspaces/{workspace_id}/tool-executions")
    assert r.json()["items"]

    exec_id = r.json()["items"][0]["id"]
    r = client.get(f"/v1/workspaces/{workspace_id}/tool-executions/{exec_id}")
    assert r.status_code == 200
    assert "args" in r.json()


def test_tool_execution_denied_without_permission(client, workspace_id):
    r = client.post(
        f"/v1/workspaces/{workspace_id}/tools/memory.create",
        json={"args": {"content": "x"}, "granted_permissions": []},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def test_events_listed_after_memory_create(client, workspace_id):
    _add_memory(client, workspace_id, "An event-generating memory.")
    r = client.get(f"/v1/workspaces/{workspace_id}/events")
    types = {e["type"] for e in r.json()["items"]}
    assert "MemoryCreated" in types

    r = client.get("/v1/events/types")
    assert "WorkflowStarted" in r.json()["event_types"]

    r = client.get("/v1/events/subscribers")
    assert any(s["name"] == "workflow-engine" for s in r.json()["subscribers"])


def test_events_dlq_and_replay_unknown_event_404(client):
    r = client.get("/v1/events/dlq")
    assert r.status_code == 200
    assert "items" in r.json()

    r = client.post("/v1/events/does-not-exist/replay")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


def test_prometheus_metrics_endpoint(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "engram_" in r.text


def test_json_metrics_and_derived_views(client, workspace_id):
    _add_memory(client, workspace_id, "Metrics probe memory.")
    assert client.get("/v1/metrics").status_code == 200
    assert client.get("/v1/metrics/agent-timelines").status_code == 200
    assert client.get("/v1/metrics/search").status_code == 200
    assert client.get("/v1/metrics/pipeline").status_code == 200
    r = client.get("/v1/metrics/workers")
    assert "workflows" in r.json() and "agents" in r.json()


# ---------------------------------------------------------------------------
# Intelligence: digital twin, evolution, evaluation
# ---------------------------------------------------------------------------


def test_digital_twin_endpoints(client, workspace_id):
    _add_memory(client, workspace_id, "Docker and Kubernetes notes for the twin.")
    r = client.get(f"/v1/workspaces/{workspace_id}/digital-twin")
    assert r.status_code == 200
    assert "skills" in r.json()

    r = client.post(f"/v1/workspaces/{workspace_id}/digital-twin/refresh")
    assert r.status_code == 200


def test_evolution_endpoints(client, workspace_id):
    _add_memory(client, workspace_id, "A memory for the evolution engine to chew on.")

    assert client.post(f"/v1/workspaces/{workspace_id}/evolution/decay").status_code == 200
    assert client.post(f"/v1/workspaces/{workspace_id}/evolution/merge-duplicates",
                       params={"dry_run": True}).status_code == 200
    assert client.post(f"/v1/workspaces/{workspace_id}/evolution/improve-summaries").status_code == 200
    assert client.post(f"/v1/workspaces/{workspace_id}/evolution/detect-contradictions").status_code == 200
    assert client.post(f"/v1/workspaces/{workspace_id}/evolution/generate-insights").status_code == 200

    r = client.post(f"/v1/workspaces/{workspace_id}/evolution/run")
    assert r.status_code == 200
    assert "insights_created" in r.json()

    r = client.get(f"/v1/workspaces/{workspace_id}/evolution/log")
    assert r.status_code == 200


def test_evaluation_endpoints(client, workspace_id):
    _add_memory(client, workspace_id, "Evaluation probe memory about Docker.")

    r = client.post(f"/v1/workspaces/{workspace_id}/evaluation/run")
    assert r.status_code == 201
    report = r.json()
    assert 0.0 <= report["retrieval_quality"] <= 1.0

    r = client.get(f"/v1/workspaces/{workspace_id}/evaluation/reports")
    assert any(x["id"] == report["id"] for x in r.json()["items"])

    r = client.get(f"/v1/workspaces/{workspace_id}/evaluation/reports/{report['id']}")
    assert r.status_code == 200
    assert "samples" in r.json()
