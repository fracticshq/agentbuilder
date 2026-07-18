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
        chunks = self.chunks if self.chunks is not None else [
            DocumentChunk(
                chunk_id=f"{self.name}-chunk",
                doc_id=f"{self.name}-doc",
                content=f"{self.name} result for {query}",
                score=1.0,
            )
        ]
        return SearchResult(
            chunks=chunks,
            total_found=len(chunks),
            query=query,
            search_type=self.name,
        )


class FailingSearch:
    def __init__(self, error_message="connection failed"):
        self.error_message = error_message

    async def search(self, *_args, **_kwargs):
        raise RuntimeError(self.error_message)


class UnavailableSearch:
    async def search(self, query, **_kwargs):
        return SearchResult(
            chunks=[],
            total_found=0,
            query=query,
            search_type="vector",
            backend_status="unavailable",
            backend_reason="authentication_failed",
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
    assert result.retrieval_metadata["status"] == "evidence"
    assert result.retrieval_metadata["search_methods"] == ["vector", "bm25"]
    assert set(result.sources) == {"vector-doc", "bm25-doc"}


@pytest.mark.asyncio
async def test_successful_empty_searches_report_no_evidence():
    events = []
    pipeline = build_pipeline()
    pipeline.vector_search = FakeSearch("vector", events, chunks=[])
    pipeline.bm25_search = FakeSearch("bm25", events, chunks=[])

    result = await pipeline.retrieve("unmatched query")

    assert result.chunks == []
    assert result.sources == []
    assert result.retrieval_metadata["status"] == "no_evidence"
    assert result.retrieval_metadata["backend_status"] == {
        "vector": {"status": "success"},
        "bm25": {"status": "success"},
    }
    assert result.retrieval_metadata["failed_backends"] == []
    assert result.retrieval_metadata["total_candidates"] == 0


@pytest.mark.asyncio
async def test_partial_backend_exception_reports_degraded_not_no_evidence():
    pipeline = build_pipeline()
    pipeline.vector_search = FailingSearch("mongodb://admin:super-secret@host unavailable")
    pipeline.bm25_search = FakeSearch("bm25", [], chunks=[])

    result = await pipeline.retrieve("unmatched query")

    assert result.chunks == []
    assert result.retrieval_metadata["status"] == "degraded"
    assert result.retrieval_metadata["backend_status"]["vector"] == {
        "status": "error",
        "reason": "backend_error",
    }
    assert result.retrieval_metadata["successful_backends"] == ["bm25"]
    assert result.retrieval_metadata["failed_backends"] == ["vector"]
    assert "super-secret" not in str(result.retrieval_metadata)


@pytest.mark.asyncio
async def test_unavailable_backend_result_reports_degraded_not_no_evidence():
    pipeline = build_pipeline()
    pipeline.vector_search = UnavailableSearch()
    pipeline.bm25_search = FakeSearch("bm25", [], chunks=[])

    result = await pipeline.retrieve("unmatched query")

    assert result.chunks == []
    assert result.retrieval_metadata["status"] == "degraded"
    assert result.retrieval_metadata["backend_status"]["vector"] == {
        "status": "unavailable",
        "reason": "authentication_failed",
    }
    assert result.retrieval_metadata["failed_backends"] == ["vector"]


@pytest.mark.asyncio
async def test_all_backend_exceptions_report_error_not_no_evidence():
    pipeline = build_pipeline()
    pipeline.vector_search = FailingSearch("vector-key=super-secret")
    pipeline.bm25_search = FailingSearch("mongo-password=super-secret")

    result = await pipeline.retrieve("unmatched query")

    assert result.chunks == []
    assert result.retrieval_metadata["status"] == "error"
    assert result.retrieval_metadata["reason"] == "no_search_backend_succeeded"
    assert result.retrieval_metadata["successful_backends"] == []
    assert result.retrieval_metadata["failed_backends"] == ["vector", "bm25"]
    assert "super-secret" not in str(result.retrieval_metadata)


@pytest.mark.asyncio
async def test_unavailable_configured_backends_report_error_not_no_evidence():
    pipeline = build_pipeline()
    pipeline.vector_search = None
    pipeline.bm25_search = None

    result = await pipeline.retrieve("unmatched query")

    assert result.chunks == []
    assert result.retrieval_metadata["status"] == "error"
    assert result.retrieval_metadata["backend_status"] == {
        "vector": {"status": "unavailable", "reason": "backend_unavailable"},
        "bm25": {"status": "unavailable", "reason": "backend_unavailable"},
    }
    assert result.retrieval_metadata["failed_backends"] == ["vector", "bm25"]


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
