from __future__ import annotations

from typing import Any
import uuid

import structlog

from app.config import Settings

logger = structlog.get_logger(__name__)


def qdrant_collection_name(settings: Settings, brand_slug: str | None) -> str:
    db_name = (brand_slug or settings.MONGODB_DATABASE or "default").replace(".", "_")[:63]
    return f"{settings.QDRANT_COLLECTION_PREFIX}_{db_name}_knowledge_base"


def qdrant_point_id(value: Any) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, str(value or uuid.uuid4())))


class QdrantVectorService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        from qdrant_client import AsyncQdrantClient

        self._client = AsyncQdrantClient(
            url=self.settings.QDRANT_URL,
            api_key=self.settings.QDRANT_API_KEY or None,
            timeout=10,
        )
        return self._client

    async def ensure_collection(self, brand_slug: str | None) -> str:
        from qdrant_client.http import models

        client = self._get_client()
        collection = qdrant_collection_name(self.settings, brand_slug)
        exists = await client.collection_exists(collection)
        if not exists:
            await client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(
                    size=self.settings.VECTOR_DIMENSIONS,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("qdrant_collection_created", collection=collection)
        return collection

    async def upsert_chunk(self, chunk: dict[str, Any], brand_slug: str | None = None) -> None:
        from qdrant_client.http import models

        vector = chunk.get("embeddings") or chunk.get("embedding") or []
        if not vector or len(vector) != self.settings.VECTOR_DIMENSIONS:
            logger.warning(
                "qdrant_upsert_skipped_invalid_vector",
                chunk_id=chunk.get("chunk_id"),
                dimensions=len(vector) if vector else 0,
            )
            return

        metadata = chunk.get("metadata") or {}
        resolved_brand_slug = brand_slug or metadata.get("brand_slug")
        collection = await self.ensure_collection(resolved_brand_slug)
        point_id = qdrant_point_id(chunk.get("chunk_id") or chunk.get("_id"))
        payload = {
            "chunk_id": chunk.get("chunk_id"),
            "doc_id": chunk.get("doc_id"),
            "content": chunk.get("content"),
            "title": chunk.get("title"),
            "url": chunk.get("url"),
            "section": chunk.get("section"),
            "metadata": metadata,
            "created_at": chunk.get("created_at") or metadata.get("created_at"),
            "content_type": chunk.get("content_type"),
            "product_data": chunk.get("product_data"),
            "dealer_data": chunk.get("dealer_data"),
            "agent_id": chunk.get("agent_id") or metadata.get("agent_id"),
        }
        await self._get_client().upsert(
            collection_name=collection,
            points=[models.PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
