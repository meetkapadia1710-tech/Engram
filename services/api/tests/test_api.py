"""API contract tests: happy paths, validation, 404s, graph, context, analytics."""


def _add(client, ws, content, **kw):
    body = {"content": content, "type": "note", **kw}
    r = client.post(f"/v1/workspaces/{ws}/memories", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_openapi_served(client):
    assert client.get("/openapi.json").status_code == 200


def test_workspace_crud(client):
    r = client.post("/v1/workspaces", json={"name": "Alpha"})
    assert r.status_code == 201
    ws = r.json()
    assert ws["slug"] == "alpha"
    # duplicate slug rejected
    assert client.post("/v1/workspaces", json={"name": "Alpha"}).status_code == 409
    listed = client.get("/v1/workspaces").json()["items"]
    assert any(w["id"] == ws["id"] for w in listed)
    assert client.delete(f"/v1/workspaces/{ws['id']}").status_code == 204


def test_memory_lifecycle(client, workspace_id):
    mem = _add(client, workspace_id, "Docker layers are cached by instruction order.",
               tags=["devops"], title="Docker caching")
    assert mem["keywords"]
    assert any(e["name"] == "docker" for e in mem["entities"])

    got = client.get(f"/v1/memories/{mem['id']}").json()
    assert got["title"] == "Docker caching"

    upd = client.patch(f"/v1/memories/{mem['id']}", json={"importance": 0.9}).json()
    assert upd["importance"] == 0.9

    assert client.delete(f"/v1/memories/{mem['id']}").status_code == 204
    assert client.get(f"/v1/memories/{mem['id']}").status_code == 404


def test_create_validations(client, workspace_id):
    r = client.post(f"/v1/workspaces/{workspace_id}/memories",
                    json={"content": "x", "type": "not_a_type"})
    assert r.status_code == 422
    r = client.post(f"/v1/workspaces/{workspace_id}/memories", json={"content": "   "})
    assert r.status_code == 422
    r = client.post("/v1/workspaces/nope/memories", json={"content": "hi"})
    assert r.status_code == 404


def test_search_endpoint(client, workspace_id):
    _add(client, workspace_id, "Kubernetes pods are scheduled onto nodes.")
    _add(client, workspace_id, "Docker Compose runs multi-container apps locally.")
    r = client.post(f"/v1/workspaces/{workspace_id}/search",
                    json={"query": "docker compose containers"})
    assert r.status_code == 200
    results = r.json()["results"]
    assert results
    assert "Docker" in results[0]["memory"]["content"]
    assert "components" in results[0]


def test_search_validation(client, workspace_id):
    r = client.post(f"/v1/workspaces/{workspace_id}/search", json={"query": ""})
    assert r.status_code == 422
    r = client.post(f"/v1/workspaces/{workspace_id}/search",
                    json={"query": "x", "mode": "quantum"})
    assert r.status_code == 422


def test_context_builder(client, workspace_id):
    _add(client, workspace_id, "Docker uses layered images. " * 30)
    r = client.post(f"/v1/workspaces/{workspace_id}/context",
                    json={"query": "docker images", "max_tokens": 500})
    assert r.status_code == 200
    data = r.json()
    assert data["sources"]
    assert "[1]" in data["context"]
    assert data["approx_tokens"] <= 600


def test_graph_and_related(client, workspace_id):
    a = _add(client, workspace_id, "Docker image caching relies on layer order.")
    _add(client, workspace_id, "Docker layer caching makes builds fast.")
    g = client.get(f"/v1/workspaces/{workspace_id}/graph").json()
    assert g["nodes"] and g["edges"]
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"memory", "entity"} <= kinds

    rel = client.get(f"/v1/memories/{a['id']}/related").json()["items"]
    assert rel, "expected at least one related memory"


def test_analytics(client, workspace_id):
    _add(client, workspace_id, "Postgres vacuum reclaims dead tuples.")
    r = client.get(f"/v1/workspaces/{workspace_id}/analytics")
    assert r.status_code == 200
    data = r.json()
    assert data["memories"] >= 1
    assert len(data["activity"]) == 14
    assert data["top_entities"]


def test_audit_log_records_actions(client, workspace_id):
    _add(client, workspace_id, "Auditable event content here.")
    items = client.get(f"/v1/workspaces/{workspace_id}/audit").json()["items"]
    assert any(i["action"] == "memory.create" for i in items)


def test_types_listed(client):
    types = client.get("/v1/types").json()
    assert "conversation" in types and "code" in types
