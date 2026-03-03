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
from ....websocket_manager import ws_manager

@router.websocket("/ws/chat/{conversation_id}")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    conversation_id: str,
    message_service: MessageService = Depends(get_message_service)
):
    """WebSocket endpoint for widget chat clients."""
    await ws_manager.connect_widget(websocket, conversation_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                request_data = json.loads(data)
                if request_data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    continue
                # If we get a message from the widget, we can process it, but usually widget uses /stream HTTP
                # If they send via WS, process it normally here.
                request = MessageRequest(**request_data)
                request.conversation_id = conversation_id
            except (json.JSONDecodeError, ValueError) as e:
                await websocket.send_text(json.dumps({
                    "error": "Invalid message format",
                    "detail": str(e)
                }))
                continue
            
            # Process message and stream response back to widget
            # (Note: App.tsx uses HTTP /stream, this is here for symmetry or future use)
            try:
                async for chunk in message_service.stream_message(request):
                    await websocket.send_text(chunk.model_dump_json())
            except Exception as e:
                logger.error("Error processing WebSocket message", error=str(e))
                await websocket.send_text(json.dumps({
                    "error": "Processing error",
                    "detail": str(e)
                }))
                
    except WebSocketDisconnect:
        ws_manager.disconnect_widget(websocket, conversation_id)
    except Exception as e:
        logger.error("WebSocket chat error", error=str(e))
        ws_manager.disconnect_widget(websocket, conversation_id)
        await websocket.close(code=1011, reason="Internal error")

@router.websocket("/ws/admin/{conversation_id}")
async def websocket_admin_endpoint(
    websocket: WebSocket,
    conversation_id: str,
    message_service: MessageService = Depends(get_message_service)
):
    """WebSocket endpoint for admin UI."""
    await ws_manager.connect_admin(websocket, conversation_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
                msg_type = message_data.get("type")
                
                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    continue
                
                if msg_type == "take_control":
                    ws_manager.set_human_control(conversation_id, True)
                    # Notify widget to pause AI indicator if needed
                    await ws_manager.send_to_widget(conversation_id, {
                        "type": "control_status",
                        "is_human_in_control": True
                    })
                    await ws_manager.send_to_admin(conversation_id, {
                        "type": "control_status",
                        "is_human_in_control": True
                    })
                    continue
                
                if msg_type == "release_control":
                    ws_manager.set_human_control(conversation_id, False)
                    await ws_manager.send_to_widget(conversation_id, {
                        "type": "control_status",
                        "is_human_in_control": False
                    })
                    await ws_manager.send_to_admin(conversation_id, {
                        "type": "control_status",
                        "is_human_in_control": False
                    })
                    continue
                
                if msg_type == "admin_message":
                    content = message_data.get("content")
                    if content:
                        # Log it into short-term memory as assistant so it appears in history properly
                        if message_service.short_term:
                            from memory.types import MessageRole
                            await message_service.short_term.add_message(
                                conversation_id=conversation_id,
                                role=MessageRole.ASSISTANT,
                                content=content,
                                metadata={"is_human_agent": True}
                            )
                        # Log to Strapi
                        asyncio.create_task(message_service.strapi_service.log_message(conversation_id, content, "agent"))
                        
                        # Send to widgets
                        await ws_manager.send_to_widget(conversation_id, {
                            "type": "admin_message",
                            "content": content
                        })
                    continue
                    
            except json.JSONDecodeError as e:
                await websocket.send_text(json.dumps({
                    "error": "Invalid JSON",
                    "detail": str(e)
                }))
                
    except WebSocketDisconnect:
        ws_manager.disconnect_admin(websocket, conversation_id)
    except Exception as e:
        logger.error("WebSocket admin error", error=str(e))
        ws_manager.disconnect_admin(websocket, conversation_id)
        await websocket.close(code=1011, reason="Internal error")