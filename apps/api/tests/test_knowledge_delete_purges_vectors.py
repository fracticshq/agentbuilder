"""Deleting a file must purge its vectors, not just its Mongo chunks.

With the Qdrant vector backend, chunks are written to both Mongo and Qdrant.
Mongo-only deletion left the vectors searchable, so a "deleted" file still
surfaced in retrieval. These tests pin that delete_document also purges Qdrant
points for the document, and that the Qdrant delete filter targets the doc id.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.qdrant_vector_service import QdrantVectorService
from app.services.knowledge_service import KnowledgeService


def _settings():
    return SimpleNamespace(
        QDRANT_COLLECTION_PREFIX="nova",
        MONGODB_DATABASE="agent-builder",
        QDRANT_URL="http://localhost:6333",
        QDRANT_API_KEY="",
        VECTOR_DIMENSIONS=1024,
    )


@pytest.mark.asyncio
async def test_delete_by_document_filters_on_doc_id():
    pytest.importorskip("qdrant_client")  # container-only dependency
    svc = QdrantVectorService(_settings())
    client = AsyncMock()
    client.collection_exists.return_value = True
    client.delete.return_value = SimpleNamespace(status="completed")
    svc._client = client

    await svc.delete_by_document("job-123", brand_slug="acme")

    client.delete.assert_awaited_once()
    kwargs = client.delete.call_args.kwargs
    assert kwargs["collection_name"] == "nova_acme_knowledge_base"
    # The filter should reference the doc id across the id fields it's stored under.
    selector = kwargs["points_selector"]
    rendered = repr(selector)
    assert "job-123" in rendered
    assert "doc_id" in rendered


@pytest.mark.asyncio
async def test_delete_by_document_noop_when_collection_missing():
    pytest.importorskip("qdrant_client")  # container-only dependency
    svc = QdrantVectorService(_settings())
    client = AsyncMock()
    client.collection_exists.return_value = False
    svc._client = client

    await svc.delete_by_document("job-123", brand_slug="acme")

    client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_document_purges_qdrant(monkeypatch):
    service = KnowledgeService.__new__(KnowledgeService)

    # Stub the Mongo side: one collection that reports a deletion.
    class FakeResult:
        deleted_count = 3

    class FakeCollection:
        async def delete_many(self, *_a, **_k):
            return FakeResult()

    async def fake_ensure(*_a, **_k):
        return None

    async def fake_scope(_identifier):
        return {"brand_id": "acme", "brand_slug": "acme", "aliases": ["acme"], "db_name": "acme"}

    async def fake_collections(_brand_id):
        return [FakeCollection()]

    monkeypatch.setattr(service, "_ensure_connection", fake_ensure)
    monkeypatch.setattr(service, "_resolve_brand_scope", fake_scope)
    monkeypatch.setattr(service, "_get_brand_knowledge_collections", fake_collections)

    qdrant = AsyncMock()
    service.qdrant = qdrant

    deleted = await service.delete_document("job-123", brand_id="acme")

    assert deleted is True
    qdrant.delete_by_document.assert_awaited_once()
    assert qdrant.delete_by_document.call_args.args[0] == "job-123"
    assert qdrant.delete_by_document.call_args.kwargs["brand_slug"] == "acme"
