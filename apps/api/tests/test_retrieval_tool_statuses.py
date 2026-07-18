from types import SimpleNamespace

import pytest

from agent_runtime.orchestrator import Orchestrator, RETRIEVAL_UNAVAILABLE_MESSAGE
from retrieval.types import DocumentChunk, RetrievalContext
from tools.builtin.retrieval_tool import CatalogSearchTool, RetrievalTool
from tools.types import ToolResult


class FakeRetrievalPipeline:
    def __init__(self, context):
        self.context = context
        self.bm25_search = None
        self.vector_search = None

    async def retrieve(self, query, **_kwargs):
        return self.context


def retrieval_context(*, status, chunks=None, sources=None, reason=None, backend_status=None):
    metadata = {
        "status": status,
        "backend_status": backend_status or {},
    }
    if reason is not None:
        metadata["reason"] = reason
    return RetrievalContext(
        chunks=chunks or [],
        confidence=0.81 if chunks else 0.0,
        sources=sources or [],
        query="warranty",
        retrieval_metadata=metadata,
    )


def evidence_chunk():
    return DocumentChunk(
        chunk_id="warranty-1",
        doc_id="warranty-policy",
        content="The verified warranty is five years.",
        title="Warranty Policy",
        url="https://example.com/policies/warranty",
        score=0.81,
    )


@pytest.mark.asyncio
async def test_retrieval_tool_keeps_no_evidence_as_a_successful_grounded_result():
    context = retrieval_context(
        status="no_evidence",
        backend_status={
            "vector": {"status": "success"},
            "bm25": {"status": "success"},
        },
    )

    result = await RetrievalTool(FakeRetrievalPipeline(context)).run("missing policy")

    assert result.success is True
    assert "No verified information matched" in result.data
    assert result.metadata["sources"] == []
    assert result.metadata["retrieval"] == {
        "status": "no_evidence",
        "reason": None,
        "backend_status": {
            "vector": {"status": "success"},
            "bm25": {"status": "success"},
        },
        "successful_backends": ["vector", "bm25"],
        "failed_backends": [],
    }


@pytest.mark.asyncio
async def test_retrieval_tool_keeps_degraded_evidence_usable_and_explicit():
    context = retrieval_context(
        status="degraded",
        chunks=[evidence_chunk()],
        sources=["warranty-policy"],
        reason="partial_backend_failure",
        backend_status={
            "vector": {"status": "error", "reason": "backend_error"},
            "bm25": {"status": "success"},
        },
    )

    result = await RetrievalTool(FakeRetrievalPipeline(context)).run("warranty")

    assert result.success is True
    assert "verified warranty is five years" in result.data
    assert result.metadata["sources"] == ["warranty-policy"]
    assert result.metadata["citation_candidates"] == [{
        "doc_id": "warranty-policy",
        "title": "Warranty Policy",
        "url": "https://example.com/policies/warranty",
        "snippet": "The verified warranty is five years.",
    }]
    assert result.metadata["retrieval"]["status"] == "degraded"
    assert result.metadata["retrieval"]["failed_backends"] == ["vector"]


@pytest.mark.asyncio
async def test_retrieval_tool_does_not_present_degraded_empty_result_as_no_evidence():
    context = retrieval_context(
        status="degraded",
        reason="partial_backend_failure",
        backend_status={
            "vector": {"status": "unavailable", "reason": "authentication_failed"},
            "bm25": {"status": "success"},
        },
    )

    result = await RetrievalTool(FakeRetrievalPipeline(context)).run("warranty")

    assert result.success is True
    assert "partially unavailable" in result.data
    assert "No verified information matched" not in result.data
    assert result.metadata["retrieval"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_retrieval_tool_converts_outage_to_generic_retryable_failure():
    secret = "mongodb://admin:super-secret@provider"
    context = retrieval_context(
        status="error",
        reason=secret,
        backend_status={
            secret: {"status": "error", "reason": "backend_error"},
            "vector": {"status": "error", "reason": secret},
            "bm25": {"status": "unavailable", "reason": "backend_unavailable"},
        },
    )

    result = await RetrievalTool(FakeRetrievalPipeline(context)).run("warranty")

    assert result.success is False
    assert result.data is None
    assert result.error == "retrieval_unavailable_retryable"
    assert result.metadata["retryable"] is True
    assert result.metadata["retrieval"] == {
        "status": "error",
        "reason": "retrieval_error",
        "backend_status": {
            "vector": {"status": "error"},
            "bm25": {"status": "unavailable", "reason": "backend_unavailable"},
        },
        "successful_backends": [],
        "failed_backends": ["vector", "bm25"],
    }
    assert secret not in str(result)


@pytest.mark.asyncio
async def test_catalog_search_propagates_the_same_retrieval_outage_contract():
    context = retrieval_context(
        status="error",
        reason="no_search_backend_succeeded",
        backend_status={"vector": {"status": "error", "reason": "backend_error"}},
    )

    result = await CatalogSearchTool(FakeRetrievalPipeline(context)).run("speaker")

    assert result.success is False
    assert result.error == "retrieval_unavailable_retryable"
    assert result.metadata["retrieval"] == {
        "status": "error",
        "reason": "no_search_backend_succeeded",
        "backend_status": {"vector": {"status": "error", "reason": "backend_error"}},
        "successful_backends": [],
        "failed_backends": ["vector"],
    }


class FakeTools:
    def __init__(self, tool):
        self.tool = tool

    def get_tool_schemas(self):
        return [{"name": "knowledge_search"}]

    def get(self, name):
        return self.tool if name == "knowledge_search" else None


class StaticTool:
    def __init__(self, result):
        self.result = result

    async def run(self, **_kwargs):
        return self.result


class PlanningAndSynthesisLLM:
    def __init__(self, synthesis_response="Synthesized grounded answer"):
        self.synthesis_response = synthesis_response
        self.prompts = []

    async def generate(self, prompt):
        self.prompts.append(prompt)
        if "Planning Phase" in prompt:
            return SimpleNamespace(content='''{
                "goal": "answer safely",
                "steps": [{
                    "id": 1,
                    "thought": "retrieve verified context",
                    "tool_name": "knowledge_search",
                    "tool_input": {"query": "warranty"}
                }]
            }''')
        return SimpleNamespace(content=self.synthesis_response)


@pytest.mark.asyncio
async def test_orchestrator_returns_retry_message_instead_of_direct_answer_after_only_retrieval_outage():
    llm = PlanningAndSynthesisLLM()
    outage_result = ToolResult(
        success=False,
        data=None,
        error="retrieval_unavailable_retryable",
        metadata={
            "retrieval": {
                "status": "error",
                "reason": "no_search_backend_succeeded",
                "backend_status": {
                    "vector": {"status": "error", "reason": "backend_error"},
                },
                "successful_backends": [],
                "failed_backends": ["vector"],
            },
            "sources": [],
            "products": [],
        },
    )

    result = await Orchestrator(llm=llm, tools=FakeTools(StaticTool(outage_result))).run("What is the warranty?")

    assert result.answer == RETRIEVAL_UNAVAILABLE_MESSAGE
    assert result.metadata["fallback_stage"] == "retrieval_unavailable"
    assert result.metadata["retryable"] is True
    assert result.metadata["retrieval"] == outage_result.metadata["retrieval"]
    assert len(llm.prompts) == 1


@pytest.mark.asyncio
async def test_orchestrator_preserves_direct_catalog_grounding_when_rag_is_unavailable():
    llm = PlanningAndSynthesisLLM()
    catalog_result = ToolResult(
        success=True,
        data="Found catalog product: Verified Speaker.",
        metadata={
            "sources": [],
            "products": [{"sku": "SPK-1", "name": "Verified Speaker"}],
            "retrieval": {
                "status": "error",
                "reason": "no_search_backend_succeeded",
                "backend_status": {"vector": {"status": "error", "reason": "backend_error"}},
                "successful_backends": [],
                "failed_backends": ["vector"],
            },
        },
    )

    result = await Orchestrator(llm=llm, tools=FakeTools(StaticTool(catalog_result))).run("Show a speaker")

    assert result.answer == "Synthesized grounded answer"
    assert "fallback" not in result.metadata
    assert len(llm.prompts) == 2


@pytest.mark.asyncio
async def test_orchestrator_synthesizes_from_degraded_usable_retrieval_with_status_in_context():
    llm = PlanningAndSynthesisLLM()
    degraded_result = ToolResult(
        success=True,
        data="Found verified warranty policy: five years.",
        metadata={
            "sources": ["warranty-policy"],
            "chunks_count": 1,
            "retrieval": {
                "status": "degraded",
                "reason": "partial_backend_failure",
                "backend_status": {
                    "vector": {"status": "error", "reason": "backend_error"},
                    "bm25": {"status": "success"},
                },
                "successful_backends": ["bm25"],
                "failed_backends": ["vector"],
            },
        },
    )

    result = await Orchestrator(llm=llm, tools=FakeTools(StaticTool(degraded_result))).run("What is the warranty?")

    assert result.answer == "Synthesized grounded answer"
    assert "fallback" not in result.metadata
    assert '"status": "degraded"' in llm.prompts[-1]
