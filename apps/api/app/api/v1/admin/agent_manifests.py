from __future__ import annotations

import re
from io import BytesIO

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.auth.dependencies import (
    ensure_brand_access,
    ensure_permission,
    is_global_admin,
    require_dashboard_access,
)
from app.auth.models import Permission, User
from app.connections import connection_manager
from app.services.agent_manifest_service import AgentManifestError, AgentManifestService

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(require_dashboard_access)])


def get_agents_collection():
    if connection_manager.system_db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return connection_manager.system_db.agents


def _download_filename(agent: dict) -> str:
    slug = agent.get("slug") or re.sub(r"[^a-z0-9]+", "-", (agent.get("name") or "agent").lower()).strip("-")
    return f"{slug or 'agent'}-manifest.zip"


@router.get("/{agent_id}/export")
async def export_agent_manifest(
    agent_id: str,
    current_user: User | None = Depends(require_dashboard_access),
):
    try:
        collection = get_agents_collection()
        agent = await collection.find_one({"id": agent_id})
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        ensure_permission(current_user, Permission.AGENT_READ)
        ensure_brand_access(current_user, agent.get("brand_id"))

        zip_bytes = AgentManifestService().build_zip(agent)
        filename = _download_filename(agent)
        return StreamingResponse(
            BytesIO(zip_bytes),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("agent_manifest_export_failed", agent_id=agent_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to export agent manifest.") from exc


@router.post("/import")
async def import_agent_manifest(
    file: UploadFile = File(...),
    brand_id: str | None = Form(None),
    current_user: User | None = Depends(require_dashboard_access),
):
    try:
        payload = await file.read()
        service = AgentManifestService()
        package_files = service.parse_zip(payload)
        brand_slug = None

        # Tenant operators must explicitly select a brand. A manifest is
        # portable data, not authority to select an arbitrary tenant.
        if not brand_id and not is_global_admin(current_user):
            raise HTTPException(status_code=400, detail="brand_id is required for tenant-scoped imports")

        if brand_id:
            brand = await connection_manager.get_system_db()["brands"].find_one({"id": brand_id})
            if not brand:
                raise HTTPException(status_code=404, detail=f"Brand not found: {brand_id}")
            ensure_permission(current_user, Permission.AGENT_WRITE)
            ensure_brand_access(current_user, brand_id)
            brand_slug = brand.get("slug")

        agent_doc = service.build_import_document(
            package_files,
            brand_id=brand_id,
            brand_slug=brand_slug,
        )
        ensure_permission(current_user, Permission.AGENT_WRITE)
        ensure_brand_access(current_user, agent_doc.get("brand_id"))
        collection = get_agents_collection()
        existing = await collection.find_one(
            {"brand_id": agent_doc["brand_id"], "slug": agent_doc["slug"]}
        )
        if existing:
            agent_doc["slug"] = f"{agent_doc['slug']}-{agent_doc['id'][:8]}"

        await collection.insert_one(agent_doc)
        return {
            "agent": {
                **agent_doc,
                "_id": str(agent_doc.get("_id", "")) if agent_doc.get("_id") else None,
            },
            "imported_files": sorted(package_files.keys()),
        }
    except HTTPException:
        raise
    except AgentManifestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("agent_manifest_import_failed", filename=file.filename, error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to import agent manifest.") from exc
