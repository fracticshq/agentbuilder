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


def test_shopify_normalization_preserves_parent_and_multi_option_variant_metadata():
    items = _normalize_shopify(
        {
            "products": [
                {
                    "id": 991,
                    "handle": "denon-home-150-wireless-speaker-1",
                    "title": "Denon Home 150 Wireless Speaker",
                    "options": [{"name": "Color"}, {"name": "Finish"}],
                    "variants": [
                        {
                            "id": 49151795560721,
                            "sku": "DENON-BLK",
                            "title": "Black / Matte",
                            "option1": "Black",
                            "option2": "Matte",
                            "price": "41900.00",
                        },
                        {
                            "id": 49151800443153,
                            "sku": "DENON-WHT",
                            "title": "White / Gloss",
                            "option1": "White",
                            "option2": "Gloss",
                            "price": "41900.00",
                        },
                    ],
                }
            ]
        },
        base_url="https://soundtrails.in",
        fallback_currency="INR",
    )

    assert len(items) == 2
    assert items[0]["product_group_id"] == items[1]["product_group_id"] == "shopify:991"
    assert items[0]["parent_name"] == "Denon Home 150 Wireless Speaker"
    assert items[0]["has_variants"] is True
    assert items[0]["variant_count"] == 2
    assert items[0]["variant_options"] == {"Color": "Black", "Finish": "Matte"}
    assert items[1]["variant_options"] == {"Color": "White", "Finish": "Gloss"}
    assert items[0]["variant_url"].endswith("?variant=49151795560721")


def test_shopify_normalization_uses_variant_featured_images():
    items = _normalize_shopify(
        {
            "products": [
                {
                    "id": 991,
                    "handle": "denon-home-150-wireless-speaker-1",
                    "title": "Denon Home 150 Wireless Speaker",
                    "images": [
                        {"id": 1, "src": "https://cdn.example.com/black.jpg", "variant_ids": [49151795560721]},
                        {"id": 2, "src": "https://cdn.example.com/white-fallback.jpg", "variant_ids": [49151800443153]},
                    ],
                    "options": [{"name": "Colour"}],
                    "variants": [
                        {
                            "id": 49151795560721,
                            "sku": "DENON-BLK",
                            "title": "Black",
                            "option1": "Black",
                            "price": "41900.00",
                            "featured_image": {"src": "https://cdn.example.com/black-featured.jpg"},
                        },
                        {
                            "id": 49151800443153,
                            "sku": "DENON-WHT",
                            "title": "White",
                            "option1": "White",
                            "price": "41900.00",
                            "featured_image": {"src": "https://cdn.example.com/white-featured.jpg"},
                        },
                    ],
                }
            ]
        },
        base_url="https://soundtrails.in",
        fallback_currency="INR",
    )

    assert items[0]["image_url"] == "https://cdn.example.com/black-featured.jpg"
    assert items[1]["image_url"] == "https://cdn.example.com/white-featured.jpg"


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
