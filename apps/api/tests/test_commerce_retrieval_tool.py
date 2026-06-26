import pytest

from retrieval.types import DocumentChunk, RetrievalContext
from tools.builtin.retrieval_tool import CatalogSearchTool
from tools.commerce_retrieval import CommerceRetrievalPipeline


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def limit(self, _limit):
        return self

    async def to_list(self, length):
        return self.rows[:length]


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def find(self, query, projection):
        self.queries.append({"query": query, "projection": projection})
        return FakeCursor(self.rows)


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
    assert result.metadata["products"][0]["currency"] == "USD"
    assert result.metadata["products"][0]["currency_source"] == "commerce.default_currency"
    assert result.metadata["budget_filter"] == {"max_amount": 1000.0, "currency": "USD"}


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
