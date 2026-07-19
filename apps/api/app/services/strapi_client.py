"""
StrapiClient — fire-and-forget sync of conversation sessions and messages
to the Strapi dashboard at POST /session-save and POST /chat-save.
"""

import asyncio
import structlog
from typing import Any
from ..monitoring import STRAPI_SYNC_COUNT

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

logger = structlog.get_logger(__name__)

MAX_SYNC_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class StrapiClient:
    """Async client for pushing conversation data to the Strapi dashboard."""

    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        # Conversation mirrors are an authenticated best-effort integration.
        # Never enqueue an unauthenticated request with an empty Bearer token.
        self._enabled = bool(base_url and api_token and _HTTPX_AVAILABLE)
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
        assistant_metadata: dict[str, Any] | None = None,
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
                assistant_metadata=assistant_metadata,
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
        metadata: dict[str, Any] | None = None,
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
                metadata=metadata,
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
        metadata: dict[str, Any] | None = None,
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
            metadata=metadata,
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
        assistant_metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._ensure_session(conversation_id, brand_slug=brand_slug, agent_id=agent_id)
        await self._save_message(
            conversation_id,
            user_message,
            "user",
            brand_slug=brand_slug,
            agent_id=agent_id,
        )
        await self._save_message(
            conversation_id,
            assistant_message,
            "agent",
            brand_slug=brand_slug,
            agent_id=agent_id,
            metadata=assistant_metadata,
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
            if not await self._allow_sync("session", conversation_id, brand_slug, agent_id):
                return
            await self._post_with_retry(
                "/api/session-save",
                {
                    "conversation_id": conversation_id,
                    "brand_slug": brand_slug,
                    "agent_id": agent_id,
                    "last_message_at": last_message_at,
                },
                operation="session",
                conversation_id=conversation_id,
                brand_slug=brand_slug,
                agent_id=agent_id,
            )
            STRAPI_SYNC_COUNT.labels(operation="session", status="success").inc()
            await self._record_sync_event("session", "success", conversation_id, brand_slug, agent_id)
            logger.debug("strapi_session_saved", conversation_id=conversation_id, brand_slug=brand_slug, agent_id=agent_id)
        except Exception as e:
            STRAPI_SYNC_COUNT.labels(operation="session", status="error").inc()
            await self._record_sync_event("session", "error", conversation_id, brand_slug, agent_id, error=str(e))
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
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            if not await self._allow_sync("message", conversation_id, brand_slug, agent_id):
                return
            payload = {
                "conversation_id": conversation_id,
                "message_content": content,
                "role": role,
                "brand_slug": brand_slug,
                "agent_id": agent_id,
                "timestamp": timestamp,
            }
            if metadata is not None:
                payload["metadata"] = metadata
            await self._post_with_retry(
                "/api/chat-save",
                payload,
                operation="message",
                conversation_id=conversation_id,
                brand_slug=brand_slug,
                agent_id=agent_id,
                role=role,
            )
            STRAPI_SYNC_COUNT.labels(operation="message", status="success").inc()
            await self._record_sync_event("message", "success", conversation_id, brand_slug, agent_id, role=role)
            logger.debug("strapi_message_saved", conversation_id=conversation_id, role=role, brand_slug=brand_slug, agent_id=agent_id)
        except Exception as e:
            STRAPI_SYNC_COUNT.labels(operation="message", status="error").inc()
            await self._record_sync_event("message", "error", conversation_id, brand_slug, agent_id, role=role, error=str(e))
            logger.warning("strapi_message_save_failed", conversation_id=conversation_id, role=role, error=str(e))

    async def _post_with_retry(
        self,
        path: str,
        payload: dict,
        *,
        operation: str,
        conversation_id: str,
        brand_slug: str | None,
        agent_id: str | None,
        role: str | None = None,
    ) -> None:
        last_error: Exception | None = None
        for attempt in range(1, MAX_SYNC_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        f"{self.base_url}{path}",
                        json=payload,
                        headers=self._headers,
                    )
                    resp.raise_for_status()
                    return
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if status_code not in RETRYABLE_STATUS_CODES or attempt >= MAX_SYNC_ATTEMPTS:
                    raise
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt >= MAX_SYNC_ATTEMPTS:
                    raise

            logger.warning(
                "strapi_sync_retrying",
                operation=operation,
                conversation_id=conversation_id,
                brand_slug=brand_slug,
                agent_id=agent_id,
                role=role,
                attempt=attempt,
                error=str(last_error),
            )
            await asyncio.sleep(0.25 * attempt)

    async def _allow_sync(
        self,
        operation: str,
        conversation_id: str,
        brand_slug: str | None,
        agent_id: str | None,
    ) -> bool:
        from ..security.rate_limiter import check_named_rate_limit

        is_allowed, info = await check_named_rate_limit(
            "strapi_sync",
            agent_id=agent_id,
            brand_slug=brand_slug,
            conversation_id=conversation_id,
            endpoint=f"strapi:{operation}",
        )
        if not is_allowed:
            STRAPI_SYNC_COUNT.labels(operation=operation, status="rate_limited").inc()
            await self._record_sync_event(
                operation,
                "rate_limited",
                conversation_id,
                brand_slug,
                agent_id,
                retry_after=info.get("retry_after"),
            )
            logger.warning(
                "strapi_sync_rate_limited",
                operation=operation,
                conversation_id=conversation_id,
                brand_slug=brand_slug,
                agent_id=agent_id,
                retry_after=info.get("retry_after"),
            )
            return False
        return True

    async def _record_sync_event(
        self,
        operation: str,
        status: str,
        conversation_id: str,
        brand_slug: str | None,
        agent_id: str | None,
        **extra,
    ) -> None:
        from .observability_service import ObservabilityService

        await ObservabilityService().track_event(
            event_type="strapi_sync",
            brand_slug=brand_slug,
            agent_id=agent_id,
            conversation_id=conversation_id,
            payload={
                "operation": operation,
                "status": status,
                **extra,
            },
        )
