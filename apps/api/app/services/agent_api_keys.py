from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from app.connections import connection_manager


AGENT_API_KEY_PREFIX = "ab_agent_v1"
AGENT_API_COLLECTION = "agent_api_keys"
DEFAULT_AGENT_API_SCOPES = [
    "sessions:create",
    "sessions:read",
    "messages:write",
    "messages:stream",
    "agents:read",
]

LEGACY_SCOPE_ALIASES = {
    "agent:read": "agents:read",
    "message:create": "messages:write",
    "message:stream": "messages:stream",
    "session:read": "sessions:read",
    "session:create": "sessions:create",
}


@dataclass(frozen=True)
class AgentApiKeyContext:
    id: str
    key_id: str
    scopes: set[str]
    agent_id: str | None
    brand_id: str | None


def hash_agent_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_agent_api_key() -> tuple[str, str, str]:
    key_secret = secrets.token_urlsafe(32)
    key_id = f"{AGENT_API_KEY_PREFIX}_{secrets.token_hex(4)}"
    full_key = f"{key_id}_{key_secret}"
    return full_key, key_id, hash_agent_api_key(full_key)


def extract_agent_api_key_id(api_key: str | None) -> str | None:
    if not api_key or not api_key.startswith(f"{AGENT_API_KEY_PREFIX}_"):
        return None
    parts = api_key.split("_")
    if len(parts) < 5:
        return None
    return "_".join(parts[:4])


def mask_agent_api_key_id(key_id: str) -> str:
    if len(key_id) <= 8:
        return "****"
    return f"{key_id[:12]}...{key_id[-4:]}"


class AgentApiKeyService:
    def _collection(self):
        return connection_manager.get_system_db()[AGENT_API_COLLECTION]

    async def ensure_indexes(self) -> None:
        collection = self._collection()
        await collection.create_index("key_id", unique=True, name="agent_api_key_id_idx")
        await collection.create_index("agent_id", name="agent_api_agent_id_idx")
        await collection.create_index("brand_id", name="agent_api_brand_id_idx")

    async def create_key(
        self,
        *,
        name: str,
        scopes: list[str] | None = None,
        agent_id: str | None = None,
        brand_id: str | None = None,
        created_by: str = "admin",
    ) -> dict[str, Any]:
        full_key, key_id, key_hash = generate_agent_api_key()
        now = datetime.now(timezone.utc)
        requested_scopes = self._normalize_scopes(scopes or DEFAULT_AGENT_API_SCOPES)
        doc = {
            "id": str(uuid.uuid4()),
            "key_id": key_id,
            "name": name.strip(),
            "key_hash": key_hash,
            "scopes": sorted(set(requested_scopes)),
            "agent_id": agent_id,
            "brand_id": brand_id,
            "is_active": True,
            "created_at": now,
            "created_by": created_by,
            "revoked_at": None,
            "last_used_at": None,
            "usage": {"total_requests": 0},
        }
        await self._collection().insert_one(doc)
        return {**self._public_doc(doc), "api_key": full_key}

    async def list_keys(
        self,
        *,
        agent_id: str | None = None,
        brand_id: str | None = None,
        brand_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if agent_id:
            query["agent_id"] = agent_id
        if brand_id:
            query["brand_id"] = brand_id
        elif brand_ids is not None:
            query["brand_id"] = {"$in": brand_ids}
        cursor = self._collection().find(query).sort("created_at", -1)
        return [self._public_doc(doc) for doc in await cursor.to_list(length=200)]

    async def get_key(self, key_id: str) -> dict[str, Any] | None:
        return await self._collection().find_one({"key_id": key_id})

    async def revoke_key(self, key_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        result = await self._collection().update_one(
            {"key_id": key_id, "is_active": True},
            {"$set": {"is_active": False, "revoked_at": now}},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Agent API key not found")
        doc = await self._collection().find_one({"key_id": key_id})
        return self._public_doc(doc)

    async def authenticate(self, api_key: str | None, *, required_scope: str) -> AgentApiKeyContext:
        key_id = extract_agent_api_key_id(api_key)
        if not key_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Agent API key required",
            )

        collection = self._collection()
        doc = await collection.find_one({"key_id": key_id})
        if not doc or not doc.get("is_active"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Agent API key")
        if not secrets.compare_digest(hash_agent_api_key(api_key or ""), doc.get("key_hash") or ""):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Agent API key")

        scopes = set(self._normalize_scopes(doc.get("scopes") or []))
        if not self._scope_allows(scopes, required_scope):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient Agent API key scope")

        await collection.update_one(
            {"key_id": key_id},
            {
                "$set": {"last_used_at": datetime.now(timezone.utc)},
                "$inc": {"usage.total_requests": 1},
            },
        )
        return AgentApiKeyContext(
            id=str(doc.get("id") or doc.get("_id") or ""),
            key_id=key_id,
            scopes=scopes,
            agent_id=doc.get("agent_id"),
            brand_id=doc.get("brand_id"),
        )

    def assert_agent_allowed(self, context: AgentApiKeyContext, agent: dict[str, Any] | None) -> None:
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if context.agent_id and agent.get("id") != context.agent_id:
            raise HTTPException(status_code=403, detail="Agent API key is not allowed for this agent")
        if context.brand_id and agent.get("brand_id") != context.brand_id:
            raise HTTPException(status_code=403, detail="Agent API key is not allowed for this brand")

    def _scope_allows(self, scopes: set[str], required_scope: str) -> bool:
        scopes = set(self._normalize_scopes(list(scopes)))
        required_scope = LEGACY_SCOPE_ALIASES.get(required_scope, required_scope)
        family = required_scope.split(":", 1)[0]
        return required_scope in scopes or "*" in scopes or "agent-api:*" in scopes or f"{family}:*" in scopes

    def _normalize_scopes(self, scopes: list[str]) -> list[str]:
        normalized = []
        for scope in scopes:
            canonical = LEGACY_SCOPE_ALIASES.get(str(scope), str(scope))
            normalized.append(canonical)
        return sorted(set(normalized))

    def _public_doc(self, doc: dict[str, Any] | None) -> dict[str, Any]:
        doc = doc or {}
        return {
            "id": str(doc.get("id") or doc.get("_id") or ""),
            "key_id": doc.get("key_id"),
            "name": doc.get("name"),
            "masked_key": mask_agent_api_key_id(doc.get("key_id") or ""),
            "scopes": doc.get("scopes") or [],
            "agent_id": doc.get("agent_id"),
            "brand_id": doc.get("brand_id"),
            "is_active": bool(doc.get("is_active")),
            "created_at": doc.get("created_at"),
            "created_by": doc.get("created_by"),
            "revoked_at": doc.get("revoked_at"),
            "last_used_at": doc.get("last_used_at"),
            "usage": doc.get("usage") or {"total_requests": 0},
        }
