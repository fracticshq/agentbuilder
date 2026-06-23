from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from tools.types import ToolResult

from app.auth.dependencies import require_dashboard_access
from app.auth.models import GLOBAL_ADMIN_ROLES, User, UserRole
from app.config import Settings
from app.connections import connection_manager
from app.dependencies import get_runtime_settings_service
from app.services.context_connector_packs import get_connector_pack, list_connector_packs
from app.services.lalkitab_runtime import normalize_lalkitab_endpoint
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.tool_config_secrets import (
    decrypt_full_agent_configuration_for_runtime,
    expose_full_agent_for_admin,
    protect_full_agent_configuration_secrets,
)
from app.services.tool_registry import ContextConnectorTool, _is_safe_external_url
from tools.mcp_client import McpClient

router = APIRouter(dependencies=[Depends(require_dashboard_access)])
settings = Settings()

CONNECTOR_READ_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.ADMIN,
    UserRole.ORG_ADMIN,
    UserRole.BRAND_ADMIN,
    UserRole.OPERATOR,
}
CONNECTOR_WRITE_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.ADMIN,
    UserRole.ORG_ADMIN,
    UserRole.BRAND_ADMIN,
}


class ConnectorToggleRequest(BaseModel):
    enabled: bool


class ConnectorTestRequest(BaseModel):
    endpoint_id: str | None = None
    query: str = "Test this configured context connector."
    payload: dict[str, Any] | None = None


class ConnectorDiscoverRequest(BaseModel):
    url: str | None = None
    endpoint: str | None = None
    auth_header: str | None = None


def _agents_collection():
    if connection_manager.system_db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return connection_manager.system_db.agents


async def _agent_or_404(agent_id: str) -> dict[str, Any]:
    agent = await _agents_collection().find_one({"id": agent_id})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _ensure_connector_access(user: User | None, agent: dict[str, Any] | None = None, *, write: bool = False) -> None:
    # require_dashboard_access returns None only for the local/dev admin-key path.
    if user is None:
        if settings.is_production:
            raise HTTPException(status_code=401, detail="User authentication required for connector administration")
        return
    allowed_roles = CONNECTOR_WRITE_ROLES if write else CONNECTOR_READ_ROLES
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Context connector access is restricted")
    if agent is None or user.role in GLOBAL_ADMIN_ROLES:
        return
    brand_id = agent.get("brand_id")
    if not brand_id or not user.has_brand_access(str(brand_id)):
        raise HTTPException(status_code=403, detail="Agent is outside the current user's brand scope")


async def _scoped_agent_or_404(agent_id: str, user: User | None, *, write: bool = False) -> dict[str, Any]:
    agent = await _agent_or_404(agent_id)
    _ensure_connector_access(user, agent, write=write)
    return agent


def _host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(str(url))
    if "{" in (parsed.netloc or "") or "}" in (parsed.netloc or ""):
        return None
    return (parsed.hostname or "").lower() or None


def _normalize_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(endpoint or {})
    normalized["id"] = str(normalized.get("id") or f"endpoint_{uuid.uuid4().hex[:8]}")
    normalized["name"] = str(normalized.get("name") or normalized["id"])
    normalized["enabled"] = bool(normalized.get("enabled", True))
    normalized["method"] = str(normalized.get("method") or "POST").upper()
    if normalized.get("url") and not normalized.get("url_template"):
        normalized["url_template"] = normalized["url"]
    if normalized.get("url_template") and not normalized.get("url"):
        normalized["url"] = normalized["url_template"]
    if normalized.get("required_fields") and not normalized.get("required_user_fields"):
        normalized["required_user_fields"] = normalized["required_fields"]
    if normalized.get("required_user_fields") and not normalized.get("required_fields"):
        normalized["required_fields"] = normalized["required_user_fields"]
    if normalized.get("description") and not normalized.get("tool_description"):
        normalized["tool_description"] = normalized["description"]
    return normalized


def _normalize_connector(connector: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(connector or {})
    normalized["id"] = str(normalized.get("id") or f"conn_{uuid.uuid4().hex[:10]}")
    normalized["name"] = str(normalized.get("name") or normalized["id"])
    normalized["type"] = "http_api" if normalized.get("type") in {None, "", "http"} else normalized.get("type")
    normalized["enabled"] = bool(normalized.get("enabled", True))
    normalized["updated_at"] = datetime.utcnow().isoformat()

    if normalized.get("auth_header"):
        normalized["auth"] = {
            **(normalized.get("auth") if isinstance(normalized.get("auth"), dict) else {}),
            "type": "raw_header",
            "auth_header": normalized.get("auth_header"),
        }
    normalized.pop("auth_header", None)

    endpoints = normalized.get("endpoints")
    normalized["endpoints"] = [
        _normalize_endpoint(endpoint)
        for endpoint in (endpoints if isinstance(endpoints, list) else [])
        if isinstance(endpoint, dict)
    ]
    if not normalized.get("domain_allowlist"):
        hosts: list[str] = []
        if normalized.get("type") == "mcp":
            host = _host_from_url(normalized.get("endpoint") or (normalized.get("mcp") or {}).get("endpoint"))
            if host:
                hosts.append(host)
        for endpoint in normalized["endpoints"]:
            host = _host_from_url(endpoint.get("url_template") or endpoint.get("url"))
            if host:
                hosts.append(host)
        if hosts:
            normalized["domain_allowlist"] = sorted(set(hosts))
    return normalized


def _public_connector(connector: dict[str, Any]) -> dict[str, Any]:
    public = deepcopy(connector)
    auth = public.get("auth")
    if isinstance(auth, dict) and auth.get("auth_header_configured") and not public.get("auth_header_configured"):
        public["auth_header_configured"] = True
    return public


async def _save_connectors(
    agent: dict[str, Any],
    connectors: list[dict[str, Any]],
    runtime_settings_service: RuntimeSettingsService,
) -> list[dict[str, Any]]:
    existing_config = agent.get("configuration") or {}
    next_config = {
        **existing_config,
        "context_connectors": connectors,
    }
    protected_config = protect_full_agent_configuration_secrets(
        next_config,
        existing_config=existing_config,
        runtime_settings_service=runtime_settings_service,
    )
    await _agents_collection().update_one(
        {"id": agent["id"]},
        {"$set": {"configuration": protected_config, "updated_at": datetime.utcnow()}},
    )
    updated = await _agents_collection().find_one({"id": agent["id"]})
    exposed = expose_full_agent_for_admin(updated, runtime_settings_service)
    return exposed.get("configuration", {}).get("context_connectors") or []


@router.get("/packs")
async def list_packs(current_user: User | None = Depends(require_dashboard_access)):
    _ensure_connector_access(current_user)
    return {"packs": list_connector_packs()}


@router.get("/packs/{pack_id}")
async def get_pack(pack_id: str, current_user: User | None = Depends(require_dashboard_access)):
    _ensure_connector_access(current_user)
    pack = get_connector_pack(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Connector pack not found")
    return {"pack": pack}


@router.get("/{agent_id}/connectors")
async def list_agent_connectors(
    agent_id: str,
    current_user: User | None = Depends(require_dashboard_access),
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    agent = await _scoped_agent_or_404(agent_id, current_user)
    exposed = expose_full_agent_for_admin(agent, runtime_settings_service)
    return {"connectors": exposed.get("configuration", {}).get("context_connectors") or []}


@router.put("/{agent_id}/connectors")
async def upsert_agent_connector(
    agent_id: str,
    connector: dict[str, Any],
    current_user: User | None = Depends(require_dashboard_access),
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    agent = await _scoped_agent_or_404(agent_id, current_user, write=True)
    normalized = _normalize_connector(connector)
    existing = [
        item
        for item in (agent.get("configuration") or {}).get("context_connectors") or []
        if isinstance(item, dict)
    ]
    next_connectors = []
    replaced = False
    for item in existing:
        if item.get("id") == normalized["id"]:
            next_connectors.append(normalized)
            replaced = True
        else:
            next_connectors.append(item)
    if not replaced:
        next_connectors.append(normalized)

    exposed_connectors = await _save_connectors(agent, next_connectors, runtime_settings_service)
    saved = next((item for item in exposed_connectors if item.get("id") == normalized["id"]), normalized)
    return {"connector": _public_connector(saved), "connectors": exposed_connectors}


@router.post("/{agent_id}/connectors/packs/{pack_id}")
async def attach_connector_pack(
    agent_id: str,
    pack_id: str,
    current_user: User | None = Depends(require_dashboard_access),
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    pack = get_connector_pack(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Connector pack not found")
    pack["id"] = pack_id
    agent = await _scoped_agent_or_404(agent_id, current_user, write=True)
    normalized = _normalize_connector(pack)
    existing = [
        item
        for item in (agent.get("configuration") or {}).get("context_connectors") or []
        if isinstance(item, dict) and item.get("id") != normalized["id"]
    ]
    exposed_connectors = await _save_connectors(agent, [*existing, normalized], runtime_settings_service)
    saved = next((item for item in exposed_connectors if item.get("id") == normalized["id"]), normalized)
    return {"connector": _public_connector(saved), "connectors": exposed_connectors}


@router.delete("/{agent_id}/connectors/{connector_id}")
async def revoke_agent_connector(
    agent_id: str,
    connector_id: str,
    current_user: User | None = Depends(require_dashboard_access),
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    agent = await _scoped_agent_or_404(agent_id, current_user, write=True)
    found = False
    next_connectors = []
    for connector in (agent.get("configuration") or {}).get("context_connectors") or []:
        if not isinstance(connector, dict):
            continue
        if connector.get("id") == connector_id:
            found = True
            connector = {
                **connector,
                "enabled": False,
                "revoked": True,
                "revoked_at": datetime.utcnow().isoformat(),
            }
        next_connectors.append(connector)
    if not found:
        raise HTTPException(status_code=404, detail="Connector not found")
    exposed = await _save_connectors(agent, next_connectors, runtime_settings_service)
    return {"connectors": exposed}


@router.post("/{agent_id}/connectors/{connector_id}/toggle")
async def toggle_agent_connector(
    agent_id: str,
    connector_id: str,
    request: ConnectorToggleRequest,
    current_user: User | None = Depends(require_dashboard_access),
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    agent = await _scoped_agent_or_404(agent_id, current_user, write=True)
    found = False
    next_connectors = []
    for connector in (agent.get("configuration") or {}).get("context_connectors") or []:
        if not isinstance(connector, dict):
            continue
        if connector.get("id") == connector_id:
            found = True
            if connector.get("revoked") and request.enabled:
                raise HTTPException(status_code=409, detail="Revoked connectors must be re-created with fresh credentials")
            connector = {
                **connector,
                "enabled": bool(request.enabled),
            }
        next_connectors.append(connector)
    if not found:
        raise HTTPException(status_code=404, detail="Connector not found")
    exposed = await _save_connectors(agent, next_connectors, runtime_settings_service)
    saved = next((item for item in exposed if item.get("id") == connector_id), {})
    return {"connector": saved, "connectors": exposed}


@router.post("/{agent_id}/connectors/{connector_id}/test")
async def test_agent_connector(
    agent_id: str,
    connector_id: str,
    request: ConnectorTestRequest,
    current_user: User | None = Depends(require_dashboard_access),
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    agent = await _scoped_agent_or_404(agent_id, current_user)
    runtime_config = decrypt_full_agent_configuration_for_runtime(
        agent.get("configuration") or {},
        runtime_settings_service,
    )
    connector = next(
        (
            item
            for item in runtime_config.get("context_connectors") or []
            if isinstance(item, dict) and item.get("id") == connector_id
        ),
        None,
    )
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    if not connector.get("enabled", True) or connector.get("revoked"):
        raise HTTPException(status_code=409, detail="Connector is disabled or revoked")
    endpoint = next(
        (
            item
            for item in connector.get("endpoints") or []
            if isinstance(item, dict)
            and (not request.endpoint_id or item.get("id") == request.endpoint_id)
            and item.get("enabled", True)
            and not item.get("revoked")
        ),
        None,
    )
    if not endpoint:
        raise HTTPException(status_code=404, detail="Enabled endpoint not found")
    endpoint = normalize_lalkitab_endpoint(endpoint)

    result: ToolResult = await ContextConnectorTool(connector, endpoint).run(
        query=request.query,
        payload=request.payload or {},
    )
    return {
        "success": bool(result.success),
        "data": result.data,
        "error": result.error,
        "metadata": result.metadata,
    }


@router.post("/{agent_id}/connectors/discover")
async def discover_connector_tools(
    agent_id: str,
    request: ConnectorDiscoverRequest,
    current_user: User | None = Depends(require_dashboard_access),
):
    await _scoped_agent_or_404(agent_id, current_user, write=True)
    endpoint = str(request.endpoint or request.url or "").strip()
    safe, reason = _is_safe_external_url(endpoint)
    if not safe:
        raise HTTPException(status_code=400, detail=f"MCP endpoint is not allowed: {reason}")
    headers = {}
    if request.auth_header:
        name, _, value = request.auth_header.partition(":")
        if name.strip() and value.strip():
            headers[name.strip()] = value.strip()
    tools = await McpClient(endpoint=endpoint, headers=headers).discover_tools(session_id=f"agent:{agent_id}:discovery")
    return {
        "discovered_tools": [
            {
                "name": tool.name,
                "description": getattr(tool, "description", ""),
                "inputSchema": getattr(tool, "parameters_schema", {}),
            }
            for tool in tools
        ],
        "status": "ok" if tools else "no_tools_discovered",
        "endpoint": endpoint,
    }
