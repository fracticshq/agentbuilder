import json
import structlog
from typing import Dict, Set
from fastapi import WebSocket

logger = structlog.get_logger(__name__)

class ConnectionManager:
    def __init__(self):
        # conversation_id -> set of active widget connections
        self.widget_connections: Dict[str, Set[WebSocket]] = {}
        # conversation_id -> set of active admin connections
        self.admin_connections: Dict[str, Set[WebSocket]] = {}
        # conversation_id -> boolean flag indicating human is in control
        self.human_control_flags: Dict[str, bool] = {}

    async def connect_widget(self, websocket: WebSocket, conversation_id: str):
        await websocket.accept()
        if conversation_id not in self.widget_connections:
            self.widget_connections[conversation_id] = set()
        self.widget_connections[conversation_id].add(websocket)
        logger.info("widget_websocket_connected", conversation_id=conversation_id)

    async def connect_admin(self, websocket: WebSocket, conversation_id: str):
        await websocket.accept()
        if conversation_id not in self.admin_connections:
            self.admin_connections[conversation_id] = set()
        self.admin_connections[conversation_id].add(websocket)
        logger.info("admin_websocket_connected", conversation_id=conversation_id)
        
        # Notify admins of the current control state on connection
        control_state = self.is_human_in_control(conversation_id)
        await self.send_to_admin(conversation_id, {
            "type": "control_status",
            "is_human_in_control": control_state
        })

    def disconnect_widget(self, websocket: WebSocket, conversation_id: str):
        if conversation_id in self.widget_connections:
            self.widget_connections[conversation_id].discard(websocket)
            if not self.widget_connections[conversation_id]:
                del self.widget_connections[conversation_id]
        logger.info("widget_websocket_disconnected", conversation_id=conversation_id)

    def disconnect_admin(self, websocket: WebSocket, conversation_id: str):
        if conversation_id in self.admin_connections:
            self.admin_connections[conversation_id].discard(websocket)
            if not self.admin_connections[conversation_id]:
                del self.admin_connections[conversation_id]
        logger.info("admin_websocket_disconnected", conversation_id=conversation_id)

    def set_human_control(self, conversation_id: str, is_active: bool):
        """Set whether a human agent is currently in control of this conversation."""
        self.human_control_flags[conversation_id] = is_active
        logger.info("human_control_updated", conversation_id=conversation_id, is_active=is_active)

    def is_human_in_control(self, conversation_id: str) -> bool:
        """Check if a human agent is in control."""
        return self.human_control_flags.get(conversation_id, False)

    async def send_to_widget(self, conversation_id: str, message: dict):
        """Send a JSON message to all widget connections for a conversation."""
        if conversation_id in self.widget_connections:
            websockets = list(self.widget_connections[conversation_id])
            for websocket in websockets:
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.error("error_sending_to_widget", error=str(e), conversation_id=conversation_id)
                    self.disconnect_widget(websocket, conversation_id)

    async def send_to_admin(self, conversation_id: str, message: dict):
        """Send a JSON message to all admin connections for a conversation."""
        if conversation_id in self.admin_connections:
            websockets = list(self.admin_connections[conversation_id])
            for websocket in websockets:
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.error("error_sending_to_admin", error=str(e), conversation_id=conversation_id)
                    self.disconnect_admin(websocket, conversation_id)

# Global websocket connection manager instance
ws_manager = ConnectionManager()
