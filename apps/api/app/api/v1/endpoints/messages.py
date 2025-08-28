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
                yield f"data: {json.dumps(chunk.dict())}\n\n"
        except Exception as e:
            logger.error("Error streaming message", error=str(e))
            yield f"data: {json.dumps({'error': 'Stream error'})}\n\n"
    
    return EventSourceResponse(generate_stream())


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
                request = MessageRequest(**request_data)
            except (json.JSONDecodeError, ValueError) as e:
                await websocket.send_text(json.dumps({
                    "error": "Invalid message format",
                    "detail": str(e)
                }))
                continue
            
            # Process message and stream response
            try:
                async for chunk in message_service.stream_message(request):
                    await websocket.send_text(json.dumps(chunk.dict()))
            except Exception as e:
                logger.error("Error processing WebSocket message", error=str(e))
                await websocket.send_text(json.dumps({
                    "error": "Processing error",
                    "detail": str(e)
                }))
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error", error=str(e))
        await websocket.close(code=1011, reason="Internal error")
