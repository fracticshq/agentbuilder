from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings
from app.connections import connection_manager
from app.services.agent_api_keys import AgentApiKeyService
from app.services.runtime_settings_service import RuntimeSettingsService

logger = structlog.get_logger(__name__)


@dataclass
class BootstrapCheck:
    name: str
    status: str
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def sanitize_database_name(value: str) -> str:
    return (value or "default").replace(".", "_")[:63]


async def ensure_system_indexes(system_db: AsyncIOMotorDatabase, settings: Settings) -> list[BootstrapCheck]:
    checks: list[BootstrapCheck] = []

    async def create(check_name: str, collection: str, *args, **kwargs) -> None:
        try:
            await system_db[collection].create_index(*args, **kwargs)
            checks.append(BootstrapCheck(name=check_name, status="ok", detail="index ready"))
        except Exception as exc:
            if "already exists" in str(exc):
                checks.append(BootstrapCheck(name=check_name, status="ok", detail="index already exists"))
                return
            checks.append(BootstrapCheck(name=check_name, status="error", detail=str(exc)))
            raise

    await create("system.brands.id", "brands", "id", unique=True, name="brand_id_idx")
    await create("system.brands.slug", "brands", "slug", unique=True, name="brand_slug_idx")
    await create("system.agents.id", "agents", "id", unique=True, name="agent_id_idx")
    await create("system.agents.brand_id", "agents", "brand_id", name="agent_brand_id_idx")
    await create("system.agents.brand_slug", "agents", [("brand_id", 1), ("slug", 1)], unique=True, name="agent_brand_slug_idx")
    await create("system.users.email", "users", "email", unique=True, name="users_email_idx")
    await create("system.users.username", "users", "username", unique=True, name="users_username_idx")
    await create(
        "system.password_reset_tokens.expires_at",
        "password_reset_tokens",
        "expires_at",
        expireAfterSeconds=0,
        name="password_reset_expiry_idx",
    )
    await create("system.audit_logs.created_at", "audit_logs", "created_at", name="audit_logs_created_at_idx")

    await RuntimeSettingsService(settings).ensure_indexes()
    checks.append(BootstrapCheck(name="system.runtime_settings", status="ok", detail="indexes ready"))
    await AgentApiKeyService().ensure_indexes()
    checks.append(BootstrapCheck(name="system.agent_api_keys", status="ok", detail="indexes ready"))
    return checks


async def ensure_brand_knowledge_indexes(db: AsyncIOMotorDatabase) -> list[BootstrapCheck]:
    checks: list[BootstrapCheck] = []
    collection = db["knowledge_base"]
    db_name = db.name

    async def create(check_name: str, *args, **kwargs) -> None:
        try:
            await collection.create_index(*args, **kwargs)
            checks.append(BootstrapCheck(name=f"{db_name}.knowledge_base.{check_name}", status="ok", detail="index ready"))
        except Exception as exc:
            error_text = str(exc)
            if "already exists" in error_text or "IndexOptionsConflict" in error_text:
                checks.append(BootstrapCheck(name=f"{db_name}.knowledge_base.{check_name}", status="ok", detail="compatible existing index present"))
                return
            checks.append(BootstrapCheck(name=f"{db_name}.knowledge_base.{check_name}", status="error", detail=str(exc)))
            raise

    await create(
        "text_index",
        [("content", "text"), ("title", "text"), ("section", "text")],
        name="text_index",
        weights={"title": 10, "section": 5, "content": 1},
    )
    await create("agent_id", "agent_id", name="knowledge_agent_id_idx")
    await create("content_type", "content_type", name="knowledge_content_type_idx")
    await create("metadata.brand_id", "metadata.brand_id", name="knowledge_metadata_brand_id_idx")
    await create("metadata.brand_slug", "metadata.brand_slug", name="knowledge_metadata_brand_slug_idx")
    await create("created_at", "created_at", name="knowledge_created_at_idx")

    try:
        result = await collection.update_many(
            {"embeddings": {"$exists": False}, "embedding": {"$exists": True}},
            [{"$set": {"embeddings": "$embedding"}}],
        )
        checks.append(
            BootstrapCheck(
                name=f"{db_name}.knowledge_base.embeddings_normalized",
                status="ok",
                detail=f"{result.modified_count} legacy rows normalized",
            )
        )
    except Exception as exc:
        checks.append(
            BootstrapCheck(
                name=f"{db_name}.knowledge_base.embeddings_normalized",
                status="error",
                detail=str(exc),
            )
        )
        raise
    return checks


async def brand_database_names(settings: Settings) -> list[str]:
    system_db = connection_manager.get_system_db()
    names: set[str] = set()
    async for brand in system_db.brands.find({}, {"slug": 1, "id": 1}):
        names.add(sanitize_database_name(brand.get("slug") or brand.get("id")))
    if not names:
        names.add(sanitize_database_name(settings.MONGODB_DATABASE))
    return sorted(name for name in names if name)


async def ensure_existing_brand_indexes(settings: Settings) -> list[BootstrapCheck]:
    client = connection_manager.mongodb_client
    if client is None:
        return [BootstrapCheck(name="mongodb", status="error", detail="MongoDB client is not connected")]

    checks: list[BootstrapCheck] = []
    for db_name in await brand_database_names(settings):
        checks.extend(await ensure_brand_knowledge_indexes(client[db_name]))
    return checks


async def bootstrap_database(settings: Settings) -> list[BootstrapCheck]:
    checks: list[BootstrapCheck] = []
    await connection_manager.connect_mongodb()

    if connection_manager.system_db is None:
        return [BootstrapCheck(name="mongodb", status="error", detail="MongoDB is not connected")]

    checks.append(BootstrapCheck(name="mongodb", status="ok", detail="connected"))
    checks.extend(await ensure_system_indexes(connection_manager.system_db, settings))
    checks.extend(await ensure_existing_brand_indexes(settings))
    return checks
