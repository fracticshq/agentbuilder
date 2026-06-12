import asyncio
import json
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import structlog

from app.auth.dependencies import require_console_access
from app.auth.models import GLOBAL_ADMIN_ROLES, User, UserRole
from app.connections import connection_manager
from app.dependencies import get_message_service, get_runtime_settings_service
from app.services.message_service import MessageService
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.tool_config_secrets import expose_full_agent_for_admin
from commons.types.requests import MessageRequest

logger = structlog.get_logger()
router = APIRouter()
SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "api_key",
    "authorization",
    "auth_header",
    "client_secret",
)


class ConsoleMessageRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    user_id: Optional[str] = "admin-console"
    page_context: Optional[dict] = None
    filters: Optional[dict] = None


def _agents_collection():
    if connection_manager.system_db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return connection_manager.system_db.agents


def _can_use_console(user: Optional[User]) -> bool:
    if user is None:
        return True
    return user.role in {
        UserRole.SUPER_ADMIN,
        UserRole.ADMIN,
        UserRole.ORG_ADMIN,
        UserRole.BRAND_ADMIN,
        UserRole.OPERATOR,
    }


def _ensure_console_access(user: Optional[User]) -> None:
    if not _can_use_console(user):
        raise HTTPException(status_code=403, detail="Agent Console access is restricted")


def _ensure_brand_access(user: Optional[User], agent: dict) -> None:
    if user is None:
        return
    if user.role in GLOBAL_ADMIN_ROLES:
        return
    brand_id = agent.get("brand_id")
    if not brand_id or not user.has_brand_access(brand_id):
        raise HTTPException(status_code=403, detail="Agent is outside the current user's brand scope")


def _json_safe(value, key_name: str = ""):
    if isinstance(value, ObjectId):
        return str(value)
    if any(part in key_name.lower() for part in SENSITIVE_KEY_PARTS):
        if value in (None, "", False):
            return value
        if isinstance(value, bool):
            return value
        return "********"
    if isinstance(value, dict):
        return {key: _json_safe(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item, key_name) for item in value]
    return value


def _safe_admin_agent(agent: dict, runtime_settings_service: RuntimeSettingsService) -> dict:
    return _json_safe(expose_full_agent_for_admin(agent, runtime_settings_service))


async def _get_console_agent_or_404(agent_id: str, user: Optional[User]) -> dict:
    _ensure_console_access(user)
    agent = await _agents_collection().find_one({"id": agent_id})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    _ensure_brand_access(user, agent)
    return agent


@router.get("/agents")
async def list_console_agents(
    current_user: Optional[User] = Depends(require_console_access),
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    _ensure_console_access(current_user)
    query = {}
    if current_user is not None and current_user.role not in GLOBAL_ADMIN_ROLES:
        query = {"brand_id": {"$in": current_user.brands or []}}

    agents = await _agents_collection().find(query).sort("updated_at", -1).to_list(length=None)
    return {
        "agents": [
            _safe_admin_agent(agent, runtime_settings_service)
            for agent in agents
        ]
    }


@router.get("/agents/{agent_id}")
async def get_console_agent(
    agent_id: str,
    current_user: Optional[User] = Depends(require_console_access),
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    agent = await _get_console_agent_or_404(agent_id, current_user)
    safe_agent = _safe_admin_agent(agent, runtime_settings_service)
    config = safe_agent.get("configuration") or {}
    return {
        "agent": safe_agent,
        "console": {
            "knowledge_enabled": bool(config.get("rag", {}).get("enabled")),
            "skills": (config.get("skills") or {}).get("selected", []),
            "tools": (config.get("tools") or {}).get("selected", []),
            "api_data_source": {
                "enabled": bool((config.get("api_data_source") or {}).get("enabled")),
                "name": (config.get("api_data_source") or {}).get("name"),
            },
        },
    }


@router.post("/agents/{agent_id}/messages/stream")
async def stream_console_message(
    agent_id: str,
    request: ConsoleMessageRequest,
    current_user: Optional[User] = Depends(require_console_access),
    message_service: MessageService = Depends(get_message_service),
):
    await _get_console_agent_or_404(agent_id, current_user)
    message_request = MessageRequest(
        agent_id=agent_id,
        message=request.message,
        conversation_id=request.conversation_id or f"agent-console-{agent_id}",
        user_id=request.user_id or "admin-console",
        page_context=request.page_context,
        filters=request.filters,
    )

    async def generate_stream():
        try:
            async for chunk in message_service.stream_message(message_request):
                yield f"data: {chunk.model_dump_json()}\n\n"
                await asyncio.sleep(0.01)
        except Exception as exc:
            logger.error("console_stream_error", agent_id=agent_id, error=str(exc))
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/agents/{agent_id}/runs")
async def list_console_runs(
    agent_id: str,
    current_user: Optional[User] = Depends(require_console_access),
):
    await _get_console_agent_or_404(agent_id, current_user)
    return {
        "runs": [],
        "status": "trace_persistence_pending",
    }
