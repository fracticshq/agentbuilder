import asyncio

import pytest

from retrieval.pipeline import RetrievalPipeline
from retrieval.types import DocumentChunk, RetrievalConfig, SearchResult


class FakeSearch:
    def __init__(self, name, events, chunks=None):
        self.name = name
        self.events = events
        self.chunks = chunks

    async def search(self, query, **_kwargs):
        self.events.append(f"{self.name}:start")
        await asyncio.sleep(0.01)
        self.events.append(f"{self.name}:end")
        return SearchResult(
            chunks=self.chunks or [
                DocumentChunk(
                    chunk_id=f"{self.name}-chunk",
                    doc_id=f"{self.name}-doc",
                    content=f"{self.name} result for {query}",
                    score=1.0,
                )
            ],
            total_found=1,
            query=query,
            search_type=self.name,
        )


class FakeFusion:
    def fuse(self, search_results, top_k):
        chunks = []
        for result in search_results:
            chunks.extend(result.chunks)
        return chunks[:top_k]


class RecordingReranker:
    def __init__(self):
        self.input_chunks = None

    async def rerank(self, query, chunks, top_k):
        self.input_chunks = chunks
        return chunks[:top_k]


def build_pipeline(**config_overrides):
    pipeline = RetrievalPipeline.__new__(RetrievalPipeline)
    config = {
        "vector_enabled": True,
        "bm25_enabled": True,
        "vector_top_k": 10,
        "bm25_top_k": 10,
        "rerank_enabled": False,
        "dedup_enabled": False,
        "brand_boost_enabled": False,
        "page_boost_enabled": False,
    }
    config.update(config_overrides)
    pipeline.config = RetrievalConfig(**config)
    pipeline.rrf = FakeFusion()
    pipeline.reranker = None
    pipeline.brand_boost = None
    pipeline.page_boost = None
    return pipeline


@pytest.mark.asyncio
async def test_retrieval_runs_vector_and_bm25_concurrently():
    events = []
    pipeline = build_pipeline()
    pipeline.vector_search = FakeSearch("vector", events)
    pipeline.bm25_search = FakeSearch("bm25", events)

    result = await pipeline.retrieve("pillar cock", max_chunks=10)

    assert len(result.chunks) == 2
    assert events.index("bm25:start") < events.index("vector:end")


def test_deduplicate_uses_structured_product_identity_before_doc_id():
    pipeline = build_pipeline()
    chunks = [
        DocumentChunk(
            chunk_id="vector-product",
            doc_id="vector-doc",
            content="Product: Towel Rail 600mm Long",
            content_type="product",
            metadata={"product_data": {"sku": "AEC-CHR-1111N"}},
            score=0.9,
        ),
        DocumentChunk(
            chunk_id="bm25-product",
            doc_id="bm25-doc",
            content="Towel Rail 600mm Long SKU AEC-CHR-1111N",
            content_type="product",
            metadata={"sku": " aec-chr-1111n "},
            score=0.8,
        ),
        DocumentChunk(
            chunk_id="different-product",
            doc_id="other-doc",
            content="Product: Towel Ring",
            content_type="product",
            metadata={"product_data": {"sku": "AEC-CHR-1121N"}},
            score=0.7,
        ),
    ]

    deduplicated = pipeline._deduplicate(chunks)

    assert [chunk.chunk_id for chunk in deduplicated] == ["vector-product", "different-product"]


@pytest.mark.asyncio
async def test_deduplication_happens_before_reranking():
    events = []
    duplicate_a = DocumentChunk(
        chunk_id="duplicate-a",
        doc_id="vector-doc",
        content="Product: Towel Rail",
        content_type="product",
        metadata={"product_data": {"sku": "AEC-CHR-1111N"}},
        score=1.0,
    )
    duplicate_b = DocumentChunk(
        chunk_id="duplicate-b",
        doc_id="bm25-doc",
        content="Towel Rail SKU AEC-CHR-1111N",
        content_type="product",
        metadata={"sku": "AEC-CHR-1111N"},
        score=0.95,
    )
    unique = DocumentChunk(
        chunk_id="unique",
        doc_id="unique-doc",
        content="Product: Towel Ring",
        content_type="product",
        metadata={"product_data": {"sku": "AEC-CHR-1121N"}},
        score=0.8,
    )

    reranker = RecordingReranker()
    pipeline = build_pipeline(rerank_enabled=True, dedup_enabled=True)
    pipeline.vector_search = FakeSearch("vector", events, [duplicate_a, unique])
    pipeline.bm25_search = FakeSearch("bm25", events, [duplicate_b])
    pipeline.reranker = reranker

    await pipeline.retrieve("towel rack", max_chunks=1)

    assert [chunk.chunk_id for chunk in reranker.input_chunks] == ["duplicate-a", "unique"]
