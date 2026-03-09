"""
Messages API Endpoints
"""

from typing import AsyncGenerator
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import json
import asyncio
import structlog

from commons.types.requests import MessageRequest
from commons.types.responses import MessageResponse, StreamingMessageResponse
from ....dependencies import get_message_service
from ....services.message_service import MessageService
from ....websocket_manager import ws_manager

logger = structlog.get_logger()
router = APIRouter()


@router.post("/", response_model=MessageResponse)
async def send_message(
    request: MessageRequest,
    message_service: MessageService = Depends(get_message_service)
):
    """Send a message and get a response."""
    try:
        response = await message_service.process_message(request)
        return response
    except Exception as e:
        logger.error("Error processing message", error=str(e))
        raise HTTPException(status_code=500, detail="Error processing message")


@router.post("/stream")
async def stream_message(
    request: MessageRequest,
    message_service: MessageService = Depends(get_message_service)
):
    """Send a message and get a streaming response."""
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
    await websocket.accept()
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            try:
                request_data = json.loads(data)
                # Heartbeat ping — respond immediately and wait for next message
                if request_data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    continue
                request = MessageRequest(**request_data)
            except (json.JSONDecodeError, ValueError) as e:
                await websocket.send_text(json.dumps({
                    "error": "Invalid message format",
                    "detail": str(e)
                }))
                continue
            
            # Mirror user message to any watching admin connections
            conv_id = request.conversation_id or ""
            if conv_id:
                await ws_manager.send_to_admin(conv_id, {
                    "type": "user_message",
                    "role": "user",
                    "content": request.message,
                })

            # Process message and stream response
            try:
                accumulated = ""
                async for chunk in message_service.stream_message(request):
                    await websocket.send_text(chunk.model_dump_json())
                    if chunk.type == "content" and chunk.content:
                        accumulated += chunk.content
                # Mirror completed AI response to admin
                if conv_id and accumulated:
                    await ws_manager.send_to_admin(conv_id, {
                        "type": "assistant_message",
                        "role": "assistant",
                        "content": accumulated,
                    })
            except Exception as e:
                logger.error("Error processing WebSocket message", error=str(e))
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": f"Error: {str(e)}",
                    "conversation_id": conv_id,
                }))
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error", error=str(e))
        await websocket.close(code=1011, reason="Internal error")


@router.websocket("/ws/admin/{conversation_id}")
async def admin_websocket_endpoint(websocket: WebSocket, conversation_id: str):
    """Admin WebSocket for human takeover and live conversation monitoring."""
    await ws_manager.connect_admin(websocket, conversation_id)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "take_control":
                ws_manager.set_human_control(conversation_id, True)
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
                ws_manager.set_human_control(conversation_id, False)
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
                await ws_manager.send_to_widget(conversation_id, {
                    "type": "admin_message",
                    "role": "assistant",
                    "content": content,
                })

    except WebSocketDisconnect:
        logger.info("Admin WebSocket disconnected", conversation_id=conversation_id)
    except Exception as e:
        logger.error("Admin WebSocket error", error=str(e), conversation_id=conversation_id)
    finally:
        ws_manager.disconnect_admin(websocket, conversation_id)


@router.websocket("/ws/widget/{conversation_id}")
async def widget_control_channel(websocket: WebSocket, conversation_id: str):
    """Widget control channel — registers widget with ws_manager so admin can push to it.

    Handles two scenarios:
    - Admin pushes (control_status, admin_message) arrive via ws_manager.send_to_widget()
      and are forwarded to the widget over this connection.
    - When a human agent is in control, user messages sent here are forwarded to the
      admin instead of going to the AI.
    """
    await ws_manager.connect_widget(websocket, conversation_id)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            elif msg_type == "user_message":
                # Only forward to admin; AI path uses the existing /ws endpoint
                if ws_manager.is_human_in_control(conversation_id):
                    content = msg.get("content", "")
                    await ws_manager.send_to_admin(conversation_id, {
                        "type": "user_message",
                        "role": "user",
                        "content": content,
                    })

    except WebSocketDisconnect:
        logger.info("Widget control channel disconnected", conversation_id=conversation_id)
    except Exception as e:
        logger.error("Widget control channel error", error=str(e), conversation_id=conversation_id)
    finally:
        ws_manager.disconnect_widget(websocket, conversation_id)
