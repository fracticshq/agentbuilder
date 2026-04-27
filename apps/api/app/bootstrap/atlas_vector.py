from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.bootstrap.database import BootstrapCheck
from app.config import Settings


def atlas_vector_index_definition(settings: Settings) -> dict[str, Any]:
    return {
        "fields": [
            {
                "type": "vector",
                "path": "embeddings",
                "numDimensions": settings.VECTOR_DIMENSIONS,
                "similarity": "cosine",
            },
            {"type": "filter", "path": "metadata.brand_id"},
            {"type": "filter", "path": "metadata.brand_slug"},
            {"type": "filter", "path": "agent_id"},
            {"type": "filter", "path": "content_type"},
        ]
    }


async def check_atlas_vector_index(db: AsyncIOMotorDatabase, settings: Settings) -> BootstrapCheck:
    collection = db["knowledge_base"]
    index_name = settings.VECTOR_INDEX_NAME
    try:
        cursor = collection.list_search_indexes(index_name)
        indexes = await cursor.to_list(length=5)
    except Exception as exc:
        return BootstrapCheck(
            name=f"{db.name}.knowledge_base.{index_name}",
            status="manual",
            detail="Could not inspect Atlas Vector Search index. Create it manually if using Atlas.",
            metadata={"error": str(exc), "definition": atlas_vector_index_definition(settings)},
        )

    if indexes:
        return BootstrapCheck(name=f"{db.name}.knowledge_base.{index_name}", status="ok", detail="Atlas vector index found")

    return BootstrapCheck(
        name=f"{db.name}.knowledge_base.{index_name}",
        status="manual",
        detail="Atlas vector index is missing. Create it using docs/ATLAS_VECTOR_INDEX.json.",
        metadata={"definition": atlas_vector_index_definition(settings)},
    )
