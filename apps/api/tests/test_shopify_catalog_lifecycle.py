"""P5 regressions for durable Shopify catalog and webhook lifecycle handling."""

from __future__ import annotations

import base64
import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1.endpoints import catalog as catalog_endpoint
from app.config import Settings
from app.services import catalog_service
from app.services.catalog_sync_store import CatalogSyncStore
from app.services.knowledge_service import KnowledgeService
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.catalog_sync_scheduler import schedule_due_shopify_syncs
from app.workers import catalog_sync_worker


class _WebhookRequest:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self._body = body
        self.headers = headers

    async def body(self) -> bytes:
        return self._body


class _Brands:
    def __init__(self, brand: dict):
        self.brand = brand
        self.updates: list[tuple[dict, dict]] = []

    async def find_one(self, _query):
        return dict(self.brand)

    async def update_one(self, query, update):
        self.updates.append((query, update))


class _WebhookStore:
    def __init__(self):
        self.sync_calls: list[dict] = []
        self.action_calls: list[dict] = []

    async def enqueue_sync(self, **kwargs):
        self.sync_calls.append(kwargs)
        return ({"job_id": kwargs["job_id"], "status": "queued"}, False)

    async def enqueue_lifecycle_action(self, **kwargs):
        self.action_calls.append(kwargs)
        return ({"job_id": kwargs["job_id"], "status": "queued"}, False)


def _signed_webhook(body: bytes, *, topic: str, webhook_id: str = "event-1") -> _WebhookRequest:
    secret = b"test-webhook-secret"
    signature = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode("ascii")
    return _WebhookRequest(
        body,
        {
            "x-shopify-hmac-sha256": signature,
            "x-shopify-shop-domain": "store.myshopify.com",
            "x-shopify-topic": topic,
            "x-shopify-webhook-id": webhook_id,
        },
    )


def _webhook_settings():
    return SimpleNamespace(
        SHOPIFY_WEBHOOKS_ENABLED=True,
        SHOPIFY_WEBHOOK_SECRET="test-webhook-secret",
        SHOPIFY_WEBHOOK_MAX_BODY_BYTES=1_048_576,
    )


@pytest.mark.asyncio
async def test_signed_product_delete_webhook_queues_brand_scoped_deactivation(monkeypatch):
    brands = _Brands(
        {
            "id": "brand-a",
            "slug": "brand-a-slug",
            "catalog_sync": {
                "source_type": "shopify",
                "source_url": "https://store.myshopify.com",
                "shop_domain": "store.myshopify.com",
                "access_token_encrypted": "encrypted-token",
                "enabled": True,
            },
        }
    )
    monkeypatch.setattr(catalog_endpoint.connection_manager, "get_system_db", lambda: SimpleNamespace(brands=brands))
    store = _WebhookStore()

    response = await catalog_endpoint.receive_shopify_webhook(
        _signed_webhook(b'{"id": 99}', topic="products/delete"),
        settings=_webhook_settings(),
        catalog_sync_store=store,
    )

    assert response["status"] == "accepted"
    assert len(store.action_calls) == 1
    action = store.action_calls[0]
    assert action["brand_id"] == "brand-a"
    assert action["source_url"] == "https://store.myshopify.com"
    assert action["action"] == "deactivate_product"
    assert action["product_id"] == "99"
    assert action["idempotency_key"] == "shopify:webhook:store.myshopify.com:event-1"


@pytest.mark.asyncio
async def test_invalid_webhook_signature_is_rejected_before_brand_lookup(monkeypatch):
    monkeypatch.setattr(catalog_endpoint.connection_manager, "get_system_db", lambda: (_ for _ in ()).throw(AssertionError("must not read brand")))
    request = _WebhookRequest(
        b'{"id": 99}',
        {
            "x-shopify-hmac-sha256": "bad",
            "x-shopify-shop-domain": "store.myshopify.com",
            "x-shopify-topic": "products/delete",
        },
    )

    with pytest.raises(Exception) as error:
        await catalog_endpoint.receive_shopify_webhook(
            request,
            settings=_webhook_settings(),
            catalog_sync_store=_WebhookStore(),
        )
    assert getattr(error.value, "status_code", None) == 401


@pytest.mark.asyncio
async def test_uninstall_webhook_revokes_credential_then_queues_source_deactivation(monkeypatch):
    brands = _Brands(
        {
            "id": "brand-a",
            "slug": "brand-a-slug",
            "catalog_sync": {
                "source_type": "shopify",
                "source_url": "https://store.myshopify.com",
                "shop_domain": "store.myshopify.com",
                "access_token_encrypted": "encrypted-token",
                "enabled": True,
            },
        }
    )
    monkeypatch.setattr(catalog_endpoint.connection_manager, "get_system_db", lambda: SimpleNamespace(brands=brands))
    store = _WebhookStore()

    response = await catalog_endpoint.receive_shopify_webhook(
        _signed_webhook(b'{"id": 99}', topic="app/uninstalled"),
        settings=_webhook_settings(),
        catalog_sync_store=store,
    )

    assert response["status"] == "accepted"
    assert brands.updates[0][1]["$set"]["catalog_sync.enabled"] is False
    assert "catalog_sync.access_token_encrypted" in brands.updates[0][1]["$unset"]
    assert store.action_calls[0]["action"] == "deactivate_source"


@pytest.mark.asyncio
async def test_catalog_worker_decrypts_only_the_encrypted_job_snapshot(monkeypatch):
    settings = Settings(SECRET_KEY="test-secret", SETTINGS_ENCRYPTION_KEY="settings-key")
    encrypted = RuntimeSettingsService(settings)._encrypt("shpat_snapshot_only")
    job = {
        "job_id": "catalog-job-1",
        "brand_id": "brand-a",
        "source_url": "https://store.myshopify.com",
        "access_token_encrypted": encrypted,
        "fallback_currency": "USD",
        "action": "sync",
        "lease_token": "lease-1",
    }
    store = SimpleNamespace(
        claim_next=AsyncMock(return_value=job),
        complete=AsyncMock(return_value=True),
        fail=AsyncMock(return_value=True),
        renew_lease=AsyncMock(return_value=True),
    )
    fetch = AsyncMock()
    monkeypatch.setattr(catalog_service, "fetch_shopify_products", fetch)
    monkeypatch.setattr(
        catalog_service,
        "get_job",
        AsyncMock(return_value={"status": "completed", "counts": {"products_upserted": 2}}),
    )

    assert await catalog_sync_worker.run_once(store, settings, identifier="worker-a") is True
    assert fetch.await_args.args[1] == "shpat_snapshot_only"
    assert store.complete.await_args.args[1]["counts"]["products_upserted"] == 2
    store.fail.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalog_store_renews_only_its_current_lease_token(monkeypatch):
    class _Collection:
        def __init__(self):
            self.calls = []

        async def update_one(self, query, update):
            self.calls.append((query, update))
            return SimpleNamespace(matched_count=1)

    collection = _Collection()
    store = CatalogSyncStore(Settings(SECRET_KEY="test-secret"))
    monkeypatch.setattr(store, "_collection", lambda: collection)

    assert await store.renew_lease({"job_id": "catalog-job-1", "lease_token": "lease-a"}) is True
    assert collection.calls[0][0]["lease_token"] == "lease-a"
    assert collection.calls[0][0]["status"] == "running"


@pytest.mark.asyncio
async def test_catalog_store_returns_lease_token_only_to_the_claimed_worker(monkeypatch):
    class _Collection:
        async def find_one_and_update(self, *_args, **_kwargs):
            return {"_id": "catalog-job-lease", "job_id": "catalog-job-lease", "lease_token": "private-lease"}

    collection = _Collection()
    store = CatalogSyncStore(Settings(SECRET_KEY="test-secret"))
    store._indexes_checked = True
    monkeypatch.setattr(catalog_sync_worker.connection_manager, "get_system_db", lambda: {"catalog_sync_jobs": collection})

    job = await store.claim_next(worker_id="worker-a")

    assert job["lease_token"] == "private-lease"


@pytest.mark.asyncio
async def test_auto_sync_scheduler_queues_due_brand_through_the_same_store(monkeypatch):
    class _Cursor:
        def __init__(self, rows):
            self.rows = iter(rows)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.rows)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class _Brands:
        def find(self, _query):
            return _Cursor([
                {
                    "id": "brand-a",
                    "slug": "brand-a-slug",
                    "catalog_sync": {
                        "source_type": "shopify",
                        "source_url": "https://store.myshopify.com",
                        "access_token_encrypted": "encrypted-token",
                        "auto_sync": True,
                        "sync_frequency": "daily",
                    },
                }
            ])

    store = SimpleNamespace(
        enqueue_sync=AsyncMock(return_value=({"job_id": "scheduled-job"}, False)),
        cancel_queued=AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.catalog_sync_scheduler.connection_manager.get_system_db",
        lambda: SimpleNamespace(brands=_Brands()),
    )
    monkeypatch.setattr(catalog_service, "create_job", AsyncMock())

    assert await schedule_due_shopify_syncs(store, Settings(SECRET_KEY="test-secret")) == 1
    assert store.enqueue_sync.await_args.kwargs["trigger"] == "scheduled_sync"
    assert catalog_service.create_job.await_args.args[2] == "brand-a"


@pytest.mark.asyncio
async def test_deactivation_marks_shopify_source_inactive_without_deleting_audit_rows():
    class _Collection:
        def __init__(self):
            self.query = None
            self.update = None

        async def update_many(self, query, update):
            self.query = query
            self.update = update
            return SimpleNamespace(modified_count=3)

    service = KnowledgeService(Settings(SECRET_KEY="test-secret"))
    service.collection = _Collection()
    service._ensure_connection = AsyncMock()

    changed = await service.deactivate_shopify_catalog(
        "brand-a",
        source_url="https://store.myshopify.com",
        product_id="99",
        reason="shopify_product_deleted",
    )

    assert changed == 3
    assert service.collection.query["metadata.catalog_source.source_url"] == "https://store.myshopify.com"
    assert service.collection.update["$set"]["metadata.catalog_source.active"] is False
    assert service.collection.update["$set"]["product_data.in_stock"] is False
