"""Tool registry + sandboxed execution: permissions, fs jail, http allowlist."""

import pytest

from sqlalchemy import select

from app import tools
from app.config import DATA_DIR
from app.models import Memory, Workspace
from app.models_platform import ToolExecution


def _ws(session, slug="tool-ws"):
    ws = Workspace(name=slug, slug=slug)
    session.add(ws)
    session.flush()
    return ws


def test_list_tools_includes_builtins():
    names = {t["name"] for t in tools.list_tools()}
    assert {"memory.search", "memory.create", "context.build", "fs.read", "http.get"} <= names


def test_execute_unknown_tool_errors(session):
    with pytest.raises(tools.ToolError) as exc:
        tools.execute(session, "not.a.tool", {})
    assert exc.value.status == "error"


def test_execute_denies_without_permission(session):
    ws = _ws(session)
    with pytest.raises(tools.ToolError) as exc:
        tools.execute(session, "memory.create", {"content": "hi"},
                       workspace_id=ws.id, granted_permissions=[])
    assert exc.value.status == "denied"

    row = session.execute(
        select(ToolExecution).where(ToolExecution.tool == "memory.create")
    ).scalar_one()
    assert row.status == "denied"


def test_execute_memory_create_and_search(session):
    ws = _ws(session, "tool-ws-2")
    result = tools.execute(
        session, "memory.create",
        {"content": "Docker layers are cached by instruction order.", "memory_type": "note"},
        workspace_id=ws.id, granted_permissions=["memory.write"],
    )
    assert result["id"]
    assert session.get(Memory, result["id"]) is not None

    row = session.execute(
        select(ToolExecution).where(ToolExecution.tool == "memory.create")
    ).scalar_one()
    assert row.status == "ok"
    assert row.duration_ms >= 0

    found = tools.execute(
        session, "memory.search", {"query": "docker"},
        workspace_id=ws.id, granted_permissions=["search"],
    )
    assert any(r["id"] == result["id"] for r in found["results"])


def test_fs_read_sandboxed_to_data_dir(session):
    probe = DATA_DIR / "engram_test_probe.txt"
    probe.write_text("hello from the sandbox", encoding="utf-8")
    try:
        result = tools.execute(
            session, "fs.read", {"path": "engram_test_probe.txt"},
            granted_permissions=["tools.fs"],
        )
        assert result["content"] == "hello from the sandbox"
    finally:
        probe.unlink(missing_ok=True)


def test_fs_read_denies_path_traversal(session):
    with pytest.raises(tools.ToolError) as exc:
        tools.execute(
            session, "fs.read", {"path": "../outside_the_sandbox.txt"},
            granted_permissions=["tools.fs"],
        )
    assert exc.value.status == "denied"


def test_http_get_denies_non_allowlisted_host(session):
    with pytest.raises(tools.ToolError) as exc:
        tools.execute(
            session, "http.get", {"url": "http://evil.example.com/steal"},
            granted_permissions=["tools.http"],
        )
    assert exc.value.status == "denied"
