from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import ensure_permission, require_dashboard_access
from app.auth.models import GLOBAL_ADMIN_ROLES, Permission, User
from app.connections import connection_manager
from app.services.agent_api_keys import AgentApiKeyService, DEFAULT_AGENT_API_SCOPES


router = APIRouter()


class AgentApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_AGENT_API_SCOPES))
    agent_id: str | None = None
    brand_id: str | None = None


def _is_global_admin(user: User | None) -> bool:
    return user is None or user.role in GLOBAL_ADMIN_ROLES


def _created_by(user: User | None) -> str:
    if user is None:
        return "admin-key"
    return str(user.id or user.email)


async def _get_agent(agent_id: str) -> dict[str, Any]:
    agent = await connection_manager.get_system_db().agents.find_one({"id": agent_id})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _ensure_brand_access(user: User | None, brand_id: str | None) -> None:
    if _is_global_admin(user):
        return
    if not brand_id:
        raise HTTPException(status_code=403, detail="Brand scope is required for this user")
    if not user.has_brand_access(brand_id):
        raise HTTPException(status_code=403, detail="Brand is outside the current user's scope")


async def _resolve_authorized_scope(
    user: User | None,
    *,
    agent_id: str | None,
    brand_id: str | None,
) -> tuple[str | None, str | None]:
    resolved_brand_id = brand_id
    if agent_id:
        agent = await _get_agent(agent_id)
        agent_brand_id = agent.get("brand_id")
        _ensure_brand_access(user, agent_brand_id)
        if resolved_brand_id and resolved_brand_id != agent_brand_id:
            raise HTTPException(status_code=400, detail="agent_id and brand_id do not belong to the same brand")
        resolved_brand_id = agent_brand_id
    elif brand_id:
        _ensure_brand_access(user, brand_id)
    elif not _is_global_admin(user):
        raise HTTPException(status_code=403, detail="Brand or agent scope is required for this user")
    return agent_id, resolved_brand_id


@router.get("/keys")
async def list_agent_api_keys(
    agent_id: str | None = Query(None),
    brand_id: str | None = Query(None),
    current_user: User | None = Depends(require_dashboard_access),
) -> dict[str, Any]:
    ensure_permission(current_user, Permission.API_KEY_READ)
    if not _is_global_admin(current_user) and not agent_id and not brand_id:
        return {"keys": await AgentApiKeyService().list_keys(brand_ids=current_user.brands or [])}

    agent_id, brand_id = await _resolve_authorized_scope(current_user, agent_id=agent_id, brand_id=brand_id)
    if _is_global_admin(current_user):
        keys = await AgentApiKeyService().list_keys(agent_id=agent_id, brand_id=brand_id)
    elif brand_id:
        keys = await AgentApiKeyService().list_keys(agent_id=agent_id, brand_id=brand_id)
    else:
        keys = []
    return {"keys": keys}


@router.post("/keys")
async def create_agent_api_key(
    request: AgentApiKeyCreateRequest,
    current_user: User | None = Depends(require_dashboard_access),
) -> dict[str, Any]:
    ensure_permission(current_user, Permission.API_KEY_WRITE)
    agent_id, brand_id = await _resolve_authorized_scope(
        current_user,
        agent_id=request.agent_id,
        brand_id=request.brand_id,
    )
    key = await AgentApiKeyService().create_key(
        name=request.name,
        scopes=request.scopes,
        agent_id=agent_id,
        brand_id=brand_id,
        created_by=_created_by(current_user),
    )
    return {"key": key}


@router.post("/keys/{key_id}/revoke")
async def revoke_agent_api_key(
    key_id: str,
    current_user: User | None = Depends(require_dashboard_access),
) -> dict[str, Any]:
    ensure_permission(current_user, Permission.API_KEY_DELETE)
    existing = await AgentApiKeyService().get_key(key_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Agent API key not found")
    _ensure_brand_access(current_user, existing.get("brand_id"))
    return {"key": await AgentApiKeyService().revoke_key(key_id)}
