"""P5 GraphQL Admin catalog-read regression coverage."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app.services import catalog_service


class _Response:
    status_code = 200
    is_redirect = False
    headers: dict[str, str] = {}

    def __init__(self, body: dict):
        self.body = body

    def json(self):
        return self.body

    def raise_for_status(self):
        return None


class _GraphQLClient:
    def __init__(self):
        self.calls: list[tuple[str, dict, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, headers, json):
        self.calls.append((url, headers, json))
        query = json["query"]
        variables = json["variables"]
        if "ShopCurrency" in query:
            return _Response({"data": {"shop": {"currencyCode": "USD"}}})
        if "CatalogProductVariants" in query:
            assert variables == {"productId": "gid://shopify/Product/44", "after": "variants-1", "first": 100}
            return _Response(
                {
                    "data": {
                        "product": {
                            "variants": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [_variant("100", "L")],
                            }
                        }
                    }
                }
            )
        assert variables == {"after": None, "first": 10}
        return _Response(
            {
                "data": {
                    "products": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "gid://shopify/Product/44",
                                "legacyResourceId": "44",
                                "title": "Linen Shirt",
                                "handle": "linen-shirt",
                                "productType": "Shirts",
                                "vendor": "NOVA",
                                "tags": ["linen"],
                                "options": [{"name": "Size", "position": 1}],
                                "featuredImage": {"url": "https://cdn.example.com/shirt.jpg"},
                                "variants": {
                                    "pageInfo": {"hasNextPage": True, "endCursor": "variants-1"},
                                    "nodes": [_variant("99", "M")],
                                },
                            }
                        ],
                    }
                }
            }
        )


def _variant(identifier: str, size: str) -> dict:
    return {
        "id": f"gid://shopify/ProductVariant/{identifier}",
        "legacyResourceId": identifier,
        "sku": f"LINEN-{size}",
        "title": size,
        "price": {"amount": "12.50", "currencyCode": "USD"},
        "inventoryQuantity": 0,
        "inventoryPolicy": "CONTINUE",
        "image": {"url": f"https://cdn.example.com/shirt-{size.lower()}.jpg"},
        "selectedOptions": [{"name": "Size", "value": size}],
    }


class _Jobs:
    def __init__(self):
        self.jobs = {"sync-1": {"job_id": "sync-1", "status": "queued"}}

    async def get(self, job_id):
        return deepcopy(self.jobs.get(job_id))

    async def update(self, job_id, updates):
        self.jobs.setdefault(job_id, {}).update(deepcopy(updates))


@pytest.mark.asyncio
async def test_shopify_sync_reads_only_graphql_and_exhausts_variant_pages(monkeypatch):
    jobs = _Jobs()
    client = _GraphQLClient()
    upsert = AsyncMock(
        return_value={
            "products_seen": 2,
            "products_upserted": 2,
            "products_marked_inactive": 0,
            "error_count": 0,
        }
    )
    monkeypatch.setattr(catalog_service, "_job_store", jobs)
    monkeypatch.setattr(catalog_service.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(catalog_service, "_upsert_shopify_catalog_into_knowledge", upsert)
    monkeypatch.setattr(catalog_service, "_update_brand_sync_state", AsyncMock())

    await catalog_service.fetch_shopify_products(
        "https://store.myshopify.com",
        "shpat_test",
        "sync-1",
        brand_id="brand-1",
    )

    assert jobs.jobs["sync-1"]["status"] == "completed"
    items = upsert.await_args.args[1]
    assert [item["source_key"] for item in items] == ["shopify:44:99", "shopify:44:100"]
    assert all(item["currency"] == "USD" for item in items)
    assert all(item["in_stock"] is True for item in items)
    assert all(url.endswith("/admin/api/2026-04/graphql.json") for url, _, _ in client.calls)
    assert all("products.json" not in url and "shop.json" not in url for url, _, _ in client.calls)


@pytest.mark.asyncio
async def test_graphql_errors_fail_the_snapshot_before_catalog_publish(monkeypatch):
    jobs = _Jobs()

    class ErrorClient(_GraphQLClient):
        async def post(self, url, *, headers, json):
            self.calls.append((url, headers, json))
            return _Response({"errors": [{"extensions": {"code": "ACCESS_DENIED"}}]})

    client = ErrorClient()
    upsert = AsyncMock()
    monkeypatch.setattr(catalog_service, "_job_store", jobs)
    monkeypatch.setattr(catalog_service.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(catalog_service, "_upsert_shopify_catalog_into_knowledge", upsert)
    monkeypatch.setattr(catalog_service, "_update_brand_sync_state", AsyncMock())

    await catalog_service.fetch_shopify_products(
        "https://store.myshopify.com",
        "shpat_test",
        "sync-1",
        brand_id="brand-1",
    )

    assert jobs.jobs["sync-1"]["status"] == "error"
    assert jobs.jobs["sync-1"]["error"] == "shopify_graphql_query_failed"
    upsert.assert_not_awaited()
