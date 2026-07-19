from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ingestion as ingestion_module
from app.auth.dependencies import require_dashboard_access
from app.auth.models import User, UserRole
from app.config import Settings
from app.connections import connection_manager
from app.dependencies import get_ingestion_service
from app.services.ingestion_service import IngestionService
from app.services.job_store import JOBS_COLLECTION, JobStore


class _UpdateResult:
    def __init__(self, matched_count: int, deleted_count: int = 0):
        self.matched_count = matched_count
        self.deleted_count = deleted_count


class _JobCollection:
    def __init__(self):
        self.documents: dict[str, dict] = {}
        self.indexes: list[tuple] = []

    async def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))

    async def find_one(self, query):
        document = self.documents.get(query.get("_id"))
        return deepcopy(document) if document else None

    async def update_one(self, query, update, upsert=False):
        job_id = query["_id"]
        document = self.documents.get(job_id)
        if document is None:
            if not upsert:
                return _UpdateResult(matched_count=0)
            document = {"_id": job_id, **deepcopy(update.get("$setOnInsert", {}))}
            self.documents[job_id] = document
            matched_count = 0
        else:
            matched_count = 1
        document.update(deepcopy(update.get("$set", {})))
        return _UpdateResult(matched_count=matched_count)

    async def delete_one(self, query):
        job_id = query["_id"]
        existed = self.documents.pop(job_id, None) is not None
        return _UpdateResult(matched_count=0, deleted_count=int(existed))


class _SystemDb:
    def __init__(self, collection: _JobCollection, agents=None):
        self.collection = collection
        self.agents = _Agents(agents or [])

    def __getitem__(self, name):
        assert name == JOBS_COLLECTION
        return self.collection


class _Agents:
    def __init__(self, agents):
        self.agents = {agent["id"]: agent for agent in agents}

    async def find_one(self, query, *args, **kwargs):
        agent = self.agents.get(query.get("id"))
        return deepcopy(agent) if agent else None


class _Redis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.set_calls: list[dict] = []
        self.fail_get = False

    async def get(self, key):
        if self.fail_get:
            raise RuntimeError("redis read failed")
        return self.values.get(key)

    async def set(self, key, value, ex):
        self.values[key] = value
        self.set_calls.append({"key": key, "value": value, "ex": ex})

    async def delete(self, key):
        self.values.pop(key, None)


def _job_payload(**overrides) -> dict:
    payload = {
        "status": "pending",
        "files_count": 2,
        "processed_count": 0,
        "agent_id": "agent-a",
        "created_at": "2026-07-19T00:00:00Z",
        "completed_at": None,
        "error": None,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def durable_job_store(monkeypatch):
    collection = _JobCollection()
    monkeypatch.setattr(connection_manager, "get_system_db", lambda: _SystemDb(collection))
    monkeypatch.setattr(connection_manager, "redis_client", None)
    return collection


@pytest.mark.asyncio
async def test_new_ingestion_service_instance_reads_existing_durable_job(durable_job_store):
    first_service = IngestionService(Settings(VECTOR_BACKEND="atlas"))
    job_id = await first_service.start_ingestion_job(
        [{"filename": "guide.md"}],
        agent_id="agent-a",
        brand_id="brand-a",
    )

    second_service = IngestionService(Settings(VECTOR_BACKEND="atlas"))
    status = await second_service.get_job_status(job_id)

    assert status is not None
    assert status.job_id == job_id
    assert status.status == "pending"
    assert status.files_count == 1
    assert status.created_at is not None
    assert status.created_at.tzinfo == timezone.utc
    assert durable_job_store.documents[job_id]["_id"] == job_id
    assert durable_job_store.documents[job_id]["brand_id"] == "brand-a"


@pytest.mark.asyncio
async def test_cache_miss_falls_back_to_mongo_and_repopulates_cache(monkeypatch):
    collection = _JobCollection()
    collection.documents["job-cache-miss"] = {"_id": "job-cache-miss", **_job_payload()}
    redis = _Redis()
    monkeypatch.setattr(connection_manager, "get_system_db", lambda: _SystemDb(collection))
    monkeypatch.setattr(connection_manager, "redis_client", redis)

    job = await JobStore().get("job-cache-miss")

    assert job is not None
    assert job["status"] == "pending"
    assert json.loads(redis.values["job:job-cache-miss"])["agent_id"] == "agent-a"


@pytest.mark.asyncio
async def test_cache_failure_falls_back_to_mongo(monkeypatch):
    collection = _JobCollection()
    collection.documents["job-cache-failure"] = {"_id": "job-cache-failure", **_job_payload()}
    redis = _Redis()
    redis.fail_get = True
    monkeypatch.setattr(connection_manager, "get_system_db", lambda: _SystemDb(collection))
    monkeypatch.setattr(connection_manager, "redis_client", redis)

    job = await JobStore().get("job-cache-failure")

    assert job is not None
    assert job["files_count"] == 2


@pytest.mark.asyncio
async def test_update_preserves_existing_fields_and_delete_clears_durable_and_cached_state(monkeypatch):
    collection = _JobCollection()
    redis = _Redis()
    monkeypatch.setattr(connection_manager, "get_system_db", lambda: _SystemDb(collection))
    monkeypatch.setattr(connection_manager, "redis_client", redis)
    store = JobStore()

    await store.set("job-update", _job_payload(brand_id="brand-a"))
    assert await store.update(
        "job-update",
        {"status": "processing", "processed_count": 1, "brand_id": "brand-b"},
    )

    updated = collection.documents["job-update"]
    assert updated["agent_id"] == "agent-a"
    assert updated["brand_id"] == "brand-a"
    assert updated["files_count"] == 2
    assert updated["created_at"] == "2026-07-19T00:00:00Z"
    assert updated["processed_count"] == 1
    assert updated["updated_at"].endswith("Z")
    assert json.loads(redis.values["job:job-update"])["files_count"] == 2

    assert await store.delete("job-update")
    assert "job-update" not in collection.documents
    assert "job:job-update" not in redis.values


@pytest.mark.asyncio
async def test_status_does_not_expose_legacy_provider_diagnostics():
    service = IngestionService(Settings(VECTOR_BACKEND="atlas"))
    service.job_store = SimpleNamespace(
        get=AsyncMock(
            return_value=_job_payload(
                status="error",
                error="Voyage rejected key bearer secret-provider-token with HTTP 401",
            )
        )
    )

    status = await service.get_job_status("job-redacted")

    assert status is not None
    assert status.error == "Document processing failed"
    assert "secret-provider-token" not in status.error


def _brand_a_admin() -> User:
    return User(
        _id="brand-admin",
        email="admin@brand-a.example",
        username="brand-a-admin",
        password_hash="hash",
        role=UserRole.BRAND_ADMIN,
        brands=["brand-a"],
    )


class _TenantJobService:
    def __init__(self):
        self.job_store = SimpleNamespace(get=self._get_job)
        self.status_requested = False
        self.cancel_requested = False

    async def _get_job(self, job_id):
        return _job_payload(agent_id="agent-b", brand_id="brand-b")

    async def get_job_status(self, job_id):
        self.status_requested = True
        raise AssertionError("Tenant authorization must run before reading job status")

    async def cancel_job(self, job_id):
        self.cancel_requested = True
        raise AssertionError("Tenant authorization must run before cancelling a job")


@pytest.mark.parametrize(
    ("method", "path", "operation"),
    [
        ("get", "/api/v1/ingest/status/job-brand-b", "status"),
        ("delete", "/api/v1/ingest/jobs/job-brand-b", "cancel"),
    ],
)
def test_tenant_cannot_read_or_cancel_another_brands_ingestion_job(monkeypatch, method, path, operation):
    service = _TenantJobService()
    app = FastAPI()
    app.include_router(ingestion_module.router, prefix="/api/v1/ingest")
    app.dependency_overrides[require_dashboard_access] = _brand_a_admin
    app.dependency_overrides[get_ingestion_service] = lambda: service
    monkeypatch.setattr(
        ingestion_module.connection_manager,
        "get_system_db",
        lambda: _SystemDb(_JobCollection(), [{"id": "agent-b", "brand_id": "brand-a"}]),
    )

    response = getattr(TestClient(app), method)(path)

    assert response.status_code == 404
    assert service.status_requested is False
    assert service.cancel_requested is False
