from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import ensure_brand_access, ensure_permission, is_global_admin, require_dashboard_access
from app.auth.models import Permission, User
from app.connections import connection_manager
from app.dependencies import get_observability_service
from app.services.observability_service import ObservabilityService

router = APIRouter(dependencies=[Depends(require_dashboard_access)])


@router.get("/summary")
async def get_observability_summary(
    brand_slug: str | None = Query(None),
    agent_id: str | None = Query(None),
    range_hours: int = Query(24, ge=1, le=720),
    service: ObservabilityService = Depends(get_observability_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    ensure_permission(current_user, Permission.MESSAGE_READ)
    if agent_id:
        agent = await connection_manager.get_system_db().agents.find_one({"id": agent_id})
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        ensure_brand_access(current_user, agent.get("brand_id"))
        # Prevent a caller from mixing a scoped agent and another tenant's slug.
        if brand_slug and brand_slug != agent.get("brand_slug"):
            raise HTTPException(status_code=404, detail="Brand not found")
        brand_slug = agent.get("brand_slug")
    elif brand_slug:
        brand = await connection_manager.get_system_db().brands.find_one({"slug": brand_slug})
        if not brand:
            raise HTTPException(status_code=404, detail="Brand not found")
        ensure_brand_access(current_user, brand.get("id"))
    elif not is_global_admin(current_user):
        raise HTTPException(status_code=400, detail="brand_slug or agent_id is required")

    return await service.summarize(
        brand_slug=brand_slug,
        agent_id=agent_id,
        range_hours=range_hours,
    )
