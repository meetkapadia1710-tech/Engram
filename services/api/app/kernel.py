"""Platform kernel: plugin lifecycle, permissions, quotas, feature flags.

The kernel is deliberately thin — it manages *metadata and gates*; actual
capabilities (memory, search, tools, workflows, agents) live in their own
modules and consult the kernel before acting.

Plugin manifest shape (stored per version, sha256-signed):

    {
      "slug": "research-assistant",
      "name": "Research Assistant",
      "kind": "app",
      "permissions": ["memory.read", "memory.write", "search", "tools.http"],
      "prompts": {...},          # business logic only —
      "workflows": [...],        # everything else uses platform APIs
      "ui": {"icon": "🔬", "accent": "#7c8cff"}
    }
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .events import emit
from .models import Memory, _now_iso
from .models_platform import FeatureFlag, Plugin, PluginInstall, PluginVersion, QuotaUsage

PERMISSIONS = [
    "memory.read", "memory.write", "memory.delete", "search", "context",
    "graph.read", "workflows.run", "agents.run", "tools.http", "tools.fs",
    "events.subscribe",
]

# per-workspace defaults; enterprise tiers override via feature flags
DEFAULT_QUOTAS = {
    "api_calls_per_day": 50_000,
    "storage_bytes": 512 * 1024 * 1024,
}


class KernelError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _sign(manifest: dict) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Publishing (catalog side)
# ---------------------------------------------------------------------------


def publish(
    db: Session,
    manifest: dict,
    *,
    version: str,
    author: str = "",
    first_party: bool = False,
) -> PluginVersion:
    slug = manifest.get("slug", "").strip()
    if not slug:
        raise KernelError(422, "manifest.slug is required")
    unknown = set(manifest.get("permissions", [])) - set(PERMISSIONS)
    if unknown:
        raise KernelError(422, f"unknown permissions: {sorted(unknown)}")

    plugin = db.execute(select(Plugin).where(Plugin.slug == slug)).scalar_one_or_none()
    if plugin is None:
        plugin = Plugin(
            slug=slug,
            name=manifest.get("name", slug),
            kind=manifest.get("kind", "app"),
            description=manifest.get("description", ""),
            author=author,
            first_party=1 if first_party else 0,
        )
        db.add(plugin)
        db.flush()

    exists = db.execute(
        select(PluginVersion).where(
            PluginVersion.plugin_id == plugin.id, PluginVersion.version == version
        )
    ).scalar_one_or_none()
    if exists:
        raise KernelError(409, f"{slug}@{version} already published")

    pv = PluginVersion(
        plugin_id=plugin.id,
        version=version,
        manifest_json=json.dumps(manifest),
        signature=_sign(manifest),
    )
    plugin.latest_version = version
    plugin.name = manifest.get("name", plugin.name)
    plugin.description = manifest.get("description", plugin.description)
    db.add(pv)
    db.flush()
    return pv


# ---------------------------------------------------------------------------
# Install lifecycle (workspace side)
# ---------------------------------------------------------------------------


def _get_version(db: Session, plugin: Plugin, version: str) -> PluginVersion:
    pv = db.execute(
        select(PluginVersion).where(
            PluginVersion.plugin_id == plugin.id, PluginVersion.version == version
        )
    ).scalar_one_or_none()
    if pv is None:
        raise KernelError(404, f"{plugin.slug}@{version} not found")
    if pv.signature != _sign(pv.manifest):
        raise KernelError(409, f"{plugin.slug}@{version} failed signature verification")
    return pv


def install(
    db: Session, workspace_id: str, slug: str, *, version: str = ""
) -> PluginInstall:
    plugin = db.execute(select(Plugin).where(Plugin.slug == slug)).scalar_one_or_none()
    if plugin is None:
        raise KernelError(404, f"plugin {slug!r} not found")
    version = version or plugin.latest_version
    pv = _get_version(db, plugin, version)

    existing = db.execute(
        select(PluginInstall).where(
            PluginInstall.workspace_id == workspace_id,
            PluginInstall.plugin_id == plugin.id,
        )
    ).scalar_one_or_none()
    if existing:
        raise KernelError(409, f"{slug} already installed (use update)")

    inst = PluginInstall(workspace_id=workspace_id, plugin_id=plugin.id, version=version)
    inst.granted_permissions = pv.manifest.get("permissions", [])
    db.add(inst)
    db.flush()
    emit(db, "PluginInstalled", {"slug": slug, "version": version}, workspace_id=workspace_id)
    return inst


def _get_install(db: Session, workspace_id: str, slug: str) -> tuple[Plugin, PluginInstall]:
    plugin = db.execute(select(Plugin).where(Plugin.slug == slug)).scalar_one_or_none()
    if plugin is None:
        raise KernelError(404, f"plugin {slug!r} not found")
    inst = db.execute(
        select(PluginInstall).where(
            PluginInstall.workspace_id == workspace_id,
            PluginInstall.plugin_id == plugin.id,
        )
    ).scalar_one_or_none()
    if inst is None:
        raise KernelError(404, f"{slug} is not installed in this workspace")
    return plugin, inst


def update(db: Session, workspace_id: str, slug: str, *, version: str = "") -> PluginInstall:
    plugin, inst = _get_install(db, workspace_id, slug)
    version = version or plugin.latest_version
    pv = _get_version(db, plugin, version)
    if version == inst.version:
        return inst
    inst.previous_version = inst.version
    inst.version = version
    inst.granted_permissions = pv.manifest.get("permissions", [])
    inst.updated_at = _now_iso()
    return inst


def rollback(db: Session, workspace_id: str, slug: str) -> PluginInstall:
    plugin, inst = _get_install(db, workspace_id, slug)
    if not inst.previous_version:
        raise KernelError(409, f"{slug} has no previous version to roll back to")
    _get_version(db, plugin, inst.previous_version)
    inst.version, inst.previous_version = inst.previous_version, inst.version
    inst.updated_at = _now_iso()
    return inst


def set_enabled(db: Session, workspace_id: str, slug: str, enabled: bool) -> PluginInstall:
    _, inst = _get_install(db, workspace_id, slug)
    inst.enabled = 1 if enabled else 0
    inst.updated_at = _now_iso()
    return inst


def uninstall(db: Session, workspace_id: str, slug: str) -> None:
    _, inst = _get_install(db, workspace_id, slug)
    db.delete(inst)
    emit(db, "PluginUninstalled", {"slug": slug}, workspace_id=workspace_id)


def has_permission(db: Session, workspace_id: str, slug: str, permission: str) -> bool:
    try:
        _, inst = _get_install(db, workspace_id, slug)
    except KernelError:
        return False
    return bool(inst.enabled) and permission in inst.granted_permissions


# ---------------------------------------------------------------------------
# Quotas
# ---------------------------------------------------------------------------


def check_and_count_api_call(db: Session, workspace_id: str) -> None:
    day = datetime.now(timezone.utc).date().isoformat()
    row = db.execute(
        select(QuotaUsage).where(
            QuotaUsage.workspace_id == workspace_id, QuotaUsage.day == day
        )
    ).scalar_one_or_none()
    if row is None:
        row = QuotaUsage(workspace_id=workspace_id, day=day, api_calls=0)
        db.add(row)
    if row.api_calls >= DEFAULT_QUOTAS["api_calls_per_day"]:
        raise KernelError(429, "daily API quota exceeded")
    row.api_calls += 1


def storage_usage(db: Session, workspace_id: str) -> dict:
    used = db.execute(
        select(func.coalesce(func.sum(func.length(Memory.content)), 0)).where(
            Memory.workspace_id == workspace_id
        )
    ).scalar_one()
    return {
        "used_bytes": int(used),
        "quota_bytes": DEFAULT_QUOTAS["storage_bytes"],
        "pct": round(100 * used / DEFAULT_QUOTAS["storage_bytes"], 2),
    }


def check_storage(db: Session, workspace_id: str, incoming_bytes: int) -> None:
    usage = storage_usage(db, workspace_id)
    if usage["used_bytes"] + incoming_bytes > usage["quota_bytes"]:
        raise KernelError(429, "storage quota exceeded")


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------


def flag_enabled(db: Session, key: str, workspace_id: str = "") -> bool:
    for ws in (workspace_id, ""):  # workspace override, then global
        row = db.execute(
            select(FeatureFlag).where(
                FeatureFlag.workspace_id == ws, FeatureFlag.key == key
            )
        ).scalar_one_or_none()
        if row is not None:
            return bool(row.enabled)
    return False


def set_flag(db: Session, key: str, enabled: bool, workspace_id: str = "") -> FeatureFlag:
    row = db.execute(
        select(FeatureFlag).where(
            FeatureFlag.workspace_id == workspace_id, FeatureFlag.key == key
        )
    ).scalar_one_or_none()
    if row is None:
        row = FeatureFlag(workspace_id=workspace_id, key=key)
        db.add(row)
    row.enabled = 1 if enabled else 0
    row.updated_at = _now_iso()
    db.flush()
    return row
