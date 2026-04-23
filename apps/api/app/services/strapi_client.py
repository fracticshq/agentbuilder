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

    def sync_conversation(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        *,
        brand_slug: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        """Schedule a non-blocking Strapi sync for one full conversation turn."""
        if not self._enabled:
            return
        asyncio.create_task(
            self._sync(
                conversation_id,
                user_message,
                assistant_message,
                brand_slug=brand_slug,
                agent_id=agent_id,
            ),
            name=f"strapi_sync_{conversation_id}",
        )

    def sync_session(
        self,
        conversation_id: str,
        *,
        brand_slug: str | None = None,
        agent_id: str | None = None,
        last_message_at: str | None = None,
    ) -> None:
        """Ensure the session row exists in Strapi (idempotent)."""
        if not self._enabled:
            return
        asyncio.create_task(
            self._ensure_session(
                conversation_id,
                brand_slug=brand_slug,
                agent_id=agent_id,
                last_message_at=last_message_at,
            ),
            name=f"strapi_session_{conversation_id}",
        )

    def save_message(
        self,
        conversation_id: str,
        content: str,
        role: str,
        *,
        brand_slug: str | None = None,
        agent_id: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        """Fire-and-forget save of a single message."""
        if not self._enabled:
            return
        asyncio.create_task(
            self._save_message_with_session(
                conversation_id,
                content,
                role,
                brand_slug=brand_slug,
                agent_id=agent_id,
                timestamp=timestamp,
            ),
            name=f"strapi_msg_{conversation_id}",
        )

    async def _save_message_with_session(
        self,
        conversation_id: str,
        content: str,
        role: str,
        *,
        brand_slug: str | None = None,
        agent_id: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        await self._ensure_session(
            conversation_id,
            brand_slug=brand_slug,
            agent_id=agent_id,
            last_message_at=timestamp,
        )
        await self._save_message(
            conversation_id,
            content,
            role,
            brand_slug=brand_slug,
            agent_id=agent_id,
            timestamp=timestamp,
        )

    # ── internals ──────────────────────────────────────────────────────────────

    async def _sync(
        self,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        *,
        brand_slug: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        await self._ensure_session(conversation_id, brand_slug=brand_slug, agent_id=agent_id)
        await asyncio.gather(
            self._save_message(conversation_id, user_message, "user", brand_slug=brand_slug, agent_id=agent_id),
            self._save_message(conversation_id, assistant_message, "agent", brand_slug=brand_slug, agent_id=agent_id),
            return_exceptions=True,
        )

    async def _ensure_session(
        self,
        conversation_id: str,
        *,
        brand_slug: str | None = None,
        agent_id: str | None = None,
        last_message_at: str | None = None,
    ) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/session-save",
                    json={
                        "conversation_id": conversation_id,
                        "brand_slug": brand_slug,
                        "agent_id": agent_id,
                        "last_message_at": last_message_at,
                    },
                    headers=self._headers,
                )
                resp.raise_for_status()
                logger.debug("strapi_session_saved", conversation_id=conversation_id, brand_slug=brand_slug, agent_id=agent_id)
        except Exception as e:
            logger.warning("strapi_session_save_failed", conversation_id=conversation_id, error=str(e))

    async def _save_message(
        self,
        conversation_id: str,
        content: str,
        role: str,
        *,
        brand_slug: str | None = None,
        agent_id: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat-save",
                    json={
                        "conversation_id": conversation_id,
                        "message_content": content,
                        "role": role,
                        "brand_slug": brand_slug,
                        "agent_id": agent_id,
                        "timestamp": timestamp,
                    },
                    headers=self._headers,
                )
                resp.raise_for_status()
                logger.debug("strapi_message_saved", conversation_id=conversation_id, role=role, brand_slug=brand_slug, agent_id=agent_id)
        except Exception as e:
            logger.warning("strapi_message_save_failed", conversation_id=conversation_id, role=role, error=str(e))
