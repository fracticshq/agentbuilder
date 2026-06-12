from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from commons.types.requests import MessageRequest, PageContext

from app.connections import connection_manager
from app.dependencies import get_message_service
from app.services.agent_api_keys import AgentApiKeyContext, AgentApiKeyService
from app.services.message_service import MessageService


logger = structlog.get_logger()
router = APIRouter()
SESSIONS_COLLECTION = "agent_api_sessions"


class AgentApiSessionCreateRequest(BaseModel):
    agent_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentApiMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: str | None = None
    conversation_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    page_context: PageContext | None = None
    filters: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _extract_api_key(authorization: str | None, x_api_key: str | None, x_agent_api_key: str | None) -> str | None:
    if x_agent_api_key:
        return x_agent_api_key
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


async def _authenticate(
    required_scope: str,
    authorization: str | None,
    x_api_key: str | None,
    x_agent_api_key: str | None,
) -> AgentApiKeyContext:
    return await AgentApiKeyService().authenticate(
        _extract_api_key(authorization, x_api_key, x_agent_api_key),
        required_scope=required_scope,
    )


def _sessions_collection():
    return connection_manager.get_system_db()[SESSIONS_COLLECTION]


def _public_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": session.get("id"),
        "conversation_id": session.get("conversation_id"),
        "agent_id": session.get("agent_id"),
        "brand_id": session.get("brand_id"),
        "user_id": session.get("user_id"),
        "metadata": session.get("metadata") or {},
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "last_message_id": session.get("last_message_id"),
    }


async def _get_agent(agent_id: str) -> dict[str, Any] | None:
    return await connection_manager.get_system_db().agents.find_one({"id": agent_id})


async def _load_session(session_id: str) -> dict[str, Any]:
    session = await _sessions_collection().find_one({"id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _assert_session_allowed(context: AgentApiKeyContext, session: dict[str, Any]) -> None:
    if context.agent_id and session.get("agent_id") != context.agent_id:
        raise HTTPException(status_code=403, detail="Agent API key is not allowed for this session")
    if context.brand_id and session.get("brand_id") != context.brand_id:
        raise HTTPException(status_code=403, detail="Agent API key is not allowed for this brand")


def _agent_api_config(agent: dict[str, Any] | None) -> dict[str, Any]:
    configuration = (agent or {}).get("configuration") or {}
    agent_api = configuration.get("agent_api") or {}
    return agent_api if isinstance(agent_api, dict) else {}


def _assert_agent_api_enabled(
    context: AgentApiKeyContext,
    agent: dict[str, Any] | None,
    *,
    origin: str | None = None,
) -> None:
    config = _agent_api_config(agent)
    if config.get("enabled") is False:
        raise HTTPException(status_code=403, detail="Agent API is disabled for this agent")

    key_ids = config.get("key_ids") or []
    if isinstance(key_ids, list) and key_ids and context.key_id not in {str(key_id) for key_id in key_ids}:
        raise HTTPException(status_code=403, detail="Agent API key is not enabled for this agent")

    allowed_origins = config.get("allowed_origins") or []
    if isinstance(allowed_origins, list) and allowed_origins and origin:
        if origin not in {str(allowed_origin) for allowed_origin in allowed_origins}:
            raise HTTPException(status_code=403, detail="Origin is not allowed for this agent")


async def _find_session_by_conversation(conversation_id: str) -> dict[str, Any] | None:
    return await _sessions_collection().find_one({"conversation_id": conversation_id})


async def _resolve_message_target(
    request: AgentApiMessageRequest,
    context: AgentApiKeyContext,
    *,
    origin: str | None = None,
) -> tuple[str, str, dict[str, Any] | None]:
    session: dict[str, Any] | None = None
    agent_id = request.agent_id or context.agent_id
    conversation_id: str | None = None

    if request.session_id:
        # Conversation identity is derived from the session, which is scope-checked.
        # A client-supplied conversation_id is never trusted to override it.
        session = await _load_session(request.session_id)
        _assert_session_allowed(context, session)
        agent_id = agent_id or session.get("agent_id")
        conversation_id = session.get("conversation_id") or session.get("id")
    elif request.conversation_id:
        # Continuing a conversation by id requires that the id belongs to a session
        # this key owns. Otherwise a key holder could read or append to another
        # user's conversation on the same agent by guessing/replaying its id.
        session = await _find_session_by_conversation(request.conversation_id)
        if not session:
            raise HTTPException(
                status_code=403,
                detail="Unknown conversation_id. Create a session before continuing a conversation.",
            )
        _assert_session_allowed(context, session)
        agent_id = agent_id or session.get("agent_id")
        conversation_id = session.get("conversation_id") or session.get("id")

    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")

    agent = await _get_agent(agent_id)
    AgentApiKeyService().assert_agent_allowed(context, agent)
    _assert_agent_api_enabled(context, agent, origin=origin)
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    return agent_id, conversation_id, session


def _message_response_payload(response: Any, *, message_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "conversation_id": response.conversation_id,
        "message_id": message_id,
        "answer": response.message,
        "citations": [
            citation.model_dump() if hasattr(citation, "model_dump") else dict(citation)
            for citation in (response.citations or [])
        ],
        "products": [],
        "dealers": [],
        "tool_calls": [],
        "metadata": {
            **(metadata or {}),
            "context_used": response.context_used,
            "confidence_score": response.confidence_score,
            "processing_time_ms": response.processing_time_ms,
            "timestamp": response.timestamp.isoformat() if hasattr(response.timestamp, "isoformat") else response.timestamp,
        },
    }


@router.post("/sessions")
async def create_session(
    request: AgentApiSessionCreateRequest,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    x_agent_api_key: str | None = Header(None),
    origin: str | None = Header(None),
) -> dict[str, Any]:
    context = await _authenticate("sessions:create", authorization, x_api_key, x_agent_api_key)
    agent_id = request.agent_id or context.agent_id
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")

    agent = await _get_agent(agent_id)
    AgentApiKeyService().assert_agent_allowed(context, agent)
    _assert_agent_api_enabled(context, agent, origin=origin)

    now = datetime.now(timezone.utc)
    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "conversation_id": session_id,
        "agent_id": agent_id,
        "brand_id": agent.get("brand_id"),
        "user_id": request.user_id or f"agent-api:{context.key_id}",
        "metadata": request.metadata,
        "created_at": now,
        "updated_at": now,
    }
    await _sessions_collection().insert_one(session)
    return {"session": _public_session(session)}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    x_agent_api_key: str | None = Header(None),
    origin: str | None = Header(None),
) -> dict[str, Any]:
    context = await _authenticate("sessions:read", authorization, x_api_key, x_agent_api_key)
    session = await _load_session(session_id)
    _assert_session_allowed(context, session)
    agent = await _get_agent(session.get("agent_id"))
    AgentApiKeyService().assert_agent_allowed(context, agent)
    _assert_agent_api_enabled(context, agent, origin=origin)
    return {"session": _public_session(session)}


@router.post("/messages")
async def create_message(
    request: AgentApiMessageRequest,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    x_agent_api_key: str | None = Header(None),
    origin: str | None = Header(None),
    message_service: MessageService = Depends(get_message_service),
) -> dict[str, Any]:
    context = await _authenticate("messages:write", authorization, x_api_key, x_agent_api_key)
    agent_id, conversation_id, session = await _resolve_message_target(request, context, origin=origin)
    user_id = request.user_id or (session or {}).get("user_id") or f"agent-api:{context.key_id}"
    message_id = str(uuid.uuid4())

    response = await message_service.process_message(
        MessageRequest(
            message=request.message,
            user_id=user_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            page_context=request.page_context,
            filters=request.filters,
        )
    )
    if session:
        await _sessions_collection().update_one(
            {"id": session["id"]},
            {"$set": {"updated_at": datetime.now(timezone.utc), "last_message_id": message_id}},
        )
    return _message_response_payload(response, message_id=message_id, metadata=request.metadata)


@router.post("/messages/stream")
async def stream_message(
    request: AgentApiMessageRequest,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    x_agent_api_key: str | None = Header(None),
    origin: str | None = Header(None),
    message_service: MessageService = Depends(get_message_service),
):
    context = await _authenticate("messages:stream", authorization, x_api_key, x_agent_api_key)
    agent_id, conversation_id, session = await _resolve_message_target(request, context, origin=origin)
    user_id = request.user_id or (session or {}).get("user_id") or f"agent-api:{context.key_id}"
    message_id = str(uuid.uuid4())

    async def generate_stream():
        yield f"data: {json.dumps({'type': 'metadata', 'conversation_id': conversation_id, 'message_id': message_id})}\n\n"
        async for chunk in message_service.stream_message(
            MessageRequest(
                message=request.message,
                user_id=user_id,
                conversation_id=conversation_id,
                agent_id=agent_id,
                page_context=request.page_context,
                filters=request.filters,
                stream=True,
            )
        ):
            yield f"data: {chunk.model_dump_json()}\n\n"
            await asyncio.sleep(0.01)
        if session:
            await _sessions_collection().update_one(
                {"id": session["id"]},
                {"$set": {"updated_at": datetime.now(timezone.utc), "last_message_id": message_id}},
            )

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    x_agent_api_key: str | None = Header(None),
    origin: str | None = Header(None),
) -> dict[str, Any]:
    context = await _authenticate("agents:read", authorization, x_api_key, x_agent_api_key)
    agent = await _get_agent(agent_id)
    AgentApiKeyService().assert_agent_allowed(context, agent)
    _assert_agent_api_enabled(context, agent, origin=origin)
    return {
        "agent": {
            "id": agent.get("id"),
            "brand_id": agent.get("brand_id"),
            "brand_slug": agent.get("brand_slug"),
            "name": agent.get("name"),
            "description": agent.get("description"),
            "status": agent.get("status"),
        }
    }


@router.websocket("/messages/ws")
async def websocket_messages(
    websocket: WebSocket,
    api_key: str | None = Query(None),
    message_service: MessageService = Depends(get_message_service),
):
    try:
        context = await AgentApiKeyService().authenticate(
            api_key or _extract_api_key(websocket.headers.get("authorization"), websocket.headers.get("x-api-key"), websocket.headers.get("x-agent-api-key")),
            required_scope="messages:stream",
        )
    except HTTPException as exc:
        await websocket.close(code=1008, reason=str(exc.detail))
        return

    await websocket.accept()
    try:
        while True:
            payload = json.loads(await websocket.receive_text())
            request = AgentApiMessageRequest(**payload)
            agent_id, conversation_id, session = await _resolve_message_target(
                request,
                context,
                origin=websocket.headers.get("origin"),
            )
            user_id = request.user_id or (session or {}).get("user_id") or f"agent-api:{context.key_id}"
            await websocket.send_text(json.dumps({"type": "metadata", "conversation_id": conversation_id, "message_id": str(uuid.uuid4())}))
            async for chunk in message_service.stream_message(
                MessageRequest(
                    message=request.message,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    page_context=request.page_context,
                    filters=request.filters,
                    stream=True,
                )
            ):
                await websocket.send_text(chunk.model_dump_json())
    except WebSocketDisconnect:
        logger.info("agent_api_websocket_disconnected")
    except HTTPException as exc:
        await websocket.close(code=1008, reason=str(exc.detail))
    except Exception as exc:
        logger.error("agent_api_websocket_error", error=str(exc))
        await websocket.close(code=1011, reason="Internal error")
