from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.catalog_service import (
    _fetch_shopify_default_currency,
    _normalize_schema_org,
    _normalize_shopify,
    _normalize_woocommerce,
    normalize_authenticated_shopify_store_url,
    normalize_currency_code,
    normalize_shopify_store_url,
)
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


def test_shopify_store_currency_is_authoritative_and_identity_is_stable():
    payload = {
        "products": [{
            "id": 44,
            "handle": "linen-shirt",
            "title": "Linen Shirt",
            "variants": [{"id": 99, "sku": "LINEN-M", "price": "12.50", "currency": "USD"}],
        }]
    }

    first = _normalize_shopify(payload, base_url="https://celavilifestyle.com", shopify_currency="INR", fallback_currency="EUR")
    second = _normalize_shopify(payload, base_url="https://celavilifestyle.com", shopify_currency="INR", fallback_currency="EUR")

    assert first[0]["currency"] == "INR"
    assert first[0]["currency_source"] == "shopify_store"
    assert first[0]["source_key"] == second[0]["source_key"] == "shopify:44:99"
    assert first[0]["price"] == 1250
    assert first[0]["price_unit"] == "minor"


def test_shopify_url_and_explicit_currency_validation():
    assert normalize_shopify_store_url("celavilifestyle.com") == "https://celavilifestyle.com"
    assert normalize_shopify_store_url("https://store.myshopify.com/") == "https://store.myshopify.com"
    assert normalize_currency_code(" inr ") == "INR"
    with pytest.raises(ValueError):
        normalize_shopify_store_url("https://celavilifestyle.com/products")
    for private_url in (
        "http://localhost",
        "http://127.0.0.1",
        "http://10.0.0.8",
        "http://169.254.169.254",
        "http://[::1]",
        "http://shop.internal",
    ):
        with pytest.raises(ValueError):
            normalize_shopify_store_url(private_url)
    with pytest.raises(ValueError):
        normalize_currency_code("USDOLLAR")

    assert normalize_authenticated_shopify_store_url("https://store.myshopify.com") == "https://store.myshopify.com"
    for unsafe_authenticated_store in (
        "http://store.myshopify.com",
        "https://store.myshopify.com:8443",
        "https://celavilifestyle.com",
    ):
        with pytest.raises(ValueError):
            normalize_authenticated_shopify_store_url(unsafe_authenticated_store)


@pytest.mark.asyncio
async def test_authenticated_shopify_store_currency_success_and_failure():
    class Response:
        def __init__(self, status_code, payload, headers=None):
            self.status_code = status_code
            self._payload = payload
            self.headers = headers or {}
            self.is_redirect = status_code in {301, 302, 303, 307, 308}

        def json(self):
            return self._payload

    class Client:
        def __init__(self, response):
            self.response = response
            self.calls = []

        async def get(self, url, headers):
            self.calls.append((url, headers))
            return self.response

    class SequenceClient:
        def __init__(self, responses):
            self.responses = iter(responses)
            self.calls = []

        async def get(self, url, headers):
            self.calls.append((url, headers))
            return next(self.responses)

    client = Client(Response(200, {"shop": {"currency": "inr"}}))
    assert await _fetch_shopify_default_currency(client, "https://celavilifestyle.myshopify.com", {"X-Shopify-Access-Token": "secret"}) == "INR"
    assert client.calls[0][0].endswith("/admin/api/2024-01/shop.json")

    redirected = SequenceClient([
        Response(302, {}, {"location": "/admin/api/2024-01/shop.json?redirected=true"}),
        Response(200, {"shop": {"currency": "GBP"}}),
    ])
    assert await _fetch_shopify_default_currency(redirected, "https://celavilifestyle.myshopify.com", {"X-Shopify-Access-Token": "secret"}) == "GBP"
    assert len(redirected.calls) == 2

    unsafe_redirect = SequenceClient([
        Response(302, {}, {"location": "http://127.0.0.1/admin/api/2024-01/shop.json"}),
        Response(200, {"shop": {"currency": "GBP"}}),
    ])
    assert await _fetch_shopify_default_currency(unsafe_redirect, "https://celavilifestyle.myshopify.com", {"X-Shopify-Access-Token": "secret"}) is None
    assert len(unsafe_redirect.calls) == 1

    cross_store_redirect = SequenceClient([
        Response(302, {}, {"location": "https://another-store.myshopify.com/admin/api/2024-01/shop.json"}),
        Response(200, {"shop": {"currency": "GBP"}}),
    ])
    assert await _fetch_shopify_default_currency(cross_store_redirect, "https://celavilifestyle.myshopify.com", {"X-Shopify-Access-Token": "secret"}) is None
    assert len(cross_store_redirect.calls) == 1

    failed = Client(Response(403, {}))
    assert await _fetch_shopify_default_currency(failed, "https://celavilifestyle.myshopify.com", {"X-Shopify-Access-Token": "secret"}) is None

    public = Client(Response(200, {"shop": {"currency": "USD"}}))
    assert await _fetch_shopify_default_currency(public, "https://celavilifestyle.com", {}) is None
    assert public.calls == []


class FakeUpsertCollection:
    def __init__(self):
        self.upserts = []
        self.update_many_calls = []

    async def update_one(self, query, update, upsert=False):
        self.upserts.append((query, update, upsert))

    async def update_many(self, query, update):
        self.update_many_calls.append((query, update))
        return SimpleNamespace(modified_count=2)


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


@pytest.mark.asyncio
async def test_shopify_sync_uses_source_identity_and_marks_only_source_rows_inactive():
    service = ProductCurrencyKnowledgeService()

    async def no_connection(_brand_id):
        return None

    async def scope(_identifier):
        return {"brand_id": "brand-1", "brand_slug": "brand-slug", "aliases": ["brand-1", "brand-slug"]}

    service._ensure_connection = no_connection
    service._resolve_brand_scope = scope
    await service.job_store.set("source-job", {"status": "pending"})

    await service.sync_shopify_catalog(
        "knowledge-job",
        [SimpleNamespace(
            sku="LINEN-M",
            name="Linen Shirt",
            price=1250,
            price_unit="minor",
            currency="INR",
            currency_source="shopify_store",
            category="Shirts",
            image_url=None,
            product_url="https://celavilifestyle.com/products/linen-shirt",
            in_stock=True,
            features=[],
            source_type="shopify",
            source_product_id="44",
            source_variant_id="99",
            source_key="shopify:44:99",
        )],
        "brand-1",
        source_url="https://celavilifestyle.com",
        source_job_id="source-job",
    )

    query, document, upsert = service.collection.upserts[0]
    assert query["doc_id"] == "brand-1_product_shopify:44:99"
    assert upsert is True
    assert document["$set"]["metadata"]["catalog_source"]["source_key"] == "shopify:44:99"
    assert document["$set"]["product_data"]["currency_source"] == "shopify_store"
    assert document["$set"]["product_data"]["price_unit"] == "minor"
    assert "Price: INR 12.50" in document["$set"]["content"]
    stale_query, stale_update = service.collection.update_many_calls[0]
    assert stale_query["metadata.catalog_source.type"] == "shopify"
    assert stale_query["metadata.catalog_source.source_key"] == {"$nin": ["shopify:44:99"]}
    assert stale_update["$set"]["product_data.in_stock"] is False
