"""P2 regressions for knowledge agent scope and catalog job ownership."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import catalog as catalog_module
from app.api.v1.endpoints import knowledge as knowledge_module
from app.auth.dependencies import get_user_from_token_or_api_key, require_dashboard_access
from app.auth.models import User, UserRole
from app.dependencies import get_catalog_sync_store, get_knowledge_service, get_runtime_settings_service
from app.services import catalog_service


class _Collection:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    async def find_one(self, query, *_args, **_kwargs):
        candidates = query.get("$or", [query])
        for candidate in candidates:
            for row in self.rows:
                if all(row.get(key) == value for key, value in candidate.items()):
                    return row
        return None


class _SystemDb:
    def __init__(self, brands: list[dict], agents: list[dict]):
        self.brands = _Collection(brands)
        self.agents = _Collection(agents)


def _brand_admin() -> User:
    return User(
        _id="brand-admin",
        email="admin@brand-a.example",
        username="brand-a-admin",
        password_hash="hash",
        role=UserRole.BRAND_ADMIN,
        brands=["brand-a"],
    )


@pytest.fixture
def scoped_system_db() -> _SystemDb:
    return _SystemDb(
        brands=[
            {"id": "brand-a", "slug": "brand-a-alias"},
            {"id": "brand-b", "slug": "brand-b-alias"},
        ],
        agents=[
            {"id": "agent-a", "brand_id": "brand-a", "brand_slug": "brand-a-alias"},
            {"id": "agent-b", "brand_id": "brand-b", "brand_slug": "brand-b-alias"},
        ],
    )


@pytest.fixture
def knowledge_client(monkeypatch, scoped_system_db):
    service = AsyncMock()
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix="/api/v1/knowledge")
    app.dependency_overrides[require_dashboard_access] = _brand_admin
    app.dependency_overrides[get_knowledge_service] = lambda: service
    monkeypatch.setattr(
        knowledge_module.connection_manager,
        "get_system_db",
        lambda: scoped_system_db,
    )
    return TestClient(app), service


def test_knowledge_cross_tenant_agent_read_is_hidden_before_service(knowledge_client):
    client, service = knowledge_client

    response = client.get(
        "/api/v1/knowledge/tree",
        params={"brand_id": "brand-a", "agent_id": "agent-b"},
    )

    assert response.status_code == 404
    service.list_knowledge_tree.assert_not_awaited()


def test_knowledge_cross_tenant_agent_write_is_hidden_before_service(knowledge_client):
    client, service = knowledge_client

    response = client.post(
        "/api/v1/knowledge/folders",
        json={"brand_id": "brand-a", "agent_id": "agent-b", "name": "Private"},
    )

    assert response.status_code == 404
    service.create_folder.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalog_create_job_persists_owner_scope(monkeypatch):
    set_job = AsyncMock()
    monkeypatch.setattr(catalog_service._job_store, "set", set_job)

    await catalog_service.create_job("catalog-job", "shopify", brand_id="brand-a", total=4)

    payload = set_job.await_args.args[1]
    assert payload["brand_id"] == "brand-a"
    assert payload["total"] == 4


@pytest.fixture
def catalog_app(monkeypatch, scoped_system_db):
    app = FastAPI()
    app.include_router(catalog_module.router, prefix="/api/v1/catalog")
    app.dependency_overrides[get_user_from_token_or_api_key] = _brand_admin
    class _RuntimeSettings:
        def _encrypt(self, value):
            return f"encrypted:{value}"

        def _decrypt(self, value):
            return value.removeprefix("encrypted:")

    class _CatalogSyncStore:
        async def enqueue_sync(self, **kwargs):
            return ({"job_id": kwargs["job_id"], "status": "queued", "brand_id": kwargs["brand_id"]}, False)

        async def get(self, _job_id):
            return None

    app.dependency_overrides[get_runtime_settings_service] = _RuntimeSettings
    app.dependency_overrides[get_catalog_sync_store] = _CatalogSyncStore
    monkeypatch.setattr(
        catalog_module.connection_manager,
        "get_system_db",
        lambda: scoped_system_db,
    )
    return app


def test_shopify_job_owner_is_created_before_durable_worker_runs(monkeypatch, catalog_app):
    events = []

    async def create_job(job_id, job_type, brand_id, total=0):
        events.append(("create", job_id, job_type, brand_id, total))

    monkeypatch.setattr(catalog_module, "_upsert_sync_config", AsyncMock())
    monkeypatch.setattr(catalog_service, "create_job", create_job)

    response = TestClient(catalog_app).post(
        "/api/v1/catalog/import/shopify",
        json={"brand_id": "brand-a-alias", "store_url": "store.myshopify.com", "access_token": "shpat_test"},
    )

    assert response.status_code == 200
    assert events[0][0] == "create"
    assert events[0][3] == "brand-a"
    assert len(events) == 1


def test_manual_shopify_sync_creates_owned_job_before_durable_worker_runs(monkeypatch, catalog_app):
    events = []
    catalog_app  # Keep the fixture's dependency and connection overrides alive.

    class _ManualBrands(_Collection):
        async def find_one(self, query, *_args, **_kwargs):
            if query == {"id": "brand-a"}:
                return {
                    "id": "brand-a",
                    "catalog_sync": {
                        "source_type": "shopify",
                        "source_url": "https://store.myshopify.com",
                        "access_token_encrypted": "encrypted:shpat_test",
                        "enabled": True,
                    },
                }
            return await super().find_one(query, *_args, **_kwargs)

    system_db = _SystemDb([], [])
    system_db.brands = _ManualBrands([])
    monkeypatch.setattr(catalog_module.connection_manager, "get_system_db", lambda: system_db)

    async def create_job(job_id, job_type, brand_id, total=0):
        events.append(("create", job_id, job_type, brand_id, total))

    monkeypatch.setattr(catalog_service, "create_job", create_job)

    response = TestClient(catalog_app).post("/api/v1/catalog/sync/brand-a")

    assert response.status_code == 200
    assert events[0][0] == "create"
    assert events[0][3] == "brand-a"
    assert len(events) == 1


def test_firecrawl_worker_receives_canonical_job_owner(monkeypatch, catalog_app):
    events = []

    async def create_job(job_id, job_type, brand_id, total=0):
        events.append(("create", job_id, job_type, brand_id, total))

    async def resolve_currency(_brand_id):
        return None

    async def run_firecrawl_scrape(urls, job_id, api_key, brand_id, *, fallback_currency=None):
        events.append(("worker", urls, job_id, api_key, brand_id, fallback_currency))

    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-firecrawl-key")
    monkeypatch.setattr(catalog_service, "create_job", create_job)
    monkeypatch.setattr(catalog_service, "_resolve_configured_default_currency", resolve_currency)
    monkeypatch.setattr(catalog_service, "run_firecrawl_scrape", run_firecrawl_scrape)

    response = TestClient(catalog_app).post(
        "/api/v1/catalog/import/scrape",
        json={"brand_id": "brand-a-alias", "urls": ["https://example.com/product"]},
    )

    assert response.status_code == 200
    assert events[0][0] == "create"
    assert events[0][3] == "brand-a"
    assert events[1][0] == "worker"
    assert events[1][4] == "brand-a"


def test_catalog_job_response_hides_provider_error_text(monkeypatch, catalog_app):
    get_job = AsyncMock(return_value={
        "job_id": "job-a",
        "brand_id": "brand-a",
        "error": "httpx.ConnectError: provider.internal timed out",
        "results": [{"url": "https://example.com", "error": "provider API token rejected"}],
    })
    monkeypatch.setattr(catalog_service, "get_job", get_job)

    response = TestClient(catalog_app).get(
        "/api/v1/catalog/jobs/job-a",
        params={"brand_id": "brand-a-alias"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "provider.internal" not in str(body)
    assert "token rejected" not in str(body)
    assert body["error"] == "Catalog import failed. Review server logs for details."
