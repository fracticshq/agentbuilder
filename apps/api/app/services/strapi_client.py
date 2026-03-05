"""
StrapiClient — fire-and-forget sync of conversation sessions and messages
to the Strapi dashboard at POST /session-save and POST /chat-save.
"""

import asyncio
import structlog

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

logger = structlog.get_logger(__name__)


class StrapiClient:
    """Async client for pushing conversation data to the Strapi dashboard."""

    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        self._enabled = bool(base_url and _HTTPX_AVAILABLE)
        if not _HTTPX_AVAILABLE:
            logger.warning("strapi_client_disabled", reason="httpx not installed")

    # ── public API ─────────────────────────────────────────────────────────────

    def sync_conversation(self, conversation_id: str, user_message: str, assistant_message: str) -> None:
        """Schedule a non-blocking Strapi sync for one full conversation turn.

        Ensures the session exists, then saves both the user message and the
        assistant response. All network calls are fire-and-forget so they never
        block the streaming response.
        """
        if not self._enabled:
            return
        asyncio.create_task(
            self._sync(conversation_id, user_message, assistant_message),
            name=f"strapi_sync_{conversation_id}",
        )

    def sync_session(self, conversation_id: str) -> None:
        """Ensure the session row exists in Strapi (idempotent)."""
        if not self._enabled:
            return
        asyncio.create_task(
            self._ensure_session(conversation_id),
            name=f"strapi_session_{conversation_id}",
        )

    # ── internals ──────────────────────────────────────────────────────────────

    async def _sync(self, conversation_id: str, user_message: str, assistant_message: str) -> None:
        await self._ensure_session(conversation_id)
        await asyncio.gather(
            self._save_message(conversation_id, user_message, "user"),
            self._save_message(conversation_id, assistant_message, "agent"),
            return_exceptions=True,
        )

    async def _ensure_session(self, conversation_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/session-save",
                    json={"conversation_id": conversation_id},
                    headers=self._headers,
                )
                resp.raise_for_status()
                logger.debug("strapi_session_saved", conversation_id=conversation_id)
        except Exception as e:
            logger.warning("strapi_session_save_failed", conversation_id=conversation_id, error=str(e))

    async def _save_message(self, conversation_id: str, content: str, role: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat-save",
                    json={
                        "conversation_id": conversation_id,
                        "message_content": content,
                        "role": role,
                    },
                    headers=self._headers,
                )
                resp.raise_for_status()
                logger.debug("strapi_message_saved", conversation_id=conversation_id, role=role)
        except Exception as e:
            logger.warning("strapi_message_save_failed", conversation_id=conversation_id, role=role, error=str(e))
