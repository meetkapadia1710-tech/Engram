"""Platform kernel: publish/install lifecycle, permissions, quotas, flags."""

import pytest

from app import kernel
from app.models import Workspace
from app.pipeline import ingest_memory


MANIFEST = {
    "slug": "test-app",
    "name": "Test App",
    "kind": "app",
    "permissions": ["memory.read", "search"],
}


def _ws(session, slug="k"):
    ws = Workspace(name=slug, slug=slug)
    session.add(ws)
    session.flush()
    return ws


def test_publish_rejects_missing_slug(session):
    with pytest.raises(kernel.KernelError) as exc:
        kernel.publish(session, {"name": "no slug"}, version="1.0.0")
    assert exc.value.status == 422


def test_publish_rejects_unknown_permission(session):
    with pytest.raises(kernel.KernelError) as exc:
        kernel.publish(session, {**MANIFEST, "permissions": ["not.a.real.permission"]},
                        version="1.0.0")
    assert exc.value.status == 422


def test_publish_rejects_duplicate_version(session):
    kernel.publish(session, MANIFEST, version="1.0.0")
    with pytest.raises(kernel.KernelError) as exc:
        kernel.publish(session, MANIFEST, version="1.0.0")
    assert exc.value.status == 409


def test_install_defaults_to_latest_version(session):
    ws = _ws(session, "k2")
    kernel.publish(session, MANIFEST, version="1.0.0")
    kernel.publish(session, {**MANIFEST, "permissions": ["memory.read", "memory.write"]},
                    version="2.0.0")

    inst = kernel.install(session, ws.id, "test-app")
    assert inst.version == "2.0.0"
    assert inst.granted_permissions == ["memory.read", "memory.write"]

    # duplicate install rejected
    with pytest.raises(kernel.KernelError) as exc:
        kernel.install(session, ws.id, "test-app")
    assert exc.value.status == 409

    # update pins the previous version for rollback
    kernel.publish(session, {**MANIFEST, "permissions": ["search"]}, version="3.0.0")
    kernel.update(session, ws.id, "test-app")
    assert inst.version == "3.0.0"
    assert inst.previous_version == "2.0.0"
    assert inst.granted_permissions == ["search"]

    kernel.rollback(session, ws.id, "test-app")
    assert inst.version == "2.0.0"
    assert inst.previous_version == "3.0.0"

    # rollback toggles version <-> previous_version, so rolling back again
    # swaps forward to 3.0.0 rather than erroring — it's a swap, not a stack.
    kernel.rollback(session, ws.id, "test-app")
    assert inst.version == "3.0.0"
    assert inst.previous_version == "2.0.0"


def test_rollback_without_prior_update_errors(session):
    ws = _ws(session, "k2b")
    kernel.publish(session, MANIFEST, version="1.0.0")
    kernel.install(session, ws.id, "test-app")
    with pytest.raises(kernel.KernelError) as exc:
        kernel.rollback(session, ws.id, "test-app")
    assert exc.value.status == 409


def test_enable_disable_and_permission_gate(session):
    ws = _ws(session, "k3")
    kernel.publish(session, MANIFEST, version="1.0.0")
    kernel.install(session, ws.id, "test-app")

    assert kernel.has_permission(session, ws.id, "test-app", "memory.read") is True
    assert kernel.has_permission(session, ws.id, "test-app", "memory.write") is False

    kernel.set_enabled(session, ws.id, "test-app", False)
    assert kernel.has_permission(session, ws.id, "test-app", "memory.read") is False

    kernel.set_enabled(session, ws.id, "test-app", True)
    assert kernel.has_permission(session, ws.id, "test-app", "memory.read") is True


def test_uninstall_removes_install(session):
    ws = _ws(session, "k4")
    kernel.publish(session, MANIFEST, version="1.0.0")
    kernel.install(session, ws.id, "test-app")
    kernel.uninstall(session, ws.id, "test-app")
    assert kernel.has_permission(session, ws.id, "test-app", "memory.read") is False


def test_install_unknown_plugin_404(session):
    ws = _ws(session, "k5")
    with pytest.raises(kernel.KernelError) as exc:
        kernel.install(session, ws.id, "does-not-exist")
    assert exc.value.status == 404


def test_api_call_quota_enforced(session, monkeypatch):
    ws = _ws(session, "k6")
    monkeypatch.setitem(kernel.DEFAULT_QUOTAS, "api_calls_per_day", 3)
    for _ in range(3):
        kernel.check_and_count_api_call(session, ws.id)
    with pytest.raises(kernel.KernelError) as exc:
        kernel.check_and_count_api_call(session, ws.id)
    assert exc.value.status == 429


def test_storage_usage_and_quota(session, monkeypatch):
    ws = _ws(session, "k7")
    ingest_memory(session, workspace_id=ws.id, content="x" * 500)
    usage = kernel.storage_usage(session, ws.id)
    assert usage["used_bytes"] >= 500

    monkeypatch.setitem(kernel.DEFAULT_QUOTAS, "storage_bytes", 100)
    with pytest.raises(kernel.KernelError) as exc:
        kernel.check_storage(session, ws.id, incoming_bytes=1000)
    assert exc.value.status == 429


def test_feature_flags_workspace_overrides_global(session):
    ws = _ws(session, "k8")
    assert kernel.flag_enabled(session, "beta-thing") is False

    kernel.set_flag(session, "beta-thing", True)  # global
    assert kernel.flag_enabled(session, "beta-thing", workspace_id=ws.id) is True

    kernel.set_flag(session, "beta-thing", False, workspace_id=ws.id)  # workspace override
    assert kernel.flag_enabled(session, "beta-thing", workspace_id=ws.id) is False
    assert kernel.flag_enabled(session, "beta-thing") is True  # global untouched
