"""
Messages API Endpoints
"""

from typing import AsyncGenerator, Optional, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header, Query
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
import json
import asyncio
import structlog
from fastapi.security import HTTPAuthorizationCredentials

from commons.types.requests import MessageRequest
from commons.types.responses import MessageResponse, StreamingMessageResponse
from ....auth.dependencies import CONSOLE_ACCESS_ROLES, get_current_active_user, get_current_user
from ....auth.models import Permission
from ....auth.widget_session import (
    WidgetSession,
    decode_widget_session,
    encode_widget_session,
    issue_widget_session,
)
from ....connections import connection_manager
from ....dependencies import get_message_service, get_settings
from ....security.rate_limiter import check_named_rate_limit
from ....services.conversation_scope_store import (
    ConversationScope,
    ConversationScopeStoreError,
    conversation_scope_store,
)
from ....services.message_service import MessageService
from ....services.observability_service import ObservabilityService
from ....websocket_manager import ws_manager
from memory.managers.short_term import ShortTermMemory

logger = structlog.get_logger()
router = APIRouter()
WS_POLICY_VIOLATION = 1008


class SessionRequest(BaseModel):
    """Request to start or resume a widget chat session."""
    agent_id: str = Field(..., min_length=1)
    session_token: Optional[str] = None


class SessionResponse(BaseModel):
    """Server-issued, signed session bound to one conversation + user + agent."""
    conversation_id: str
    user_id: str
    session_token: str


class HistoryResponse(BaseModel):
    conversation_id: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    has_more: bool = False


def _bind_request_to_session(request: MessageRequest, session: WidgetSession) -> None:
    """Force the request to act on the token's conversation/user, ignoring client-supplied ids."""
    request.conversation_id = session.conversation_id
    request.user_id = session.user_id
    request.agent_id = session.agent_id


async def _close_websocket(websocket: WebSocket, reason: str) -> None:
    try:
        await websocket.close(code=WS_POLICY_VIOLATION, reason=reason)
    except RuntimeError:
        logger.debug("websocket_already_closed", reason=reason)


async def _safe_send_text(websocket: WebSocket, payload: str) -> bool:
    try:
        await websocket.send_text(payload)
        return True
    except (WebSocketDisconnect, RuntimeError):
        logger.info("websocket_send_skipped_closed_socket")
        return False


async def _enforce_websocket_rate_limit(
    websocket: WebSocket,
    endpoint: str,
    policy: str,
    *,
    agent_id: str | None = None,
    brand_slug: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    ip_address = websocket.client.host if websocket.client else None
    is_allowed, info = await check_named_rate_limit(
        policy,
        ip_address=ip_address,
        endpoint=endpoint,
        agent_id=agent_id,
        brand_slug=brand_slug,
        conversation_id=conversation_id,
    )
    if not is_allowed:
        resolved_brand_slug = brand_slug or await _get_agent_brand_slug(agent_id)
        await ObservabilityService().track_event(
            event_type="rate_limit",
            brand_slug=resolved_brand_slug,
            agent_id=agent_id,
            conversation_id=conversation_id,
            payload={
                "policy": info.get("policy") or policy,
                "outcome": "blocked",
                "endpoint": endpoint,
                "retry_after": info.get("retry_after"),
                "channel": "websocket",
            },
        )
        await _safe_send_text(websocket, json.dumps({
            "type": "rate_limit",
            "content": "Rate limit exceeded. Please wait before sending another message.",
            "retry_after": info.get("retry_after") or 60,
            "policy": info.get("policy") or policy,
        }))
        await _close_websocket(websocket, "Rate limit exceeded")
        return False
    return True


async def _enforce_message_rate_limit(request: MessageRequest, policy: str, endpoint: str) -> None:
    brand_slug = await _get_agent_brand_slug(request.agent_id)
    is_allowed, info = await check_named_rate_limit(
        policy,
        user_id=request.user_id,
        agent_id=request.agent_id,
        brand_slug=brand_slug,
        conversation_id=request.conversation_id,
        endpoint=endpoint,
    )
    if not is_allowed:
        await ObservabilityService().track_event(
            event_type="rate_limit",
            brand_slug=brand_slug,
            agent_id=request.agent_id,
            conversation_id=request.conversation_id,
            payload={
                "policy": info.get("policy") or policy,
                "outcome": "blocked",
                "endpoint": endpoint,
                "retry_after": info.get("retry_after"),
                "channel": "http",
            },
        )
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(info["limit"]),
                "X-RateLimit-Remaining": str(info["remaining"]),
                "X-RateLimit-Reset": str(info["reset_at"]),
                "Retry-After": str(info["retry_after"] or 60),
            },
        )


async def _get_agent_brand_slug(agent_id: str | None) -> str | None:
    if not agent_id:
        return None

    try:
        system_db = connection_manager.get_system_db()
        agent = await system_db.agents.find_one({"id": agent_id}, {"brand_slug": 1})
    except Exception as exc:
        logger.warning("agent_brand_lookup_failed", agent_id=agent_id, error=str(exc))
        return None

    brand_slug = agent.get("brand_slug") if agent else None
    return brand_slug or None


def _websocket_token(websocket: WebSocket, scheme: str) -> str | None:
    """Read a browser-safe token from a WebSocket subprotocol.

    Browsers cannot set an Authorization header for WebSocket handshakes.  The
    SDK therefore sends ``[scheme, token]`` as ``Sec-WebSocket-Protocol``.  The
    token is deliberately not accepted from a URL query string, which would
    leak it into access logs and proxy telemetry. Non-browser clients may still
    use an Authorization header.
    """
    authorization = websocket.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip() or None

    protocols = [
        item.strip()
        for item in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if item.strip()
    ]
    for index, value in enumerate(protocols[:-1]):
        if value.lower() == scheme.lower():
            return protocols[index + 1]
    return None


def _websocket_offers_protocol(websocket: WebSocket, protocol: str) -> bool:
    return any(
        value.strip().lower() == protocol.lower()
        for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if value.strip()
    )


async def _require_widget_control_scope(
    websocket: WebSocket,
    conversation_id: str,
) -> tuple[WidgetSession, ConversationScope] | None:
    token = _websocket_token(websocket, "widget-session")
    session = decode_widget_session(token)
    if session is None or session.conversation_id != conversation_id:
        await _close_websocket(websocket, "Invalid widget session")
        return None
    try:
        scope = await conversation_scope_store.get(conversation_id)
    except ConversationScopeStoreError:
        await _close_websocket(websocket, "Conversation authorization unavailable")
        return None
    if scope is None or scope.agent_id != session.agent_id or scope.user_id != session.user_id:
        await _close_websocket(websocket, "Widget session does not own this conversation")
        return None
    return session, scope


async def _require_admin_takeover_scope(
    websocket: WebSocket,
    conversation_id: str,
) -> ConversationScope | None:
    """Require an operator JWT and its creation-time tenant scope for takeover."""
    token = _websocket_token(websocket, "bearer")
    if not token:
        await _close_websocket(websocket, "Dashboard authentication required")
        return None
    try:
        system_db = connection_manager.get_system_db()
        user = await get_current_active_user(
            await get_current_user(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
                system_db,
            )
        )
        if user.role not in CONSOLE_ACCESS_ROLES or not user.has_permission(Permission.MESSAGE_WRITE):
            await _close_websocket(websocket, "Operator permission required")
            return None
        scope = await conversation_scope_store.get(conversation_id)
    except HTTPException:
        await _close_websocket(websocket, "Dashboard authentication failed")
        return None
    except ConversationScopeStoreError:
        await _close_websocket(websocket, "Conversation authorization unavailable")
        return None

    if scope is None or not user.has_brand_access(scope.brand_id):
        # Return a generic policy error to avoid confirming a conversation's
        # existence or tenant to an unauthorized operator.
        await _close_websocket(websocket, "Conversation is outside your scope")
        return None
    return scope


async def _conversation_agent_id(conversation_id: str) -> str | None:
    """Resolve the immutable conversation agent without trusting WebSocket input."""
    agent_id = await ws_manager.get_agent_id(conversation_id)
    if agent_id:
        return agent_id
    try:
        scope = await conversation_scope_store.get(conversation_id)
    except ConversationScopeStoreError:
        return None
    return scope.agent_id if scope else None


async def _require_widget_session(
    request: MessageRequest,
    token: Optional[str],
) -> WidgetSession:
    """Validate the widget session token and bind the request to its identity.

    Raises 401 if the token is missing or invalid. The token is the only source
    of truth for conversation_id / user_id, so a caller cannot address another
    visitor's conversation by guessing or replaying an id.
    """
    session = decode_widget_session(token, expected_agent_id=request.agent_id)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail="A valid widget session token is required. Start a session at POST /messages/session.",
        )
    _bind_request_to_session(request, session)
    return session


@router.post("/session", response_model=SessionResponse)
async def start_session(request: SessionRequest):
    """Start or resume a widget chat session.

    Returns a signed token bound to a server-generated conversation_id and
    user_id. Presenting a still-valid token resumes the same conversation
    (preserving short-term and episodic memory); otherwise a fresh identity is
    minted. The agent must exist and be active.
    """
    system_db = connection_manager.get_system_db()
    agent = await system_db.agents.find_one(
        {"id": request.agent_id, "status": "active"},
        {"id": 1, "brand_id": 1, "brand_slug": 1, "configuration": 1},
    )
    channels = (((agent or {}).get("configuration") or {}).get("channels") or {})
    widget = channels.get("widget") or {}
    if not agent or widget.get("enabled", True) is False:
        raise HTTPException(status_code=404, detail="Agent not found, not active, or widget disabled")

    existing = decode_widget_session(request.session_token, expected_agent_id=request.agent_id)
    if existing is not None:
        token = encode_widget_session(existing)
        session = existing
    else:
        token, session = issue_widget_session(request.agent_id)

    brand_id = (agent or {}).get("brand_id")
    brand_slug = (agent or {}).get("brand_slug")
    if not isinstance(brand_id, str) or not brand_id or not isinstance(brand_slug, str) or not brand_slug:
        raise HTTPException(status_code=503, detail="Agent does not have a complete tenant scope")
    try:
        await conversation_scope_store.bind(
            conversation_id=session.conversation_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            brand_id=brand_id,
            brand_slug=brand_slug,
        )
    except ConversationScopeStoreError:
        # Do not issue a usable public session that an operator WebSocket cannot
        # authorize by tenant. The caller can retry safely with the same token.
        raise HTTPException(status_code=503, detail="Widget sessions are temporarily unavailable")

    return SessionResponse(
        conversation_id=session.conversation_id,
        user_id=session.user_id,
        session_token=token,
    )


def _public_history_metadata(metadata: Any) -> dict[str, Any]:
    """Expose only widget-safe message metadata; never return raw runtime state."""
    if not isinstance(metadata, dict):
        return {}
    allowed = {
        "products", "dealers", "commerce", "cart", "active_product_focus",
        "product_reference_map", "original_query", "search_query", "resolved_reference",
    }
    result = {key: metadata[key] for key in allowed if key in metadata}
    if "response_metadata" in metadata and isinstance(metadata["response_metadata"], dict):
        result.update(_public_history_metadata(metadata["response_metadata"]))
    return result


@router.get("/history", response_model=HistoryResponse)
async def get_widget_history(
    limit: int = Query(50, ge=1, le=100),
    x_widget_session: Optional[str] = Header(None),
):
    """Return signed-session-bound conversation history for widget hydration."""
    session = decode_widget_session(x_widget_session)
    if session is None:
        raise HTTPException(status_code=401, detail="A valid widget session token is required")

    try:
        brand_db = await connection_manager.get_brand_db_by_agent_id(session.agent_id)
        memory = ShortTermMemory(brand_db)
        messages = await memory.get_recent_messages(session.conversation_id, limit=limit)
        return HistoryResponse(
            conversation_id=session.conversation_id,
            messages=[
                {
                    "message_id": message.id,
                    "conversation_id": message.conversation_id,
                    "role": message.role.value,
                    "content": message.content,
                    "timestamp": message.timestamp.isoformat(),
                    "metadata": _public_history_metadata(message.metadata),
                }
                for message in messages
            ],
            has_more=len(messages) >= limit,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("widget_history_failed", agent_id=session.agent_id, conversation_id=session.conversation_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Unable to load conversation history")


@router.post("/", response_model=MessageResponse)
async def send_message(
    request: MessageRequest,
    message_service: MessageService = Depends(get_message_service),
    x_widget_session: Optional[str] = Header(None),
):
    """Send a message and get a response."""
    try:
        await _require_widget_session(request, x_widget_session)
        await _enforce_message_rate_limit(request, "widget_chat", "POST:/messages")
        response = await message_service.process_message(request)
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error processing message", error=str(e))
        raise HTTPException(status_code=500, detail="Error processing message")


@router.post("/stream")
async def stream_message(
    request: MessageRequest,
    message_service: MessageService = Depends(get_message_service),
    x_widget_session: Optional[str] = Header(None),
):
    """Send a message and get a streaming response."""
    await _require_widget_session(request, x_widget_session)
    await _enforce_message_rate_limit(request, "widget_stream", "POST:/messages/stream")

    async def generate_stream():
        try:
            async for chunk in message_service.stream_message(request):
                # Manual SSE formatting: "data: <json>\n\n"
                data = f"data: {chunk.model_dump_json()}\n\n"
                yield data
                # Small delay to ensure proper streaming and prevent buffering
                await asyncio.sleep(0.01)
        except Exception as e:
            logger.error("Error streaming message", error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    message_service: MessageService = Depends(get_message_service)
):
    """WebSocket endpoint for real-time messaging."""
    if not await _enforce_websocket_rate_limit(websocket, "WS_CONNECT:/messages/ws", "widget_ws_connect"):
        return
    await websocket.accept()
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            try:
                request_data = json.loads(data)
                if not await _enforce_websocket_rate_limit(
                    websocket,
                    "WS_MESSAGE:/messages/ws",
                    "widget_ws_message",
                    agent_id=request_data.get("agent_id"),
                    conversation_id=request_data.get("conversation_id"),
                ):
                    return
                # Heartbeat ping — respond immediately and wait for next message
                if request_data.get("type") == "ping":
                    if not await _safe_send_text(websocket, json.dumps({"type": "pong"})):
                        return
                    continue
                session_token = request_data.pop("session_token", None)
                request = MessageRequest(**request_data)
            except (json.JSONDecodeError, ValueError) as e:
                if not await _safe_send_text(websocket, json.dumps({
                    "error": "Invalid message format",
                    "detail": str(e)
                })):
                    return
                continue

            # Bind to the signed session; ignore any client-supplied ids.
            session = decode_widget_session(session_token, expected_agent_id=request.agent_id)
            if session is None:
                if not await _safe_send_text(websocket, json.dumps({
                    "type": "error",
                    "content": "A valid widget session token is required.",
                })):
                    return
                continue
            _bind_request_to_session(request, session)
            
            # Process message and stream response
            try:
                async for chunk in message_service.stream_message(request):
                    if not await _safe_send_text(websocket, chunk.model_dump_json()):
                        return
            except Exception as e:
                logger.error("Error processing WebSocket message", error=str(e))
                if not await _safe_send_text(websocket, json.dumps({
                    "type": "error",
                    "content": f"Error: {str(e)}",
                    "conversation_id": request.conversation_id or "",
                })):
                    return
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error", error=str(e))
        try:
            await websocket.close(code=1011, reason="Internal error")
        except RuntimeError:
            logger.debug("websocket_close_skipped_after_error")


@router.websocket("/ws/admin/{conversation_id}")
async def admin_websocket_endpoint(
    websocket: WebSocket,
    conversation_id: str,
    message_service: MessageService = Depends(get_message_service),
):
    """Tenant-scoped operator WebSocket for human takeover.

    Authentication is a dashboard access JWT supplied in the ``bearer``
    WebSocket subprotocol, followed by a lookup of the immutable server-side
    conversation scope. A global admin key or a caller-supplied agent ID can
    never grant access to another tenant's conversation.
    """
    scope = await _require_admin_takeover_scope(websocket, conversation_id)
    if scope is None:
        return
    if not await _enforce_websocket_rate_limit(
        websocket,
        "WS_CONNECT:/messages/ws/admin",
        "admin_api",
        agent_id=scope.agent_id,
        brand_slug=scope.brand_slug,
        conversation_id=conversation_id,
    ):
        return
    settings = get_settings()

    await ws_manager.connect_admin(
        websocket,
        conversation_id,
        subprotocol="bearer" if _websocket_offers_protocol(websocket, "bearer") else None,
    )
    try:
        while True:
            data = await websocket.receive_text()
            if not await _enforce_websocket_rate_limit(
                websocket,
                "WS_MESSAGE:/messages/ws/admin",
                "admin_api",
                agent_id=scope.agent_id,
                brand_slug=scope.brand_slug,
                conversation_id=conversation_id,
            ):
                return
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "take_control":
                if not settings.ENABLE_HUMAN_TAKEOVER:
                    logger.warning(
                        "admin_take_control_rejected_human_takeover_disabled",
                        conversation_id=conversation_id,
                    )
                    await ws_manager.send_to_admin(conversation_id, {
                        "type": "system_notice",
                        "content": "Human takeover is disabled for this environment",
                    })
                    await ws_manager.send_to_admin(conversation_id, {
                        "type": "control_status",
                        "is_human_in_control": False,
                    })
                    continue

                await ws_manager.set_human_control(conversation_id, True)
                await ws_manager.send_to_admin(conversation_id, {
                    "type": "control_status",
                    "is_human_in_control": True,
                })
                await ws_manager.send_to_admin(conversation_id, {
                    "type": "system_notice",
                    "content": "You took control of this conversation",
                })
                await ws_manager.send_to_widget(conversation_id, {
                    "type": "control_status",
                    "is_human_in_control": True,
                })
                await ws_manager.send_to_widget(conversation_id, {
                    "type": "system_notice",
                    "content": "Conversation switched to Human mode",
                })

            elif msg_type == "release_control":
                # Collect buffered takeover messages before clearing state
                takeover_messages = await ws_manager.pop_takeover_buffer(conversation_id)

                # Inject history BEFORE notifying widget that AI is back in control.
                # This ensures the AI has full context before the user can send the next message.
                agent_id = await _conversation_agent_id(conversation_id)
                if agent_id and takeover_messages:
                    try:
                        await message_service.inject_history(conversation_id, agent_id, takeover_messages)
                    except Exception as e:
                        logger.error("inject_history_failed", error=str(e), conversation_id=conversation_id)

                await ws_manager.set_human_control(conversation_id, False)

                await ws_manager.send_to_admin(conversation_id, {
                    "type": "control_status",
                    "is_human_in_control": False,
                })
                await ws_manager.send_to_admin(conversation_id, {
                    "type": "system_notice",
                    "content": "Control returned to AI",
                })
                await ws_manager.send_to_widget(conversation_id, {
                    "type": "control_status",
                    "is_human_in_control": False,
                })
                await ws_manager.send_to_widget(conversation_id, {
                    "type": "system_notice",
                    "content": "Conversation switched to AI mode",
                })

            elif msg_type == "admin_message":
                content = msg.get("content", "")
                if not settings.ENABLE_HUMAN_TAKEOVER or not await ws_manager.is_human_in_control(conversation_id):
                    logger.warning(
                        "admin_message_rejected_not_in_human_control",
                        conversation_id=conversation_id,
                        human_takeover_enabled=settings.ENABLE_HUMAN_TAKEOVER,
                    )
                    await ws_manager.send_to_admin(conversation_id, {
                        "type": "system_notice",
                        "content": "Take control before sending messages to the visitor",
                    })
                    continue

                # Deliver to widget
                await ws_manager.send_to_widget(conversation_id, {
                    "type": "admin_message",
                    "role": "assistant",
                    "content": content,
                })
                # Buffer for memory injection on release
                await ws_manager.buffer_takeover_message(conversation_id, "assistant", content)
                # Persist to Strapi (role 'agent' matches Strapi convention)
                agent_id = await _conversation_agent_id(conversation_id)
                brand_slug = await _get_agent_brand_slug(agent_id)
                message_service.strapi.save_message(
                    conversation_id,
                    content,
                    "agent",
                    brand_slug=brand_slug,
                    agent_id=agent_id,
                )

    except WebSocketDisconnect:
        logger.info("Admin WebSocket disconnected", conversation_id=conversation_id)
    except Exception as e:
        logger.error("Admin WebSocket error", error=str(e), conversation_id=conversation_id)
    finally:
        await ws_manager.disconnect_admin(websocket, conversation_id)


@router.websocket("/ws/widget/{conversation_id}")
async def widget_control_channel(
    websocket: WebSocket,
    conversation_id: str,
    message_service: MessageService = Depends(get_message_service),
):
    """Signed widget control channel for human takeover.

    Receives:
    - register: confirms the already server-bound conversation scope
    - ping: heartbeat
    - user_message: forwarded to admin during human takeover, buffered, and persisted
    """
    settings = get_settings()
    session_and_scope = await _require_widget_control_scope(websocket, conversation_id)
    if session_and_scope is None:
        return
    _, scope = session_and_scope
    agent_id = scope.agent_id
    if not await _enforce_websocket_rate_limit(
        websocket,
        "WS_CONNECT:/messages/ws/widget",
        "widget_ws_connect",
        agent_id=agent_id,
        brand_slug=scope.brand_slug,
        conversation_id=conversation_id,
    ):
        return
    await ws_manager.register_agent_id(conversation_id, agent_id)
    await ws_manager.connect_widget(
        websocket,
        conversation_id,
        subprotocol="widget-session" if _websocket_offers_protocol(websocket, "widget-session") else None,
    )
    try:
        while True:
            data = await websocket.receive_text()
            if not await _enforce_websocket_rate_limit(
                websocket,
                "WS_MESSAGE:/messages/ws/widget",
                "widget_ws_message",
                agent_id=agent_id,
                brand_slug=scope.brand_slug,
                conversation_id=conversation_id,
            ):
                return
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                if not await _safe_send_text(websocket, json.dumps({"type": "pong"})):
                    return

            elif msg_type == "register":
                # The agent was bound by the signed session and immutable
                # conversation record before accepting this socket.
                await ws_manager.register_agent_id(conversation_id, agent_id)

            elif msg_type == "user_message":
                if await ws_manager.is_human_in_control(conversation_id):
                    content = msg.get("content", "")
                    # Deliver to admin dashboard in real-time
                    await ws_manager.send_to_admin(conversation_id, {
                        "type": "user_message",
                        "role": "user",
                        "content": content,
                    })
                    # Buffer for memory injection on release
                    await ws_manager.buffer_takeover_message(conversation_id, "user", content)
                    # Persist to Strapi
                    brand_slug = scope.brand_slug
                    message_service.strapi.save_message(
                        conversation_id,
                        content,
                        "user",
                        brand_slug=brand_slug,
                        agent_id=agent_id,
                    )

    except WebSocketDisconnect:
        logger.info("Widget control channel disconnected", conversation_id=conversation_id)
    except Exception as e:
        logger.error("Widget control channel error", error=str(e), conversation_id=conversation_id)
    finally:
        await ws_manager.disconnect_widget(websocket, conversation_id)
