"""
Qdrant vector search implementation for local/self-hosted NOVA installs.
"""

import os
from typing import Any, Dict, List, Optional

import structlog

from .voyage_client import VoyageClient
from ..types import DocumentChunk, SearchResult

logger = structlog.get_logger()


def _collection_name(brand_id: Optional[str]) -> str:
    prefix = os.getenv("QDRANT_COLLECTION_PREFIX", "nova")
    db_name = (brand_id or os.getenv("MONGODB_DATABASE", "agent-builder")).replace(".", "_")[:63]
    return f"{prefix}_{db_name}_knowledge_base"


class QdrantVectorSearch:
    """Qdrant vector search with Voyage embeddings."""

    def __init__(
        self,
        voyage_client: Optional[VoyageClient] = None,
        brand_id: Optional[str] = None,
    ):
        from qdrant_client import AsyncQdrantClient

        self.brand_id = brand_id
        self.collection_name = _collection_name(brand_id)
        self.client = AsyncQdrantClient(
            url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            api_key=os.getenv("QDRANT_API_KEY") or None,
            timeout=10,
        )
        self.voyage = voyage_client or VoyageClient()
        logger.info("Qdrant vector search initialized", brand_id=brand_id, collection=self.collection_name)

    def _build_filter(self, filters: Optional[Dict[str, Any]] = None):
        if not filters:
            return None

        from qdrant_client.http import models

        conditions = []
        for key, value in filters.items():
            payload_key = key
            if isinstance(value, dict) and "$in" in value:
                conditions.append(
                    models.FieldCondition(
                        key=payload_key,
                        match=models.MatchAny(any=[str(item) for item in value["$in"]]),
                    )
                )
            else:
                conditions.append(
                    models.FieldCondition(
                        key=payload_key,
                        match=models.MatchValue(value=value),
                    )
                )

        return models.Filter(must=conditions) if conditions else None

    async def search(
        self,
        query: str,
        top_k: int = 50,
        filters: Optional[Dict[str, Any]] = None,
        similarity_threshold: float = 0.7,
    ) -> SearchResult:
        import time

        start_time = time.time()
        query_embedding = await self.voyage.embed_query(query)
        try:
            result = await self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                query_filter=self._build_filter(filters),
                limit=top_k,
                score_threshold=similarity_threshold,
                with_payload=True,
            )
        except Exception as exc:
            if "Not found" in str(exc) or "doesn't exist" in str(exc):
                logger.warning("Qdrant collection missing", collection=self.collection_name)
                result = []
            else:
                raise

        chunks = [self._result_to_chunk(point) for point in result]
        execution_time = (time.time() - start_time) * 1000
        return SearchResult(
            chunks=chunks,
            total_found=len(chunks),
            query=query,
            search_type="qdrant",
            execution_time_ms=execution_time,
            metadata={"top_k": top_k, "threshold": similarity_threshold, "filters": filters or {}},
        )

    def _result_to_chunk(self, point: Any) -> DocumentChunk:
        payload = point.payload or {}
        return DocumentChunk(
            chunk_id=payload.get("chunk_id") or str(point.id),
            doc_id=payload.get("doc_id", "unknown"),
            content=payload.get("content", ""),
            title=payload.get("title"),
            url=payload.get("url"),
            section=payload.get("section"),
            score=float(point.score or 0.0),
            metadata=payload.get("metadata") or {},
            created_at=payload.get("created_at"),
            content_type=payload.get("content_type"),
            product_data=payload.get("product_data"),
            dealer_data=payload.get("dealer_data"),
        )

    async def health_check(self) -> Dict[str, Any]:
        try:
            await self.client.get_collection(self.collection_name)
            qdrant_healthy = True
        except Exception as exc:
            logger.warning("Qdrant health check failed", collection=self.collection_name, error=str(exc))
            qdrant_healthy = False

        voyage_healthy = await self.voyage.health_check()
        return {
            "qdrant": "healthy" if qdrant_healthy else "unhealthy",
            "voyage": "healthy" if voyage_healthy else "unhealthy",
            "overall": "healthy" if (qdrant_healthy and voyage_healthy) else "unhealthy",
        }

    async def close(self):
        await self.voyage.close()
        await self.client.close()
