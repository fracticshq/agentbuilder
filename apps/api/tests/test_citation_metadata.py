"""Public citation and retrieval-health response contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_runtime.orchestrator import AgentResult
from commons.types.requests import MessageRequest
from tools.types import ToolResult

from app.services.message_service import (
    _extract_tool_result_metadata,
    _response_retrieval_health,
)


def _retrieval_health(*, status: str, reason=None, backend_status=None) -> dict:
    return {
        "status": status,
        "reason": reason,
        "backend_status": backend_status or {},
        # These are deliberately ignored and recalculated by the service.
        "successful_backends": ["untrusted-provider"],
        "failed_backends": ["untrusted-provider"],
    }


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.DEFAULT_LLM_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    settings.OPENAI_MODEL = "gpt-4o-mini"
    settings.QWEN_API_KEY = ""
    settings.QWEN_MODEL = "qwen-max"
    settings.STRAPI_URL = "http://localhost:1337"
    settings.STRAPI_API_TOKEN = ""
    settings.CONFIDENCE_THRESHOLD = 0.7
    return settings


class _StaticOrchestrator:
    """A signature-preserving orchestrator double for the streaming path."""

    def __init__(self):
        self.result = None
        self.calls = []

    async def run(self, query, context, chat_history=None, on_event=None):
        self.calls.append({"query": query, "context": context, "chat_history": chat_history})
        return self.result


@pytest.fixture
def message_service():
    with (
        patch("app.services.message_service.RetrievalPipeline"),
        patch("app.services.message_service.create_provider_from_env"),
        patch("app.services.message_service.connection_manager"),
        patch("app.services.message_service.ToolRegistry"),
        patch("app.services.message_service.RetrievalTool"),
        patch("app.services.message_service.ResponseValidator"),
        patch("app.services.message_service.StrapiClient"),
    ):
        from app.services.message_service import MessageService

        service = MessageService(settings=_make_settings(), brand_id="brand-test")
        service.agent_config = {"features": {"conversation_memory": False}}
        service._load_agent_config = AsyncMock()
        service._ensure_memory_initialized = AsyncMock()
        service._build_memory_context = AsyncMock(return_value={})
        service.memory_config = SimpleNamespace(
            ENABLE_GRAPH_RULES=False,
            ENABLE_FACT_EXTRACTION=False,
            ENABLE_AUTO_SUMMARY=False,
        )
        service.observability = SimpleNamespace(track_event=AsyncMock())
        service.strapi = MagicMock()
        service.orchestrator = _StaticOrchestrator()
        yield service


def test_extract_tool_result_metadata_prefers_bounded_candidates_and_deduplicates():
    secret = "api_key=not-for-clients"
    citations, products, dealers = _extract_tool_result_metadata({
        "knowledge_search": ToolResult(
            success=True,
            data=None,
            metadata={
                "confidence": 0.67,
                "citation_candidates": [
                    {
                        "doc_id": "warranty-policy",
                        "title": "Warranty Policy",
                        "url": f"https://example.com/policies/warranty?{secret}",
                        "snippet": "  Verified five-year coverage.  ",
                        "confidence": 0.82,
                        "content": "large raw body that must never become a citation",
                    },
                    {
                        "doc_id": "secret-source",
                        "title": "Secret Source",
                        "url": "javascript:alert(1)",
                        "snippet": f"token: {secret}",
                    },
                ],
                "sources": [
                    {"doc_id": "warranty-policy", "title": "Legacy warranty title"},
                    "legacy-source",
                ],
                "products": [{"id": "product-1"}],
                "dealers": [{"id": "dealer-1"}],
            },
        ),
    })

    assert citations == [
        {
            "doc_id": "warranty-policy",
            "title": "Warranty Policy",
            "url": "https://example.com/policies/warranty",
            "snippet": "Verified five-year coverage.",
            "confidence": pytest.approx(0.82),
        },
        {
            "doc_id": "secret-source",
            "title": "Secret Source",
            "url": None,
            "snippet": None,
            "confidence": pytest.approx(0.67),
        },
        {
            "doc_id": "legacy-source",
            "title": "legacy-source",
            "url": None,
            "snippet": None,
            "confidence": pytest.approx(0.67),
        },
    ]
    assert products == [{"id": "product-1"}]
    assert dealers == [{"id": "dealer-1"}]
    assert secret not in str(citations)
    assert "large raw body" not in str(citations)


def test_retrieval_health_allowlists_status_reason_and_backend_details():
    secret = "mongodb://admin:super-secret@provider"
    tool_results = {
        "knowledge_search": ToolResult(
            success=False,
            data=None,
            metadata={
                "retrieval": _retrieval_health(
                    status="error",
                    reason=secret,
                    backend_status={
                        "vector": {"status": "error", "reason": secret},
                        "bm25": {"status": "unavailable", "reason": "backend_unavailable"},
                        "provider-name-and-secret": {"status": "error", "reason": "backend_error"},
                    },
                )
            },
        )
    }

    assert _response_retrieval_health(tool_results) == {
        "status": "error",
        "reason": "retrieval_error",
        "backend_status": {
            "vector": {"status": "error"},
            "bm25": {"status": "unavailable", "reason": "backend_unavailable"},
        },
        "successful_backends": [],
        "failed_backends": ["vector", "bm25"],
    }
    assert secret not in str(_response_retrieval_health(tool_results))

    no_evidence = _response_retrieval_health({
        "knowledge_search": ToolResult(
            success=True,
            data=None,
            metadata={
                "retrieval": _retrieval_health(
                    status="no_evidence",
                    backend_status={"vector": {"status": "success"}},
                )
            },
        )
    })
    assert no_evidence["status"] == "no_evidence"
    assert no_evidence["reason"] is None


@pytest.mark.asyncio
async def test_sync_and_stream_responses_include_safe_citations_and_retrieval_health(message_service):
    retrieval = _retrieval_health(
        status="degraded",
        reason="partial_backend_failure",
        backend_status={
            "vector": {"status": "error", "reason": "backend_error"},
            "bm25": {"status": "success"},
        },
    )
    tool_result = ToolResult(
        success=True,
        data=None,
        metadata={
            "confidence": 0.81,
            "sources": ["warranty-policy"],
            "citation_candidates": [{
                "doc_id": "warranty-policy",
                "title": "Warranty Policy",
                "url": "https://example.com/policies/warranty",
                "snippet": "The verified warranty is five years.",
            }],
            "retrieval": retrieval,
        },
    )
    message_service.orchestrator.result = AgentResult(
        answer="The verified warranty is five years.",
        metadata={
            "validation_confidence": 0.81,
            "tool_results": {"knowledge_search": tool_result},
        },
    )
    request = MessageRequest(
        message="What is the warranty?",
        user_id="user-1",
        agent_id="agent-1",
        conversation_id="conversation-1",
    )

    response = await message_service.process_message(request)

    expected_health = {
        "status": "degraded",
        "reason": "partial_backend_failure",
        "backend_status": {
            "vector": {"status": "error", "reason": "backend_error"},
            "bm25": {"status": "success"},
        },
        "successful_backends": ["bm25"],
        "failed_backends": ["vector"],
    }
    assert response.metadata["retrieval"] == expected_health
    assert response.citations[0].model_dump() == {
        "doc_id": "warranty-policy",
        "title": "Warranty Policy",
        "url": "https://example.com/policies/warranty",
        "confidence": 0.81,
        "snippet": "The verified warranty is five years.",
    }

    chunks = [chunk async for chunk in message_service.stream_message(request)]
    metadata_chunk = next(chunk for chunk in chunks if chunk.type == "metadata")
    done_chunk = next(chunk for chunk in chunks if chunk.type == "done")
    final_answer_chunk = next(chunk for chunk in chunks if chunk.type == "final_answer")

    assert metadata_chunk.metadata["retrieval"] == expected_health
    assert done_chunk.metadata["retrieval"] == expected_health
    assert final_answer_chunk.metadata["retrieval"] == expected_health
    assert metadata_chunk.citations[0].snippet == "The verified warranty is five years."
