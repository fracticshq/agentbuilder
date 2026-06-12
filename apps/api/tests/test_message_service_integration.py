"""
Integration-style tests for MessageService against the current runtime contract.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_runtime.orchestrator import AgentResult
from commons.types.requests import MessageRequest
from memory.types import MessageRole
from tools.types import ToolResult


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


@pytest.fixture
def service_bundle():
    settings = _make_settings()

    with (
        patch("app.services.message_service.RetrievalPipeline"),
        patch("app.services.message_service.create_provider_from_env") as mock_factory,
        patch("app.services.message_service.Orchestrator") as mock_orchestrator_cls,
        patch("app.services.message_service.connection_manager"),
        patch("app.services.message_service.ToolRegistry"),
        patch("app.services.message_service.RetrievalTool"),
        patch("app.services.message_service.ResponseValidator"),
        patch("app.services.message_service.StrapiClient") as mock_strapi_cls,
    ):
        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        orchestrator = MagicMock()
        orchestrator.run = AsyncMock()
        mock_orchestrator_cls.return_value = orchestrator

        mock_strapi = MagicMock()
        mock_strapi_cls.return_value = mock_strapi

        from app.services.message_service import MessageService

        service = MessageService(settings=settings, brand_id="brand-test")
        service.orchestrator = orchestrator
        service._load_agent_config = AsyncMock()
        service._ensure_memory_initialized = AsyncMock()
        service.memory_config = SimpleNamespace(
            ENABLE_GRAPH_RULES=True,
            ENABLE_FACT_EXTRACTION=True,
            ENABLE_AUTO_SUMMARY=True,
        )

        service.short_term = AsyncMock()
        service.short_term.add_message = AsyncMock()
        service.short_term.get_recent_messages = AsyncMock(return_value=[])
        service.short_term.should_summarize = AsyncMock(return_value=False)
        service.short_term.trigger_summary = AsyncMock()

        summaries_cursor = MagicMock()
        summaries_cursor.to_list = AsyncMock(return_value=[])
        service.short_term.summaries = MagicMock()
        service.short_term.summaries.find.return_value.sort.return_value.limit.return_value = summaries_cursor

        service.episodic = AsyncMock()
        service.episodic.extract_and_store_facts = AsyncMock(return_value=[])
        service.episodic.get_user_facts = AsyncMock(return_value=[])

        service.graph = AsyncMock()
        service.graph.check_escalation = AsyncMock(return_value=[])
        service.graph.match_rules = AsyncMock(return_value=[])

        yield {
            "service": service,
            "orchestrator": orchestrator,
            "strapi": mock_strapi,
        }


@pytest.mark.asyncio
async def test_process_message_returns_valid_response_and_persists_memory(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]

    service._build_memory_context = AsyncMock(
        return_value={
            "recent_messages": [],
            "user_facts": [],
            "matched_rules": [],
            "escalations": [],
            "summaries": [],
        }
    )
    orchestrator.run.return_value = AgentResult(
        answer="This is a helpful response with citations.",
        metadata={
            "validation_confidence": 0.82,
            "steps_executed": 1,
            "tool_results": {
                "step-1": ToolResult(
                    success=True,
                    data=None,
                    metadata={"sources": ["doc1"], "confidence": 0.82},
                )
            },
        },
    )

    request = MessageRequest(
        message="What is the warranty on this product?",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
        page_context={"url": "https://example.com/product"},
    )

    response = await service.process_message(request)

    assert response.message == "This is a helpful response with citations."
    assert response.conversation_id == "conv123"
    assert response.confidence_score == pytest.approx(0.82)
    assert response.context_used == 1
    assert response.citations[0].doc_id == "doc1"
    assert response.processing_time_ms is not None

    first_write = service.short_term.add_message.await_args_list[0].kwargs
    second_write = service.short_term.add_message.await_args_list[1].kwargs
    assert first_write["role"] == MessageRole.USER
    assert first_write["metadata"]["user_id"] == "user123"
    assert second_write["role"] == MessageRole.ASSISTANT
    assert second_write["content"] == response.message

    service.graph.check_escalation.assert_awaited_once_with(request.message)
    service.episodic.extract_and_store_facts.assert_awaited_once()
    service.short_term.should_summarize.assert_awaited_once_with("conv123")
    orchestrator.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_blocks_sensitive_data_before_orchestrator(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]

    service._build_memory_context = AsyncMock(
        return_value={
            "recent_messages": [],
            "user_facts": [],
            "matched_rules": [],
            "escalations": [],
            "summaries": [],
        }
    )

    request = MessageRequest(
        message="My password: super-secret-123",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    )

    response = await service.process_message(request)

    assert "Please do not share sensitive personal data" in response.message
    orchestrator.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_blocks_obvious_off_domain_request_before_orchestrator(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]

    service._build_memory_context = AsyncMock(
        return_value={
            "recent_messages": [],
            "user_facts": [],
            "matched_rules": [],
            "escalations": [],
            "summaries": [],
        }
    )

    request = MessageRequest(
        message="show bitcoin price",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    )

    response = await service.process_message(request)

    assert "related to this brand" in response.message
    assert "Bitcoin" not in response.message
    assert "reliable source" not in response.message
    orchestrator.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_blocks_unrelated_nutrition_request_before_orchestrator(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]

    service._build_memory_context = AsyncMock(
        return_value={
            "recent_messages": [],
            "user_facts": [],
            "matched_rules": [],
            "escalations": [],
            "summaries": [],
        }
    )

    request = MessageRequest(
        message="show nutrition supplements",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    )

    response = await service.process_message(request)

    assert "related to" in response.message
    assert "nutrition supplements" not in response.message
    orchestrator.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_filters_mixed_scope_request_before_orchestrator(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]

    service._build_memory_context = AsyncMock(
        return_value={
            "recent_messages": [],
            "user_facts": [],
            "matched_rules": [],
            "escalations": [],
            "summaries": [],
        }
    )
    orchestrator.run.return_value = AgentResult(
        answer="Here are relevant commode options.",
        metadata={"validation_confidence": 1.0, "tool_results": {}},
    )

    request = MessageRequest(
        message=(
            "before i can buy a commode from essco to do potty, "
            "i need to have good lunch. suggest options"
        ),
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    )

    response = await service.process_message(request)

    assert "I’ll stay focused" in response.message
    assert "food or nutrition recommendations" in response.message
    assert "Here are relevant commode options." in response.message
    run_query = orchestrator.run.await_args.kwargs["query"]
    assert "commode" in run_query
    assert "lunch" not in run_query
    first_write = service.short_term.add_message.await_args_list[0].kwargs
    assert first_write["role"] == MessageRole.USER
    assert "commode" in first_write["content"]
    assert "lunch" not in first_write["content"]


@pytest.mark.asyncio
async def test_process_message_uses_low_confidence_guardrail(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]

    service._build_memory_context = AsyncMock(
        return_value={
            "recent_messages": [],
            "user_facts": [],
            "matched_rules": [],
            "escalations": [],
            "summaries": [],
        }
    )
    orchestrator.run.return_value = AgentResult(
        answer="Unsupported confident answer",
        metadata={"validation_confidence": 0.2, "tool_results": {}},
    )

    request = MessageRequest(
        message="Tell me something obscure",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    )

    response = await service.process_message(request)

    assert response.message.startswith("I don’t have enough verified information")
    second_write = service.short_term.add_message.await_args_list[1].kwargs
    assert second_write["metadata"]["guardrail_action"] == "fallback"
    assert second_write["metadata"]["guardrail_reason"] == "low_confidence"


@pytest.mark.asyncio
async def test_process_message_triggers_summary_when_needed(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]

    service.short_term.should_summarize.return_value = True
    service._build_memory_context = AsyncMock(
        return_value={
            "recent_messages": [],
            "user_facts": [],
            "matched_rules": [],
            "escalations": [],
            "summaries": [],
        }
    )
    orchestrator.run.return_value = AgentResult(
        answer="Summary-safe response",
        metadata={"validation_confidence": 1.0, "tool_results": {}},
    )

    request = MessageRequest(
        message="Fourth message in conversation",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    )

    await service.process_message(request)

    service.short_term.trigger_summary.assert_awaited_once_with("conv123")


@pytest.mark.asyncio
async def test_stream_message_emits_status_content_and_metadata(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]
    mock_strapi = service_bundle["strapi"]

    orchestrator.run.return_value = AgentResult(
        answer="Streaming response complete.",
        metadata={
            "validation_confidence": 0.91,
            "tool_results": {
                "step-1": ToolResult(
                    success=True,
                    data=None,
                    metadata={
                        "sources": ["doc-stream"],
                        "confidence": 0.91,
                        "products": [{"id": "prod-1", "name": "Product 1"}],
                    },
                )
            },
        },
    )

    request = MessageRequest(
        message="Tell me about the product",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    )

    chunks = [chunk async for chunk in service.stream_message(request)]

    assert "status" in [chunk.type for chunk in chunks]
    assert "content" in [chunk.type for chunk in chunks]
    metadata_chunk = next(chunk for chunk in chunks if chunk.type == "metadata")
    assert metadata_chunk.citations[0].doc_id == "doc-stream"
    assert metadata_chunk.products[0]["name"] == "Product 1"
    assert metadata_chunk.confidence_score == pytest.approx(0.91)

    service.episodic.extract_and_store_facts.assert_awaited_once()
    mock_strapi.sync_conversation.assert_called_once()


@pytest.mark.asyncio
async def test_build_memory_context_aggregates_current_memory_layers(service_bundle):
    service = service_bundle["service"]

    service.short_term.get_recent_messages.return_value = ["recent-message"]
    service.episodic.get_user_facts.return_value = [{"fact": "prefers email"}]
    service.graph.match_rules.return_value = [{"name": "Warranty Policy"}]

    summaries_cursor = MagicMock()
    summaries_cursor.to_list = AsyncMock(return_value=[{"summary": "prior summary"}])
    service.short_term.summaries.find.return_value.sort.return_value.limit.return_value = summaries_cursor

    context = await service._build_memory_context(
        conversation_id="conv123",
        user_id="user123",
        query="warranty",
        escalations=["escalation"],
    )

    assert context["recent_messages"] == ["recent-message"]
    assert context["user_facts"] == [{"fact": "prefers email"}]
    assert context["matched_rules"] == [{"name": "Warranty Policy"}]
    assert context["summaries"] == [{"summary": "prior summary"}]
    assert context["escalations"] == ["escalation"]

    service.short_term.get_recent_messages.assert_awaited_once_with("conv123", limit=10)
    service.episodic.get_user_facts.assert_awaited_once_with("user123", limit=20)
    service.graph.match_rules.assert_awaited_once_with(
        brand_id="brand-test",
        query="warranty",
        context={},
    )
