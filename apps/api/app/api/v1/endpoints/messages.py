"""
Messages API Endpoints
"""

from typing import AsyncGenerator, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
import json
import asyncio
import structlog
from urllib.parse import urlparse

from commons.types.requests import MessageRequest
from commons.types.responses import MessageResponse, StreamingMessageResponse
from ....auth.admin_key import is_admin_key_authorized
from ....auth.widget_session import (
    WidgetSession,
    decode_widget_session,
    encode_widget_session,
    issue_widget_session,
)
from ....connections import connection_manager
from ....dependencies import get_message_service, get_settings
from ....security.rate_limiter import check_named_rate_limit
from ....services.message_service import MessageService
from ....services.observability_service import ObservabilityService
from ....websocket_manager import ws_manager

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


def _origin_matches_base_url(origin: str | None, base_url: str | None) -> bool:
    if not origin or not base_url:
        return False

    try:
        origin_parts = urlparse(origin)
        base_parts = urlparse(base_url)
    except Exception:
        return False

    if not origin_parts.hostname or not base_parts.hostname:
        return False

    origin_port = origin_parts.port or (443 if origin_parts.scheme == "https" else 80)
    base_port = base_parts.port or (443 if base_parts.scheme == "https" else 80)
    return (
        origin_parts.scheme == base_parts.scheme
        and origin_parts.hostname == base_parts.hostname
        and origin_port == base_port
    )


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
        {"id": request.agent_id, "status": "active"}, {"id": 1, "configuration": 1}
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

    return SessionResponse(
        conversation_id=session.conversation_id,
        user_id=session.user_id,
        session_token=token,
    )


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
    """Admin WebSocket for human takeover and live conversation monitoring."""
    if not await _enforce_websocket_rate_limit(
        websocket,
        "WS_CONNECT:/messages/ws/admin",
        "admin_api",
        conversation_id=conversation_id,
    ):
        return
    settings = get_settings()

    admin_key = websocket.headers.get("x-admin-key") or websocket.query_params.get("admin_key")
    trusted_strapi_origin = (
        not settings.is_production
        and _origin_matches_base_url(websocket.headers.get("origin"), settings.STRAPI_URL)
    )
    if not is_admin_key_authorized(admin_key, settings) and not trusted_strapi_origin:
        logger.warning(
            "admin_websocket_rejected_invalid_admin_key",
            conversation_id=conversation_id,
            origin=websocket.headers.get("origin"),
            has_admin_key=bool(admin_key),
        )
        await _close_websocket(websocket, "Invalid admin key")
        return

    await ws_manager.connect_admin(websocket, conversation_id)
    try:
        while True:
            data = await websocket.receive_text()
            if not await _enforce_websocket_rate_limit(
                websocket,
                "WS_MESSAGE:/messages/ws/admin",
                "admin_api",
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
                agent_id = await ws_manager.get_agent_id(conversation_id)
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
                agent_id = await ws_manager.get_agent_id(conversation_id)
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
    """Widget control channel — registers widget with ws_manager so admin can push to it.

    Receives:
    - register: widget sends agent_id so backend can restore AI context on release
    - ping: heartbeat
    - user_message: forwarded to admin during human takeover, buffered, and persisted
    """
    settings = get_settings()
    agent_id = (websocket.query_params.get("agent_id") or "").strip()
    if not await _enforce_websocket_rate_limit(
        websocket,
        "WS_CONNECT:/messages/ws/widget",
        "widget_ws_connect",
        agent_id=agent_id or None,
        conversation_id=conversation_id,
    ):
        return
    control_secret = (websocket.query_params.get("control_secret") or "").strip()
    is_authorized = await ws_manager.authorize_widget_control(
        conversation_id,
        agent_id,
        control_secret,
    )
    if not is_authorized:
        logger.warning(
            "widget_control_rejected_unauthorized",
            conversation_id=conversation_id,
            agent_id=agent_id,
            control_secret_length=len(control_secret),
        )
        await _close_websocket(websocket, "Unauthorized widget control channel")
        return

    await ws_manager.connect_widget(websocket, conversation_id)
    try:
        while True:
            data = await websocket.receive_text()
            if not await _enforce_websocket_rate_limit(
                websocket,
                "WS_MESSAGE:/messages/ws/widget",
                "widget_ws_message",
                agent_id=agent_id or None,
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
                # Widget sends its agent_id so we can inject history into the right memory
                if agent_id:
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
                    brand_slug = await _get_agent_brand_slug(agent_id or None)
                    message_service.strapi.save_message(
                        conversation_id,
                        content,
                        "user",
                        brand_slug=brand_slug,
                        agent_id=agent_id or None,
                    )

    except WebSocketDisconnect:
        logger.info("Widget control channel disconnected", conversation_id=conversation_id)
    except Exception as e:
        logger.error("Widget control channel error", error=str(e), conversation_id=conversation_id)
    finally:
        await ws_manager.disconnect_widget(websocket, conversation_id)
