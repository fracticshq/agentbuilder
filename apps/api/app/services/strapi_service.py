"""
Strapi Service for Logging Chat Context
"""

import os
import asyncio
import httpx
import structlog
from typing import Dict, Any, Optional
from ..config import Settings

logger = structlog.get_logger(__name__)


class StrapiService:
    """
    Service for sending logging requests to Strapi backend.
    Designed to run asynchronously and fire-and-forget so it doesn't block the main agent flow.
    """

    def __init__(self, settings: Optional[Settings] = None):
        if settings is None:
            settings = Settings()
        self.base_url = getattr(settings, "STRAPI_LOG_URL", "http://localhost:1337").rstrip("/")
        self.api_token = getattr(settings, "STRAPI_API_TOKEN", None)
        # Using new sessionapi endpoints
        # Custom routes are registered at the root of the /api prefix
        self.session_save_url = f"{self.base_url}/api/session-save"
        self.chat_save_url = f"{self.base_url}/api/chat-save"
        
        logger.info("strapi_service_configured", 
                    session_url=self.session_save_url, 
                    chat_url=self.chat_save_url,
                    has_token=bool(self.api_token))

    async def _post_request(self, url: str, payload: Dict[str, Any]) -> None:
        """Internal helper to make asynchronous POST requests to Strapi."""
        try:
            headers = {}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
                
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=5.0)
                if response.status_code >= 400:
                    logger.warning(
                        "strapi_log_failed",
                        url=url,
                        status_code=response.status_code,
                        text=response.text,
                    )
        except Exception as e:
            logger.error("strapi_request_error", url=url, error=str(e))

    async def log_session(self, conversation_id: str) -> None:
        """
        Log/verify session existence in Strapi.
        """
        payload = {"conversation_id": conversation_id}
        await self._post_request(self.session_save_url, payload)

    async def log_message(self, conversation_id: str, message_content: str, role: str = "user") -> None:
        """
        Log user or agent message into the Strapi message table.
        """
        payload = {
            "conversation_id": conversation_id,
            "message_content": message_content,
            "role": role,
        }
        await self._post_request(self.chat_save_url, payload)
