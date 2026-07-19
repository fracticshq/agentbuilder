"""Durable tenant binding for public widget conversations.

Widget session JWTs prove that a caller owns a conversation.  Human-takeover
also needs a server-side record of the conversation's creation-time agent and
brand so an operator WebSocket can be authorized without trusting a client
supplied agent or a process-local Redis value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from pymongo.errors import DuplicateKeyError

from ..connections import connection_manager

logger = structlog.get_logger(__name__)

CONVERSATION_SCOPES_COLLECTION = "widget_conversation_scopes"


class ConversationScopeStoreError(RuntimeError):
    """The authoritative conversation scope cannot be safely read or stored."""


class ConversationScopeMismatchError(ConversationScopeStoreError):
    """A valid token conflicts with an existing immutable conversation scope."""


class ConversationScopeAuthorizationError(ConversationScopeStoreError):
    """A signed widget session can no longer access its original tenant scope."""


@dataclass(frozen=True)
class ConversationScope:
    conversation_id: str
    user_id: str
    agent_id: str
    brand_id: str
    brand_slug: str


class ConversationScopeStore:
    """Mongo-backed immutable tenant scope with bounded session retention."""

    def __init__(self, *, retention_seconds: int = 72 * 60 * 60):
        self.retention_seconds = max(60, int(retention_seconds))
        self._indexes_checked = False

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _collection(self):
        try:
            return connection_manager.get_system_db()[CONVERSATION_SCOPES_COLLECTION]
        except (RuntimeError, AttributeError, KeyError, TypeError) as exc:
            raise ConversationScopeStoreError("Conversation scope storage is unavailable") from exc

    async def _ensure_indexes(self, collection: Any) -> None:
        if self._indexes_checked:
            return
        self._indexes_checked = True
        try:
            await collection.create_index(
                "expires_at",
                expireAfterSeconds=0,
                name="widget_conversation_scopes_expiry_idx",
            )
            await collection.create_index(
                [("brand_id", 1), ("agent_id", 1), ("expires_at", 1)],
                name="widget_conversation_scopes_tenant_idx",
            )
        except Exception as exc:
            # Index races are benign. The following read/write remains the
            # authority and reports an unavailable store if Mongo is down.
            logger.warning("conversation_scope_index_setup_failed", error_type=type(exc).__name__)

    @staticmethod
    def _from_document(document: dict[str, Any] | None) -> ConversationScope | None:
        if not isinstance(document, dict):
            return None
        values = {
            "conversation_id": document.get("conversation_id") or document.get("_id"),
            "user_id": document.get("user_id"),
            "agent_id": document.get("agent_id"),
            "brand_id": document.get("brand_id"),
            "brand_slug": document.get("brand_slug"),
        }
        if any(not isinstance(value, str) or not value for value in values.values()):
            return None
        return ConversationScope(**values)

    async def bind(
        self,
        *,
        conversation_id: str,
        user_id: str,
        agent_id: str,
        brand_id: str,
        brand_slug: str,
    ) -> ConversationScope:
        """Persist an immutable creation-time scope and refresh only its TTL."""
        values = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "brand_id": brand_id,
            "brand_slug": brand_slug,
        }
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise ConversationScopeStoreError("Conversation scope is incomplete")

        collection = self._collection()
        await self._ensure_indexes(collection)
        now = self._utc_now()
        expires_at = now + timedelta(seconds=self.retention_seconds)
        document = {
            "_id": conversation_id,
            **values,
            "created_at": now,
            "expires_at": expires_at,
            "privacy": {
                "status": "active",
                "long_term_memory_consent": "unknown",
                "updated_at": now,
            },
        }
        try:
            await collection.insert_one(document)
            return ConversationScope(**values)
        except DuplicateKeyError:
            # Another request may have resumed the same valid signed session.
            # Never overwrite its tenant scope; compare every identity field.
            existing = await self.get(conversation_id)
            if existing is None:
                raise ConversationScopeStoreError("Conversation scope storage is unavailable")
            if existing != ConversationScope(**values):
                raise ConversationScopeMismatchError("Conversation scope does not match the signed session")
            try:
                await collection.update_one({"_id": conversation_id}, {"$set": {"expires_at": expires_at}})
            except Exception as exc:
                raise ConversationScopeStoreError("Conversation scope storage is unavailable") from exc
            return existing
        except ConversationScopeStoreError:
            raise
        except Exception as exc:
            logger.warning("conversation_scope_bind_failed", error_type=type(exc).__name__)
            raise ConversationScopeStoreError("Conversation scope storage is unavailable") from exc

    async def get(self, conversation_id: str) -> ConversationScope | None:
        if not isinstance(conversation_id, str) or not conversation_id:
            return None
        collection = self._collection()
        now = self._utc_now()
        try:
            document = await collection.find_one({"_id": conversation_id, "expires_at": {"$gt": now}})
        except Exception as exc:
            logger.warning("conversation_scope_read_failed", error_type=type(exc).__name__)
            raise ConversationScopeStoreError("Conversation scope storage is unavailable") from exc
        if isinstance(document, dict) and (document.get("privacy") or {}).get("status") == "erased":
            return None
        return self._from_document(document)

    async def set_long_term_memory_consent(
        self,
        *,
        conversation_id: str,
        user_id: str,
        agent_id: str,
        granted: bool,
        policy_version: str | None = None,
    ) -> None:
        """Persist explicit, session-bound consent for episodic memory only."""
        collection = self._collection()
        now = self._utc_now()
        try:
            result = await collection.update_one(
                {
                    "_id": conversation_id,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "privacy.status": {"$ne": "erased"},
                },
                {
                    "$set": {
                        "privacy.long_term_memory_consent": "granted" if granted else "withdrawn",
                        "privacy.updated_at": now,
                        "privacy.policy_version": policy_version,
                    },
                },
            )
        except Exception as exc:
            logger.warning("conversation_scope_consent_write_failed", error_type=type(exc).__name__)
            raise ConversationScopeStoreError("Conversation scope storage is unavailable") from exc
        if not getattr(result, "matched_count", 0):
            raise ConversationScopeAuthorizationError("Widget session is not authorized for this conversation")

    async def has_long_term_memory_consent(
        self,
        *,
        conversation_id: str,
        user_id: str,
        agent_id: str,
    ) -> bool:
        """Whether this signed session explicitly opted into episodic memory."""
        collection = self._collection()
        try:
            document = await collection.find_one(
                {
                    "_id": conversation_id,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "privacy.status": {"$ne": "erased"},
                    "privacy.long_term_memory_consent": "granted",
                },
                {"_id": 1},
            )
        except Exception as exc:
            logger.warning("conversation_scope_consent_read_failed", error_type=type(exc).__name__)
            raise ConversationScopeStoreError("Conversation scope storage is unavailable") from exc
        return bool(document)

    async def require_active_widget_scope(
        self,
        *,
        conversation_id: str,
        user_id: str,
        agent_id: str,
    ) -> ConversationScope:
        """Return the immutable scope only while the agent still belongs to it.

        A widget JWT binds a visitor to an agent, but an agent can later be
        moved between brands by an operator.  Looking up messages through the
        agent's current brand database without this check would make an old
        token cross the tenant boundary.  Keep the original scope authoritative
        and reject the session rather than routing it to the new tenant.
        """
        scope = await self.get(conversation_id)
        if (
            scope is None
            or scope.user_id != user_id
            or scope.agent_id != agent_id
        ):
            raise ConversationScopeAuthorizationError("Widget session is not authorized for this conversation")

        try:
            agent = await connection_manager.get_system_db().agents.find_one(
                {"id": agent_id},
                {"brand_id": 1, "brand_slug": 1, "status": 1},
            )
        except (RuntimeError, AttributeError, KeyError, TypeError) as exc:
            raise ConversationScopeStoreError("Conversation scope storage is unavailable") from exc
        except Exception as exc:
            logger.warning("conversation_scope_agent_lookup_failed", error_type=type(exc).__name__)
            raise ConversationScopeStoreError("Conversation scope storage is unavailable") from exc

        if (
            not isinstance(agent, dict)
            or agent.get("status") != "active"
            or agent.get("brand_id") != scope.brand_id
            or agent.get("brand_slug") != scope.brand_slug
        ):
            raise ConversationScopeAuthorizationError("Widget session is no longer active for this tenant")
        return scope


conversation_scope_store = ConversationScopeStore()
