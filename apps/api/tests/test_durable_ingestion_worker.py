"""Focused lifecycle coverage for restart-safe v2 ingestion jobs."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.connections import connection_manager
from app.services.ingestion_service import IngestionIdempotencyConflictError, IngestionService
from app.services.job_store import JobStore


class _Result:
    def __init__(self, matched_count=0, deleted_count=0, inserted_id=None):
        self.matched_count = matched_count
        self.deleted_count = deleted_count
        self.inserted_id = inserted_id


def _value(document, key):
    value = document
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, item) for item in expected):
                return False
            continue
        actual = _value(document, key)
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$in" and actual not in operand:
                    return False
                if operator == "$nin" and actual in operand:
                    return False
                if operator == "$lte" and (actual is None or actual > operand):
                    return False
                if operator == "$exists" and ((actual is not None) != bool(operand)):
                    return False
        elif actual != expected:
            return False
    return True


class _Cursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, fields):
        for field, direction in reversed(fields):
            self.documents.sort(key=lambda item: _value(item, field), reverse=direction < 0)
        return self

    def __aiter__(self):
        self._iterator = iter(self.documents)
        return self

    async def __anext__(self):
        try:
            return deepcopy(next(self._iterator))
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self):
        self.documents = {}

    async def create_index(self, *args, **kwargs):
        return kwargs.get("name")

    async def insert_one(self, document):
        if document["_id"] in self.documents:
            raise RuntimeError("duplicate key")
        self.documents[document["_id"]] = deepcopy(document)
        return _Result(inserted_id=document["_id"])

    async def find_one(self, query, projection=None):
        for document in self.documents.values():
            if _matches(document, query):
                return deepcopy(document)
        return None

    async def update_one(self, query, update, upsert=False):
        document = next((item for item in self.documents.values() if _matches(item, query)), None)
        if document is None:
            if not upsert:
                return _Result()
            document = {"_id": query["_id"]}
            document.update(deepcopy(update.get("$setOnInsert", {})))
            self.documents[document["_id"]] = document
        for key, value in update.get("$set", {}).items():
            document[key] = deepcopy(value)
        for key, value in update.get("$inc", {}).items():
            document[key] = document.get(key, 0) + value
        return _Result(matched_count=1)

    async def find_one_and_update(self, query, update, sort=None, return_document=None):
        candidates = [item for item in self.documents.values() if _matches(item, query)]
        if not candidates:
            return None
        if sort:
            for field, direction in reversed(sort):
                candidates.sort(key=lambda item: _value(item, field), reverse=direction < 0)
        document = candidates[0]
        for key, value in update.get("$set", {}).items():
            document[key] = deepcopy(value)
        for key, value in update.get("$inc", {}).items():
            document[key] = document.get(key, 0) + value
        return deepcopy(document)

    async def delete_many(self, query):
        ids = [key for key, item in self.documents.items() if _matches(item, query)]
        for key in ids:
            self.documents.pop(key)
        return _Result(deleted_count=len(ids))

    def find(self, query):
        return _Cursor([deepcopy(item) for item in self.documents.values() if _matches(item, query)])


class _SystemDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def durable_mongo(monkeypatch):
    system = _SystemDb()
    brands = {}
    monkeypatch.setattr(connection_manager, "get_system_db", lambda: system)
    monkeypatch.setattr(connection_manager, "get_brand_db", lambda slug: brands.setdefault(slug, _SystemDb()))
    monkeypatch.setattr(connection_manager, "redis_client", None)
    return system, brands


@pytest.mark.asyncio
async def test_submission_persists_encrypted_payload_and_immutable_scope_snapshot(durable_mongo):
    system, _ = durable_mongo
    service = IngestionService(Settings(VECTOR_BACKEND="atlas"))
    source = b"private source bytes must not be in the job"

    job_id = await service.submit_durable_job(
        [{"content": source, "filename": "private.txt", "content_type": "text/plain"}],
        agent_id="agent-a",
        brand_id="brand-a",
        brand_slug="brand-a-slug",
        chunk_size=500,
        chunk_overlap=60,
    )

    job = system["ingestion_jobs"].documents[job_id]
    payload = next(iter(system["ingestion_payloads"].documents.values()))
    assert job["status"] == "queued"
    assert job["snapshot"] == {
        "agent_id": "agent-a",
        "brand_id": "brand-a",
        "brand_slug": "brand-a-slug",
        "chunk_size": 500,
        "chunk_overlap": 60,
    }
    assert source not in repr(job).encode()
    assert source not in bytes(payload["content_encrypted"])
    assert (await service.payload_store.load(payload["_id"], job_id=job_id))["content"] == source


@pytest.mark.asyncio
async def test_brand_scoped_structured_upload_is_encrypted_durable_and_preserves_product_contract(durable_mongo):
    system, brands = durable_mongo
    service = IngestionService(Settings(VECTOR_BACKEND="atlas"))
    service._generate_embeddings = AsyncMock(return_value=[0.25] * 1024)
    source = json.dumps([
        {
            "sku": "SKU-BLACK",
            "name": "Mixer Black",
            "price": 420000,
            "currency": "INR",
            "category": "mixers",
            "in_stock": True,
            "features": ["matte"],
            "product_group_id": "shopify:mixer",
            "variant_id": "black",
            "variant_sku": "SKU-BLACK",
            "variant_options": {"Colour": "Black"},
        }
    ]).encode("utf-8")

    job_id = await service.submit_durable_job(
        [{
            "content": source,
            "filename": "catalog.json",
            "content_type": "application/json",
            "context": {"kb_content_type": "product", "folder_path": "/catalog/2026"},
        }],
        agent_id=None,
        brand_id="brand-a",
        brand_slug="brand-a-slug",
        chunk_size=500,
        chunk_overlap=60,
        job_metadata={"submission_kind": "knowledge_bulk", "items_count": 1},
    )

    payload = next(iter(system["ingestion_payloads"].documents.values()))
    assert b"SKU-BLACK" not in bytes(payload["content_encrypted"])
    assert b"catalog/2026" not in bytes(payload["context_encrypted"])
    assert "context" not in system["ingestion_jobs"].documents[job_id]

    assert await service.process_next_durable_job(worker_id="worker-1") is True
    job = system["ingestion_jobs"].documents[job_id]
    assert job["status"] == "completed"
    published = next(iter(brands["brand-a-slug"]["knowledge_base"].documents.values()))
    assert published["agent_id"] is None
    assert published["metadata"]["folder"] == "/catalog/2026"
    assert published["product_data"]["variant_sku"] == "SKU-BLACK"
    assert published["product_data"]["product_group_id"] == "shopify:mixer"


@pytest.mark.asyncio
async def test_idempotent_submission_reuses_job_and_rejects_different_source(durable_mongo):
    system, _ = durable_mongo
    service = IngestionService(Settings(VECTOR_BACKEND="atlas"))
    first = [{"content": b"same source", "filename": "guide.txt", "content_type": "text/plain"}]
    job_id = await service.submit_durable_job(
        first,
        agent_id="agent-a",
        brand_id="brand-a",
        brand_slug="brand-a-slug",
        chunk_size=500,
        chunk_overlap=60,
        idempotency_key="upload-retry-1",
    )

    retry_job_id = await service.submit_durable_job(
        first,
        agent_id="agent-a",
        brand_id="brand-a",
        brand_slug="brand-a-slug",
        chunk_size=500,
        chunk_overlap=60,
        idempotency_key="upload-retry-1",
    )
    assert retry_job_id == job_id
    assert len(system["ingestion_jobs"].documents) == 1
    assert len(system["ingestion_payloads"].documents) == 1

    with pytest.raises(IngestionIdempotencyConflictError):
        await service.submit_durable_job(
            [{"content": b"different source", "filename": "guide.txt", "content_type": "text/plain"}],
            agent_id="agent-a",
            brand_id="brand-a",
            brand_slug="brand-a-slug",
            chunk_size=500,
            chunk_overlap=60,
            idempotency_key="upload-retry-1",
        )


@pytest.mark.asyncio
async def test_claim_reclaim_and_fencing_are_mongo_atomic(durable_mongo):
    system, _ = durable_mongo
    store = JobStore()
    await store.create_durable_job(
        "job-claim",
        {
            "agent_id": "agent-a", "brand_id": "brand-a", "brand_slug": "brand-a",
            "snapshot": {"agent_id": "agent-a", "brand_id": "brand-a", "brand_slug": "brand-a", "chunk_size": 500, "chunk_overlap": 60},
            "payload_refs": [], "files_count": 0,
        },
    )
    first = await store.claim_next(worker_id="one", lease_seconds=30)
    assert first and first["lease_token"]
    assert await store.claim_next(worker_id="two", lease_seconds=30) is None

    system["ingestion_jobs"].documents["job-claim"]["lease_expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    second = await store.claim_next(worker_id="two", lease_seconds=30)
    assert second and second["lease_token"] != first["lease_token"]
    assert not await store.begin_publish("job-claim", first["lease_token"])
    assert await store.begin_publish("job-claim", second["lease_token"])


@pytest.mark.asyncio
async def test_retry_and_cancellation_cannot_be_overwritten_by_stale_worker(durable_mongo):
    system, _ = durable_mongo
    store = JobStore()
    base = {
        "agent_id": "agent-a", "brand_id": "brand-a", "brand_slug": "brand-a",
        "snapshot": {"agent_id": "agent-a", "brand_id": "brand-a", "brand_slug": "brand-a", "chunk_size": 500, "chunk_overlap": 60},
        "payload_refs": [], "files_count": 0,
    }
    await store.create_durable_job("job-retry", base)
    claim = await store.claim_next(worker_id="worker", lease_seconds=30)
    assert claim
    assert await store.retry_or_fail(
        "job-retry", claim["lease_token"], error="Document processing failed", retryable=True,
        max_attempts=3, retry_delay_seconds=1,
    )
    assert system["ingestion_jobs"].documents["job-retry"]["status"] == "queued"
    assert await store.cancel("job-retry")
    assert system["ingestion_jobs"].documents["job-retry"]["status"] == "cancelled"

    await store.create_durable_job("job-cancel", base)
    running = await store.claim_next(worker_id="worker", lease_seconds=30)
    assert running and running["job_id"] == "job-cancel"
    assert await store.cancel("job-cancel")
    assert not await store.complete("job-cancel", running["lease_token"])
    assert system["ingestion_jobs"].documents["job-cancel"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_publish_retry_never_becomes_terminal_after_partial_commit(durable_mongo):
    system, _ = durable_mongo
    store = JobStore()
    await store.create_durable_job(
        "job-publish-retry",
        {
            "agent_id": "agent-a", "brand_id": "brand-a", "brand_slug": "brand-a",
            "snapshot": {"agent_id": "agent-a", "brand_id": "brand-a", "brand_slug": "brand-a", "chunk_size": 500, "chunk_overlap": 60},
            "payload_refs": [], "files_count": 0,
        },
    )
    first = await store.claim_next(worker_id="worker", lease_seconds=30)
    assert first
    assert await store.begin_publish("job-publish-retry", first["lease_token"])

    # Even with a retry budget of one, a publish failure cannot be terminal:
    # deterministic upserts may already have made some chunks visible.
    assert await store.retry_or_fail(
        "job-publish-retry", first["lease_token"], error="Failed to store knowledge-base document",
        retryable=True, max_attempts=1, retry_delay_seconds=1,
    )
    pending = system["ingestion_jobs"].documents["job-publish-retry"]
    assert pending["status"] == "queued"
    assert pending["phase"] == "publishing"

    pending["next_attempt_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    resumed = await store.claim_next(worker_id="recovery", lease_seconds=30)
    assert resumed
    assert resumed["phase"] == "publishing"


@pytest.mark.asyncio
async def test_deterministic_publish_upserts_fixed_creation_brand_after_agent_move(durable_mongo):
    _, brands = durable_mongo
    service = IngestionService(Settings(VECTOR_BACKEND="atlas"))
    snapshot = {"agent_id": "agent-a", "brand_id": "brand-a", "brand_slug": "brand-original", "chunk_size": 500, "chunk_overlap": 60}
    staged = {
        "chunk_id": service._durable_chunk_id("job-publish", 0, 0),
        "job_id": "job-publish", "filename": "guide.txt", "content": "stable content",
        "embeddings": [0.25] * 1024, "metadata": {"job_id": "job-publish"}, "content_type": "guide",
    }

    # The current agent could now point to another brand; publishing deliberately
    # receives only the creation snapshot and must never resolve that agent.
    await service._publish_staged_chunk(staged, snapshot)
    await service._publish_staged_chunk(staged, snapshot)

    assert "brand-original" in brands
    assert "brand-moved" not in brands
    chunks = brands["brand-original"]["knowledge_base"].documents
    assert list(chunks) == [staged["chunk_id"]]
    assert chunks[staged["chunk_id"]]["brand_id"] == "brand-a"
