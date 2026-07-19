import re

import pytest

from retrieval.types import DocumentChunk, RetrievalContext
from tools.builtin.retrieval_tool import CatalogSearchTool
from tools.commerce_retrieval import CommerceRetrievalPipeline


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self._index = 0

    def limit(self, _limit):
        return self

    async def to_list(self, length):
        return self.rows[:length]

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self.rows):
            raise StopAsyncIteration
        row = self.rows[self._index]
        self._index += 1
        return row


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def find(self, query, projection=None):
        self.queries.append({"query": query, "projection": projection})
        return FakeCursor([row for row in self.rows if self._matches(row, query)])

    def _matches(self, row, query):
        for key, expected in query.items():
            if key == "$or":
                if not any(self._matches(row, branch) for branch in expected):
                    return False
                continue
            actual = self._get_value(row, key)
            if isinstance(expected, dict):
                if "$in" in expected:
                    if actual not in expected["$in"]:
                        return False
                if "$gt" in expected and not (actual is not None and actual > expected["$gt"]):
                    return False
                if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
                    return False
                if "$regex" in expected:
                    flags = re.IGNORECASE if expected.get("$options") == "i" else 0
                    if actual is None or not re.search(expected["$regex"], str(actual), flags):
                        return False
            elif actual != expected:
                return False
        return True

    @staticmethod
    def _get_value(row, key):
        value = row
        for part in key.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value


class FakeSearchBackend:
    def __init__(self, collection):
        self.collection = collection


class FakeRetrievalPipeline:
    def __init__(self, *, rows=None, chunks=None):
        self.bm25_search = FakeSearchBackend(FakeCollection(rows or []))
        self.vector_search = None
        self.chunks = chunks or []
        self.queries = []

    async def retrieve(self, query, **kwargs):
        self.queries.append({"query": query, **kwargs})
        return RetrievalContext(
            chunks=self.chunks,
            confidence=0.72 if self.chunks else 0.0,
            sources=["retrieval-doc"] if self.chunks else [],
            query=query,
        )


def product_row(**product_data):
    return {
        "content_type": "product",
        "title": product_data.get("name"),
        "content": product_data.get("description", ""),
        "doc_id": product_data.get("sku", "doc"),
        "product_data": product_data,
    }


def product_chunk(**product_data):
    return DocumentChunk(
        chunk_id=f"{product_data.get('sku')}-chunk",
        doc_id=f"{product_data.get('sku')}-doc",
        content=product_data.get("description") or product_data.get("name") or "",
        content_type="product",
        product_data=product_data,
        score=0.8,
    )


def commerce_config():
    return {
        "default_currency": "usd",
        "currency_policy": "catalog_first_config_fallback",
        "taxonomy": {
            "category_field": "category",
            "product_type_field": "product_type",
            "tags_field": "tags",
            "categories": {
                "speaker": {
                    "aliases": ["speakers", "bookshelf speaker"],
                    "exclusions": ["cable"],
                }
            },
        },
    }


def test_parse_intent_handles_suffix_budgets_and_configured_currency():
    pipeline = CommerceRetrievalPipeline(FakeRetrievalPipeline(), commerce_config())

    intent = pipeline.parse_intent("show speakers 100k")

    assert intent.budget_max == 100000
    assert intent.budget_currency == "USD"
    assert intent.product_type == "speaker"
    assert "bookshelf speaker" in intent.expanded_terms


@pytest.mark.asyncio
async def test_catalog_search_normalizes_missing_currency_from_config():
    tool = CatalogSearchTool(
        FakeRetrievalPipeline(
            rows=[
                product_row(
                    sku="SPK-1",
                    name="Bookshelf Speaker",
                    product_type="speaker",
                    category="Speakers",
                    price=999,
                    currency="",
                )
            ]
        )
    )

    result = await tool.run(
        query="bookshelf speaker under $1k",
        pagination={"limit": 3},
        commerce_config=commerce_config(),
    )

    assert result.success is True
    assert "Bookshelf Speaker - USD 9.99" in result.data
    assert result.metadata["products"][0]["currency"] == "USD"
    assert result.metadata["products"][0]["currency_source"] == "commerce.default_currency"
    assert result.metadata["budget_filter"] == {"max_amount": 1000.0, "currency": "USD"}


@pytest.mark.asyncio
async def test_catalog_search_excludes_deactivated_shopify_products_from_direct_and_rag_results():
    retrieval = FakeRetrievalPipeline(
        rows=[
            product_row(
                sku="STALE-1",
                name="Deleted Speaker",
                product_type="speaker",
                category="Speakers",
                price=999,
                source_active=False,
            )
        ],
        chunks=[
            product_chunk(
                sku="STALE-1",
                name="Deleted Speaker",
                product_type="speaker",
                category="Speakers",
                price=999,
                source_active=False,
            )
        ],
    )
    tool = CatalogSearchTool(retrieval)

    result = await tool.run(query="bookshelf speaker", commerce_config=commerce_config())

    assert result.success is True
    assert result.metadata["products"] == []
    assert any(
        query["query"].get("product_data.source_active") == {"$ne": False}
        for query in retrieval.bm25_search.collection.queries
    )


@pytest.mark.asyncio
async def test_catalog_search_honors_default_only_currency_policy():
    tool = CatalogSearchTool(
        FakeRetrievalPipeline(
            rows=[
                product_row(
                    sku="SPK-1",
                    name="Bookshelf Speaker",
                    product_type="speaker",
                    category="Speakers",
                    price=999,
                    currency="USD",
                )
            ]
        )
    )

    config = {
        **commerce_config(),
        "default_currency": "inr",
        "currency_policy": "default_only",
    }

    result = await tool.run(query="bookshelf speaker", commerce_config=config)

    assert "Bookshelf Speaker - INR 9.99" in result.data
    assert result.metadata["products"][0]["currency"] == "INR"
    assert result.metadata["products"][0]["currency_source"] == "commerce.default_currency"


@pytest.mark.asyncio
async def test_catalog_search_honors_catalog_only_currency_policy():
    tool = CatalogSearchTool(
        FakeRetrievalPipeline(
            rows=[
                product_row(
                    sku="SPK-1",
                    name="Bookshelf Speaker",
                    product_type="speaker",
                    category="Speakers",
                    price=999,
                    currency="",
                )
            ]
        )
    )

    config = {
        **commerce_config(),
        "default_currency": "inr",
        "currency_policy": "catalog_only",
    }

    result = await tool.run(query="bookshelf speaker", commerce_config=config)

    assert "Bookshelf Speaker - 9.99" in result.data
    assert result.metadata["products"][0]["currency"] is None
    assert result.metadata["products"][0]["currency_source"] == "missing"


@pytest.mark.asyncio
async def test_catalog_search_fuses_direct_and_retrieval_products_by_identity():
    tool = CatalogSearchTool(
        FakeRetrievalPipeline(
            rows=[
                product_row(
                    sku="SPK-1",
                    name="Bookshelf Speaker",
                    product_type="speaker",
                    category="Speakers",
                    price=999,
                    currency="USD",
                )
            ],
            chunks=[
                product_chunk(
                    sku="SPK-1",
                    name="Bookshelf Speaker",
                    product_type="speaker",
                    category="Speakers",
                    price=999,
                    currency="USD",
                )
            ],
        )
    )

    result = await tool.run(query="bookshelf speaker", commerce_config=commerce_config())

    assert [product["sku"] for product in result.metadata["products"]] == ["SPK-1"]
    assert result.metadata["products"][0]["ranker_sources"] == ["direct_catalog", "retrieval"]
    assert result.metadata["retrieval_diagnostics"]["rankers"] == {
        "direct_catalog": 1,
        "retrieval_products": 1,
    }


@pytest.mark.asyncio
async def test_catalog_search_groups_variants_into_one_product_card():
    tool = CatalogSearchTool(
        FakeRetrievalPipeline(
            rows=[
                product_row(
                    sku="DENON-BLK",
                    name="Denon Home 150 Wireless Speaker - Black",
                    parent_name="Denon Home 150 Wireless Speaker",
                    product_group_id="shopify:denon-home-150",
                    variant_id="gid://shopify/ProductVariant/black",
                    variant_sku="DENON-BLK",
                    variant_title="Black",
                    variant_options={"Color": "Black"},
                    product_type="speaker",
                    category="General",
                    price=4190000,
                    currency="INR",
                    product_url="https://soundtrails.in/products/denon-home-150-wireless-speaker-1",
                    variant_url="https://soundtrails.in/products/denon-home-150-wireless-speaker-1?variant=49151795560721",
                ),
                product_row(
                    sku="DENON-WHT",
                    name="Denon Home 150 Wireless Speaker - White",
                    parent_name="Denon Home 150 Wireless Speaker",
                    product_group_id="shopify:denon-home-150",
                    variant_id="gid://shopify/ProductVariant/white",
                    variant_sku="DENON-WHT",
                    variant_title="White",
                    variant_options={"Color": "White"},
                    product_type="speaker",
                    category="General",
                    price=4190000,
                    currency="INR",
                    product_url="https://soundtrails.in/products/denon-home-150-wireless-speaker-1",
                    variant_url="https://soundtrails.in/products/denon-home-150-wireless-speaker-1?variant=49151800443153",
                ),
            ]
        )
    )

    result = await tool.run(query="denon home speaker", commerce_config=commerce_config())

    assert len(result.metadata["products"]) == 1
    product = result.metadata["products"][0]
    assert product["name"] == "Denon Home 150 Wireless Speaker"
    assert product["product_group_id"] == "shopify:denon-home-150"
    assert product["variant_count"] == 2
    assert [variant["variant_options"]["Color"] for variant in product["variants"]] == ["Black", "White"]
    assert "2 variants" in result.data


@pytest.mark.asyncio
async def test_catalog_search_hydrates_all_sibling_variants_after_group_selection():
    pipeline = FakeRetrievalPipeline(
        rows=[
            product_row(
                sku="DENON-BLK",
                name="Denon Home 150 Wireless Speaker - Black",
                parent_name="Denon Home 150 Wireless Speaker",
                product_group_id="shopify:denon-home-150",
                variant_id="black",
                variant_sku="DENON-BLK",
                variant_options={"Colour": "Black"},
                product_type="speaker",
                category="General",
                price=4190000,
                currency="INR",
                product_url="https://example.com/products/denon-home-150",
                variant_url="https://example.com/products/denon-home-150?variant=black",
            ),
            product_row(
                sku="DENON-WHT",
                name="Denon Home 150 Wireless Speaker - White",
                parent_name="Denon Home 150 Wireless Speaker",
                product_group_id="shopify:denon-home-150",
                variant_id="white",
                variant_sku="DENON-WHT",
                variant_options={"Colour": "White"},
                product_type="speaker",
                category="General",
                price=4290000,
                currency="INR",
                product_url="https://example.com/products/denon-home-150",
                variant_url="https://example.com/products/denon-home-150?variant=white",
            ),
        ]
    )
    tool = CatalogSearchTool(pipeline)

    result = await tool.run(query="speaker under ₹42000", commerce_config=commerce_config())

    assert len(result.metadata["products"]) == 1
    product = result.metadata["products"][0]
    assert product["sku"] == "DENON-BLK"
    assert product["variant_count"] == 1
    assert [variant["variant_sku"] for variant in product["variants"]] == ["DENON-BLK"]
    assert product["variants"][0]["is_default"] is True
    assert product["price_min"] == 4190000
    assert product["price_max"] == 4190000
    assert any(query["query"].get("product_data.product_group_id") == "shopify:denon-home-150" for query in pipeline.bm25_search.collection.queries)


@pytest.mark.asyncio
async def test_catalog_search_hydrates_siblings_by_handle_when_group_id_is_missing():
    pipeline = FakeRetrievalPipeline(
        rows=[
            product_row(
                sku="WHEY-STRAW-2",
                name="Whey Protein - Strawberry / 2 lb",
                parent_name="Whey Protein",
                handle="whey-protein",
                variant_id="strawberry-2",
                variant_sku="WHEY-STRAW-2",
                variant_options={"Flavour": "Strawberry", "Weight": "2 lb"},
                product_type="protein",
                category="Nutrition",
                price=549900,
                currency="INR",
                product_url="https://example.com/products/whey-protein",
            ),
            product_row(
                sku="WHEY-VAN-5",
                name="Whey Protein - Vanilla / 5 lb",
                parent_name="Whey Protein",
                handle="whey-protein",
                variant_id="vanilla-5",
                variant_sku="WHEY-VAN-5",
                variant_options={"Flavour": "Vanilla", "Weight": "5 lb"},
                product_type="protein",
                category="Nutrition",
                price=899900,
                currency="INR",
                product_url="https://example.com/products/whey-protein",
            ),
        ]
    )
    tool = CatalogSearchTool(pipeline)

    result = await tool.run(query="protein under ₹6000", commerce_config=commerce_config())

    product = result.metadata["products"][0]
    assert [variant["variant_options"] for variant in product["variants"]] == [
        {"Flavour": "Strawberry", "Weight": "2 lb"},
    ]
    assert any(query["query"].get("product_data.handle") == "whey-protein" for query in pipeline.bm25_search.collection.queries)


@pytest.mark.asyncio
async def test_catalog_search_selects_matching_option_variant_first():
    tool = CatalogSearchTool(
        FakeRetrievalPipeline(
            rows=[
                product_row(
                    sku="DENON-BLK",
                    name="Denon Home 150 Wireless Speaker - Black",
                    product_group_id="shopify:denon-home-150",
                    variant_id="black",
                    variant_options={"Color": "Black"},
                    product_type="speaker",
                    category="General",
                    price=4190000,
                    currency="INR",
                    product_url="https://soundtrails.in/products/denon-home-150-wireless-speaker-1",
                ),
                product_row(
                    sku="DENON-WHT",
                    name="Denon Home 150 Wireless Speaker - White",
                    product_group_id="shopify:denon-home-150",
                    variant_id="white",
                    variant_options={"Color": "White"},
                    product_type="speaker",
                    category="General",
                    price=4190000,
                    currency="INR",
                    product_url="https://soundtrails.in/products/denon-home-150-wireless-speaker-1",
                ),
            ]
        )
    )

    result = await tool.run(query="black denon home speaker", commerce_config=commerce_config())

    product = result.metadata["products"][0]
    assert product["variant_id"] == "black"
    assert product["variants"][0]["variant_options"]["Color"] == "Black"


@pytest.mark.asyncio
async def test_catalog_search_returns_no_exact_matches_for_invalid_top_set():
    tool = CatalogSearchTool(
        FakeRetrievalPipeline(
            rows=[
                product_row(
                    sku="CBL-1",
                    name="Speaker Cable",
                    product_type="accessory",
                    category="Cables",
                    price=2500,
                    currency="USD",
                )
            ],
            chunks=[
                product_chunk(
                    sku="AMP-1",
                    name="Integrated Amplifier",
                    product_type="amplifier",
                    category="Amplifiers",
                    price=1500,
                    currency="USD",
                )
            ],
        )
    )

    result = await tool.run(query="speaker under $1k", commerce_config=commerce_config())

    assert result.success is True
    assert result.metadata["products"] == []
    assert result.data == "No exact matching catalog products found."
    assert result.metadata["confidence"] == 0.0
