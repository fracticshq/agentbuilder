from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.catalog_service import _normalize_schema_org, _normalize_shopify, _normalize_woocommerce
from app.services.knowledge_service import KnowledgeService


def test_shopify_normalization_preserves_catalog_currency_before_fallback():
    items = _normalize_shopify(
        {
            "products": [
                {
                    "id": 1,
                    "title": "Trail Tee",
                    "variants": [
                        {"id": 11, "sku": "TEE-USD", "price": {"amount": "12.50", "currencyCode": "usd"}},
                    ],
                }
            ]
        },
        fallback_currency="INR",
    )

    assert items[0]["price"] == 1250
    assert items[0]["currency"] == "USD"
    assert items[0]["currency_source"] == "catalog"


def test_catalog_normalization_marks_missing_or_configured_currency():
    shopify_items = _normalize_shopify(
        {"products": [{"id": 1, "title": "Mystery Item", "variants": [{"id": 11, "price": "10"}]}]}
    )
    assert shopify_items[0]["currency"] is None
    assert shopify_items[0]["currency_source"] == "missing"

    woo_items = _normalize_woocommerce([{"id": 2, "name": "Mug", "price": "8"}], fallback_currency="eur")
    assert woo_items[0]["currency"] == "EUR"
    assert woo_items[0]["currency_source"] == "configured_default"

    schema_items = _normalize_schema_org({"@type": "Product", "name": "Poster", "offers": {"price": "5"}})
    assert schema_items[0]["currency"] is None
    assert schema_items[0]["currency_source"] == "missing"


class FakeUpsertCollection:
    def __init__(self):
        self.upserts = []

    async def update_one(self, query, update, upsert=False):
        self.upserts.append((query, update, upsert))


class ProductCurrencyKnowledgeService(KnowledgeService):
    def __init__(self):
        super().__init__(Settings(VECTOR_BACKEND="atlas"))
        self.collection = FakeUpsertCollection()

    async def _chunk_text(self, text, filename, agent_id=None):
        return [text]

    async def _generate_embeddings(self, texts):
        return [[0.1, 0.2] for _ in texts]


@pytest.mark.asyncio
async def test_product_knowledge_uses_configured_currency_only_when_missing():
    service = ProductCurrencyKnowledgeService()
    await service.job_store.set("job-123", {"status": "processing", "processed_chunks": 0})

    await service._process_product_item(
        SimpleNamespace(
            sku="SKU-1",
            name="Catalog Hat",
            price=1200,
            currency=None,
            category="Accessories",
            image_url=None,
            product_url=None,
            in_stock=True,
            features=[],
        ),
        "brand-1",
        "job-123",
        {"brand_id": "brand-1", "brand_slug": "brand-slug"},
        configured_default_currency="usd",
    )

    document = service.collection.upserts[0][1]["$set"]
    assert "Price: USD 1,200" in document["content"]
    assert document["product_data"]["currency"] == "USD"
    assert document["product_data"]["currency_source"] == "configured_default"


@pytest.mark.asyncio
async def test_product_knowledge_does_not_hardcode_currency_when_missing():
    service = ProductCurrencyKnowledgeService()
    await service.job_store.set("job-456", {"status": "processing", "processed_chunks": 0})

    await service._process_product_item(
        SimpleNamespace(
            sku="SKU-2",
            name="Catalog Pin",
            price=500,
            currency="",
            category="Accessories",
            image_url=None,
            product_url=None,
            in_stock=True,
            features=[],
        ),
        "brand-1",
        "job-456",
        {"brand_id": "brand-1", "brand_slug": "brand-slug"},
    )

    document = service.collection.upserts[0][1]["$set"]
    assert "Price: 500" in document["content"]
    assert "INR" not in document["content"]
    assert document["product_data"]["currency"] is None
    assert document["product_data"]["currency_source"] == "missing"
