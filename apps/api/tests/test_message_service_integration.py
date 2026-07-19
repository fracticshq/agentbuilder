"""
Integration-style tests for MessageService against the current runtime contract.
"""

import json

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


def _empty_memory_context() -> dict:
    return {
        "recent_messages": [],
        "user_facts": [],
        "matched_rules": [],
        "escalations": [],
        "summaries": [],
    }


def test_commerce_response_preparation_groups_flat_url_sibling_variants():
    from app.services.message_service import _prepare_commerce_products_for_response

    products = [
        {
            "sku": "49151795560721",
            "id": "49151795560721",
            "name": "Denon Home 150 - Wireless Speaker – Black",
            "price": 4190000,
            "currency": "INR",
            "product_url": "https://example.com/products/denon-home-150-wireless-speaker-1",
            "image_url": "https://example.com/black.jpg",
            "in_stock": True,
        },
        {
            "sku": "49151800443153",
            "id": "49151800443153",
            "name": "Denon Home 150 - Wireless Speaker – White",
            "price": 4190000,
            "currency": "INR",
            "product_url": "https://example.com/products/denon-home-150-wireless-speaker-1",
            "image_url": "https://example.com/white.jpg",
            "in_stock": True,
        },
    ]

    grouped = _prepare_commerce_products_for_response(
        products,
        {
            "commerce": {
                "default_currency": "INR",
                "currency_policy": "catalog_first_config_fallback",
            }
        },
    )

    assert len(grouped) == 1
    assert grouped[0]["name"] == "Denon Home 150 - Wireless Speaker"
    assert grouped[0]["variant_count"] == 2
    assert grouped[0]["variants"][0]["variant_options"] == {"Variant": "Black"}
    assert grouped[0]["variants"][1]["variant_options"] == {"Variant": "White"}


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

        async def granted_when_configured(**_kwargs):
            return service._long_term_memory_enabled()

        service._long_term_memory_consent_granted = granted_when_configured

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
    service.agent_config = {"memory": {"long_term": {"enabled": True}}}

    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
    service.short_term.get_recent_messages.return_value = [
        SimpleNamespace(role=MessageRole.USER, content="Earlier question", metadata={}),
        SimpleNamespace(role=MessageRole.ASSISTANT, content="Earlier answer", metadata={"cart_id": "cart-1"}),
    ]
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
    run_kwargs = orchestrator.run.await_args.kwargs
    assert [entry["role"] for entry in run_kwargs["chat_history"]] == ["user", "assistant"]
    assert run_kwargs["context"]["session_state"]["cart_id"] == "cart-1"


@pytest.mark.asyncio
async def test_process_message_returns_products_dealers_and_suppresses_commerce_citations(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]
    mock_strapi = service_bundle["strapi"]
    service.agent_config = {
        "data_source": "shopify",
        "commerce": {
            "default_currency": "INR",
            "currency_policy": "default_only",
            "display_policy": {"cards_only": True},
        },
    }

    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
    product = {"sku": "SPK-1", "name": "Bookshelf Speaker", "price": 999, "currency": "USD"}
    dealer = {"dealer_id": "DLR-1", "name": "Downtown Audio"}
    orchestrator.run.return_value = AgentResult(
        answer="Here is the matching product.",
        metadata={
            "validation_confidence": 0.94,
            "steps_executed": 1,
            "tool_results": {
                "catalog": ToolResult(
                    success=True,
                    data=None,
                    metadata={
                        "sources": ["internal-catalog-source"],
                        "confidence": 0.94,
                        "products": [product, {**product}],
                        "dealers": [dealer, {**dealer}],
                    },
                )
            },
        },
    )

    request = MessageRequest(
        message="show speakers",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    )

    response = await service.process_message(request)

    assert response.citations == []
    expected_product = {
        **product,
        "currency": "INR",
        "currency_source": "commerce.default_currency",
        "price_minor": 999,
        "price_unit": "minor",
        "image_url": None,
        "product_url": None,
    }
    assert response.products == [expected_product]
    assert response.dealers == [dealer]
    assert response.metadata is not None
    strapi_metadata = mock_strapi.sync_conversation.call_args.kwargs["assistant_metadata"]
    assert strapi_metadata["products"] == [expected_product]
    assert strapi_metadata["dealers"] == [dealer]


@pytest.mark.asyncio
async def test_process_message_blocks_sensitive_data_before_orchestrator(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]

    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())

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

    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())

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

    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())

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
    service.agent_config = {"domain": {"verticals": ["bathware"]}}

    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
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
    assert "I don’t have enough verified information" in response.message
    assert "Here are relevant commode options." not in response.message
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

    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
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
async def test_process_message_keeps_supported_claim_and_removes_private_evidence_annotation(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]
    service.observability.track_event = AsyncMock()
    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
    orchestrator.run.return_value = AgentResult(
        answer="The warranty coverage is 2 years. [evidence: warranty-terms-v1]",
        metadata={
            "validation_confidence": 0.92,
            "tool_results": {
                "knowledge": ToolResult(
                    success=True,
                    data="Warranty coverage is 2 years from the original purchase date.",
                    metadata={},
                )
            },
        },
    )

    response = await service.process_message(
        MessageRequest(message="What is the warranty?", user_id="user123", agent_id="agent-123", conversation_id="conv123")
    )

    assert response.message == "The warranty coverage is 2 years."
    assert "evidence:" not in response.message.lower()
    assert "warranty-terms-v1" not in response.message


@pytest.mark.asyncio
async def test_process_message_replaces_unsupported_factual_claim_with_safe_fallback(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]
    service.observability.track_event = AsyncMock()
    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
    orchestrator.run.return_value = AgentResult(
        answer="The warranty coverage is 3 years.",
        metadata={
            "validation_confidence": 0.92,
            "tool_results": {
                "knowledge": ToolResult(
                    success=True,
                    data="Warranty coverage is 2 years from the original purchase date.",
                    metadata={},
                )
            },
        },
    )

    response = await service.process_message(
        MessageRequest(message="What is the warranty?", user_id="user123", agent_id="agent-123", conversation_id="conv123")
    )

    assert response.message.startswith("I don’t have enough verified information")
    assert "3 years" not in response.message
    assistant_write = service.short_term.add_message.await_args_list[-1].kwargs
    assert assistant_write["metadata"]["guardrail_reason"] == "claim_evidence"
    assert assistant_write["metadata"]["evidence_validation"]["unsupported_claim_count"] == 1


@pytest.mark.asyncio
async def test_process_message_allows_structured_commerce_price_and_stock_without_citations(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]
    service.observability.track_event = AsyncMock()
    service.agent_config = {
        "data_source": "shopify",
        "commerce": {"default_currency": "INR", "currency_policy": "catalog_first_config_fallback"},
    }
    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
    product = {"sku": "SPK-1", "name": "Bookshelf Speaker", "price": 999, "currency": "INR", "in_stock": True}
    orchestrator.run.return_value = AgentResult(
        answer="Bookshelf Speaker costs ₹999 and is in stock.",
        metadata={
            "validation_confidence": 0.92,
            "tool_results": {"catalog": ToolResult(success=True, data=None, metadata={"products": [product]})},
        },
    )

    response = await service.process_message(
        MessageRequest(message="Tell me about the Bookshelf Speaker", user_id="user123", agent_id="agent-123", conversation_id="conv123")
    )

    assert response.message == "Bookshelf Speaker costs ₹999 and is in stock."
    assert response.citations == []
    assert response.products[0]["name"] == "Bookshelf Speaker"


@pytest.mark.asyncio
async def test_stream_replaces_unsupported_lalkitab_remedy_without_private_context_leak(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]
    service.observability.track_event = AsyncMock()
    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
    agent_result = AgentResult(
        answer="Your remedy is to donate copper every Sunday.",
        metadata={
            "lalkitab_runtime": True,
            "validation_passed": True,
            "validation_confidence": 1.0,
            "tool_results": {},
            "lalkitab_api_context_full": {
                "normalized_birth_input": {"date": "1987-07-16", "time": "15:26:00", "latitude": 28.6139},
                "chart_context": {"ascendant": "Aries"},
            },
        },
    )
    async def run_orchestrator(query, context, chat_history=None, on_event=None):
        return agent_result

    orchestrator.run = run_orchestrator

    chunks = [
        chunk
        async for chunk in service.stream_message(
            MessageRequest(message="Give me a remedy", user_id="user123", agent_id="agent-123", conversation_id="conv123")
        )
    ]

    public_payload = json.dumps([chunk.model_dump(mode="json") for chunk in chunks], ensure_ascii=False)
    assert "I can’t verify that Lal Kitab interpretation or remedy" in public_payload
    assert "donate copper" not in public_payload
    assert "1987-07-16" not in public_payload
    assert "15:26:00" not in public_payload
    assert "28.6139" not in public_payload


@pytest.mark.asyncio
async def test_stream_keeps_supported_claim_and_never_emits_private_evidence_annotation(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]
    service.observability.track_event = AsyncMock()
    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
    agent_result = AgentResult(
        answer="The warranty coverage is 2 years. [source: warranty-terms-v1]",
        metadata={
            "validation_confidence": 0.92,
            "tool_results": {
                "knowledge": ToolResult(
                    success=True,
                    data="Warranty coverage is 2 years from the original purchase date.",
                    metadata={},
                )
            },
        },
    )
    async def run_orchestrator(query, context, chat_history=None, on_event=None):
        return agent_result

    orchestrator.run = run_orchestrator

    chunks = [
        chunk
        async for chunk in service.stream_message(
            MessageRequest(message="What is the warranty?", user_id="user123", agent_id="agent-123", conversation_id="conv123")
        )
    ]

    public_content = "".join(chunk.content for chunk in chunks if chunk.type in {"content", "final_answer"})
    final_answer = next(chunk.content for chunk in chunks if chunk.type == "final_answer")
    assert final_answer == "The warranty coverage is 2 years."
    assert "source:" not in public_content.lower()
    assert "warranty-terms-v1" not in public_content


@pytest.mark.asyncio
async def test_process_message_triggers_summary_when_needed(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]

    service.short_term.should_summarize.return_value = True
    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
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
    service.agent_config = {"memory": {"long_term": {"enabled": True}}}

    async def run_orchestrator(query, context, chat_history=None, on_event=None):
        return AgentResult(
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

    orchestrator.run = run_orchestrator

    request = MessageRequest(
        message="Tell me about the product",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    )

    chunks = [chunk async for chunk in service.stream_message(request)]

    assert "activity" in [chunk.type for chunk in chunks]
    assert "content" in [chunk.type for chunk in chunks]
    metadata_chunk = next(chunk for chunk in chunks if chunk.type == "metadata")
    assert metadata_chunk.citations[0].doc_id == "doc-stream"
    assert metadata_chunk.products[0]["name"] == "Product 1"
    assert metadata_chunk.confidence_score == pytest.approx(0.91)

    service.episodic.extract_and_store_facts.assert_awaited_once()
    mock_strapi.sync_conversation.assert_called_once()


@pytest.mark.asyncio
async def test_stream_message_suppresses_commerce_source_activity(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]
    mock_strapi = service_bundle["strapi"]
    service.agent_config = {
        "data_source": "shopify",
        "commerce": {
            "default_currency": "INR",
            "currency_policy": "default_only",
            "display_policy": {"cards_only": True},
        },
    }

    async def run_orchestrator(query, context, chat_history=None, on_event=None):
        return AgentResult(
            answer="Here is the matching product.",
            metadata={
                "validation_confidence": 0.91,
                "tool_results": {
                    "catalog": ToolResult(
                        success=True,
                        data=None,
                        metadata={
                            "sources": ["internal-catalog-source"],
                            "confidence": 0.91,
                            "products": [{"id": "prod-1", "name": "Product 1", "currency": "USD"}],
                        },
                    )
                },
            },
        )

    orchestrator.run = run_orchestrator

    request = MessageRequest(
        message="show speakers",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    )

    chunks = [chunk async for chunk in service.stream_message(request)]

    tool_chunk = next(chunk for chunk in chunks if chunk.type == "tool_result")
    assert "source" not in tool_chunk.content.lower()
    assert tool_chunk.products[0]["name"] == "Product 1"
    assert tool_chunk.products[0]["currency"] == "INR"
    metadata_chunk = next(chunk for chunk in chunks if chunk.type == "metadata")
    assert metadata_chunk.citations == []
    assert metadata_chunk.products[0]["name"] == "Product 1"
    assert metadata_chunk.products[0]["currency"] == "INR"
    strapi_metadata = mock_strapi.sync_conversation.call_args.kwargs["assistant_metadata"]
    assert strapi_metadata["products"][0]["name"] == "Product 1"
    assert strapi_metadata["products"][0]["currency"] == "INR"


@pytest.mark.asyncio
async def test_build_memory_context_aggregates_current_memory_layers(service_bundle):
    service = service_bundle["service"]
    service.agent_config = {"memory": {"long_term": {"enabled": True}}}

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
        long_term_enabled=True,
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


@pytest.mark.asyncio
async def test_process_message_does_not_extract_long_term_facts_without_consent(service_bundle):
    service = service_bundle["service"]
    orchestrator = service_bundle["orchestrator"]
    service.agent_config = {"memory": {"long_term": {"enabled": True}}}
    service._long_term_memory_consent_granted = AsyncMock(return_value=False)
    service._build_memory_context = AsyncMock(return_value=_empty_memory_context())
    orchestrator.run.return_value = AgentResult(answer="A safe response", metadata={"tool_results": {}})

    await service.process_message(MessageRequest(
        message="remember that I prefer email",
        user_id="user123",
        agent_id="agent-123",
        conversation_id="conv123",
    ))

    service.episodic.extract_and_store_facts.assert_not_awaited()
