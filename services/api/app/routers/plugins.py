"""Marketplace / Plugin management router.

Endpoints
---------
GET  /v1/catalog                        — Browse all published plugins
GET  /v1/catalog/{slug}                 — Plugin detail + version history
POST /v1/catalog                        — Publish a new plugin manifest
POST /v1/workspaces/{ws}/plugins/{slug}/install
POST /v1/workspaces/{ws}/plugins/{slug}/update
POST /v1/workspaces/{ws}/plugins/{slug}/rollback
POST /v1/workspaces/{ws}/plugins/{slug}/enable
POST /v1/workspaces/{ws}/plugins/{slug}/disable
DELETE /v1/workspaces/{ws}/plugins/{slug}
GET  /v1/workspaces/{ws}/plugins        — Installed plugins for workspace
GET  /v1/workspaces/{ws}/plugins/{slug}/permissions
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from .. import kernel
from ..models_platform import Plugin, PluginInstall, PluginVersion
from ..security import Guard, audit, guard

router = APIRouter(prefix="/v1", tags=["marketplace"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PublishBody(BaseModel):
    manifest: dict
    version: str
    author: str = ""
    first_party: bool = False


class InstallBody(BaseModel):
    version: str = ""


# ---------------------------------------------------------------------------
# Catalog (read-only, no auth required for browsing)
# ---------------------------------------------------------------------------


@router.get("/catalog")
def list_catalog(
    g: Guard = Depends(guard),
    kind: str | None = Query(default=None),
    q: str | None = Query(default=None),
    first_party: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Browse all published plugins with optional filters."""
    stmt = select(Plugin)
    if kind:
        stmt = stmt.where(Plugin.kind == kind)
    if first_party is not None:
        stmt = stmt.where(Plugin.first_party == (1 if first_party else 0))
    plugins = list(g.db.execute(stmt).scalars().all())
    if q:
        ql = q.lower()
        plugins = [
            p for p in plugins
            if ql in p.name.lower() or ql in p.description.lower()
        ]
    total = len(plugins)
    plugins = plugins[offset: offset + limit]
    return {
        "total": total,
        "items": [_plugin_out(p) for p in plugins],
        "limit": limit,
        "offset": offset,
    }


@router.get("/catalog/{slug}")
def get_catalog_entry(slug: str, g: Guard = Depends(guard)):
    """Plugin details including all published versions."""
    plugin = g.db.execute(
        select(Plugin).where(Plugin.slug == slug)
    ).scalar_one_or_none()
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"plugin {slug!r} not found")
    versions = g.db.execute(
        select(PluginVersion)
        .where(PluginVersion.plugin_id == plugin.id)
        .order_by(PluginVersion.created_at.desc())
    ).scalars().all()
    return {
        **_plugin_out(plugin),
        "versions": [
            {
                "version": v.version,
                "signature": v.signature,
                "min_platform": v.min_platform,
                "created_at": v.created_at,
                "manifest": v.manifest,
            }
            for v in versions
        ],
    }


@router.post("/catalog", status_code=201)
def publish_plugin(body: PublishBody, g: Guard = Depends(guard)):
    """Publish a new plugin or a new version of an existing plugin."""
    try:
        pv = kernel.publish(
            g.db,
            body.manifest,
            version=body.version,
            author=body.author,
            first_party=body.first_party,
        )
    except kernel.KernelError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    audit(
        g.db,
        actor=g.actor,
        action="plugin.publish",
        detail=f"{body.manifest.get('slug')}@{body.version}",
    )
    g.db.commit()
    return {"plugin_id": pv.plugin_id, "version": pv.version, "signature": pv.signature}


# ---------------------------------------------------------------------------
# Install lifecycle (workspace-scoped)
# ---------------------------------------------------------------------------


@router.post("/workspaces/{workspace_id}/plugins/{slug}/install", status_code=201)
def install_plugin(
    workspace_id: str,
    slug: str,
    body: InstallBody | None = None,
    g: Guard = Depends(guard),
):
    try:
        inst = kernel.install(
            g.db, workspace_id, slug, version=(body.version if body else "")
        )
    except kernel.KernelError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    audit(g.db, actor=g.actor, action="plugin.install",
          workspace_id=workspace_id, detail=f"{slug}@{inst.version}")
    g.db.commit()
    return _install_out(inst)


@router.post("/workspaces/{workspace_id}/plugins/{slug}/update")
def update_plugin(
    workspace_id: str,
    slug: str,
    body: InstallBody | None = None,
    g: Guard = Depends(guard),
):
    try:
        inst = kernel.update(
            g.db, workspace_id, slug, version=(body.version if body else "")
        )
    except kernel.KernelError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    audit(g.db, actor=g.actor, action="plugin.update",
          workspace_id=workspace_id, detail=f"{slug}@{inst.version}")
    g.db.commit()
    return _install_out(inst)


@router.post("/workspaces/{workspace_id}/plugins/{slug}/rollback")
def rollback_plugin(workspace_id: str, slug: str, g: Guard = Depends(guard)):
    try:
        inst = kernel.rollback(g.db, workspace_id, slug)
    except kernel.KernelError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    audit(g.db, actor=g.actor, action="plugin.rollback",
          workspace_id=workspace_id, detail=f"{slug}@{inst.version}")
    g.db.commit()
    return _install_out(inst)


@router.post("/workspaces/{workspace_id}/plugins/{slug}/enable")
def enable_plugin(workspace_id: str, slug: str, g: Guard = Depends(guard)):
    try:
        inst = kernel.set_enabled(g.db, workspace_id, slug, enabled=True)
    except kernel.KernelError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    g.db.commit()
    return _install_out(inst)


@router.post("/workspaces/{workspace_id}/plugins/{slug}/disable")
def disable_plugin(workspace_id: str, slug: str, g: Guard = Depends(guard)):
    try:
        inst = kernel.set_enabled(g.db, workspace_id, slug, enabled=False)
    except kernel.KernelError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    g.db.commit()
    return _install_out(inst)


@router.delete("/workspaces/{workspace_id}/plugins/{slug}", status_code=204)
def uninstall_plugin(workspace_id: str, slug: str, g: Guard = Depends(guard)):
    try:
        kernel.uninstall(g.db, workspace_id, slug)
    except kernel.KernelError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    audit(g.db, actor=g.actor, action="plugin.uninstall",
          workspace_id=workspace_id, detail=slug)
    g.db.commit()


@router.get("/workspaces/{workspace_id}/plugins")
def list_installed(workspace_id: str, g: Guard = Depends(guard)):
    """List all plugins installed in a workspace."""
    insts = g.db.execute(
        select(PluginInstall).where(PluginInstall.workspace_id == workspace_id)
    ).scalars().all()
    return {"items": [_install_out(i) for i in insts]}


@router.get("/workspaces/{workspace_id}/plugins/{slug}/permissions")
def check_permissions(workspace_id: str, slug: str, g: Guard = Depends(guard)):
    """List which permissions a plugin has in this workspace."""
    plugin = g.db.execute(
        select(Plugin).where(Plugin.slug == slug)
    ).scalar_one_or_none()
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"plugin {slug!r} not found")
    inst = g.db.execute(
        select(PluginInstall).where(
            PluginInstall.workspace_id == workspace_id,
            PluginInstall.plugin_id == plugin.id,
        )
    ).scalar_one_or_none()
    if inst is None:
        raise HTTPException(status_code=404, detail=f"{slug} not installed")
    return {
        "slug": slug,
        "enabled": bool(inst.enabled),
        "granted": inst.granted_permissions,
        "available": list(kernel.PERMISSIONS),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plugin_out(p: Plugin) -> dict:
    return {
        "id": p.id,
        "slug": p.slug,
        "name": p.name,
        "kind": p.kind,
        "description": p.description,
        "author": p.author,
        "first_party": bool(p.first_party),
        "latest_version": p.latest_version,
        "created_at": p.created_at,
    }


def _install_out(i: PluginInstall) -> dict:
    return {
        "id": i.id,
        "plugin_id": i.plugin_id,
        "workspace_id": i.workspace_id,
        "version": i.version,
        "previous_version": i.previous_version,
        "enabled": bool(i.enabled),
        "auto_update": bool(i.auto_update),
        "granted_permissions": i.granted_permissions,
        "installed_at": i.installed_at,
        "updated_at": i.updated_at,
    }
