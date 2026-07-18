"""
Tests that unrecoverable LLM failures yield a parseable, safe terminal error
chunk from stream_message rather than a successful-looking fallback sequence.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from commons.types.requests import MessageRequest
from agent_runtime.orchestrator import AgentResult


def _make_settings(api_key="sk-test"):
    s = MagicMock()
    s.DEFAULT_LLM_PROVIDER = "openai"
    s.OPENAI_API_KEY = api_key
    s.OPENAI_MODEL = "gpt-4o-mini"
    s.QWEN_API_KEY = ""
    s.QWEN_MODEL = "qwen-max"
    return s


@pytest.mark.asyncio
async def test_stream_yields_terminal_error_chunk_on_safe_canned_llm_failure():
    """A safe-canned fallback signals failed generation, not a completed answer."""
    settings = _make_settings()

    with (
        patch("app.services.message_service.RetrievalPipeline"),
        patch("app.services.message_service.create_provider_from_env"),
        patch("app.services.message_service.connection_manager"),
        patch("app.services.message_service.ToolRegistry"),
        patch("app.services.message_service.RetrievalTool"),
        patch("app.services.message_service.ResponseValidator"),
    ):
        mock_orch_instance = MagicMock()
        mock_orch_instance.run = AsyncMock(return_value=AgentResult(
            answer="I’m not able to answer that reliably right now.",
            metadata={
                "fallback": True,
                "fallback_stage": "safe_canned",
                "fallback_reason": "planning_failed",
                "fallback_error": "AuthenticationError: Incorrect API key provided",
            },
        ))

        from app.services.message_service import MessageService
        svc = MessageService(settings=settings)

        # Stub out memory initialization so the code reaches orchestrator.run
        svc._load_agent_config = AsyncMock()
        svc._ensure_memory_initialized = AsyncMock()
        svc.short_term = AsyncMock()
        svc.short_term.add_message = AsyncMock()
        svc.short_term.get_recent_messages = AsyncMock(return_value=[])
        svc.orchestrator = mock_orch_instance

        req = MessageRequest(
            message="What warranty coverage do you provide?",
            user_id="user-test-1",
            agent_id="test-agent",
            conversation_id="conv-test-1",
        )

        chunks = [c async for c in svc.stream_message(req)]

        error_chunks = [c for c in chunks if c.type == "error"]
        assert len(error_chunks) == 1, f"Expected 1 error chunk, got: {[c.type for c in chunks]}"
        assert error_chunks[0].content == (
            "I’m sorry, but I can’t complete that response right now. Please try again in a moment."
        )
        assert error_chunks[0].metadata == {"code": "generation_failed", "retryable": True}
        assert "AuthenticationError" not in error_chunks[0].content
        assert not {"content", "final_answer", "metadata", "done"}.intersection(
            chunk.type for chunk in chunks
        )


@pytest.mark.asyncio
async def test_stream_error_chunk_has_conversation_id_and_redacts_exception_details():
    """Escaped exceptions use the same safe terminal event contract."""
    settings = _make_settings()

    with (
        patch("app.services.message_service.RetrievalPipeline"),
        patch("app.services.message_service.create_provider_from_env"),
        patch("app.services.message_service.connection_manager"),
        patch("app.services.message_service.ToolRegistry"),
        patch("app.services.message_service.RetrievalTool"),
        patch("app.services.message_service.ResponseValidator"),
    ):
        mock_orch_instance = MagicMock()
        mock_orch_instance.run = AsyncMock(
            side_effect=Exception("AuthenticationError: Incorrect API key provided")
        )

        from app.services.message_service import MessageService
        svc = MessageService(settings=settings)
        svc._load_agent_config = AsyncMock()
        svc._ensure_memory_initialized = AsyncMock()
        svc.short_term = AsyncMock()
        svc.short_term.add_message = AsyncMock()
        svc.short_term.get_recent_messages = AsyncMock(return_value=[])
        svc.orchestrator = mock_orch_instance

        req = MessageRequest(
            message="What warranty coverage do you provide?",
            user_id="user-test-2",
            agent_id="test-agent",
            conversation_id="conv-xyz-999",
        )

        chunks = [c async for c in svc.stream_message(req)]
        error_chunks = [c for c in chunks if c.type == "error"]
        assert len(error_chunks) == 1
        assert error_chunks[0].conversation_id == "conv-xyz-999"
        assert "AuthenticationError" not in error_chunks[0].content
        assert error_chunks[0].metadata == {"code": "generation_failed", "retryable": True}


def test_lalkitab_safe_abstention_is_not_an_unrecoverable_generation_failure():
    """P0's deterministic chart-validation abstention remains a normal response."""
    from app.services.message_service import _is_unrecoverable_generation_failure

    result = AgentResult(
        answer="A validated chart is required before I can provide a reading.",
        metadata={
            "lalkitab_runtime": True,
            "validation_passed": False,
            "validation_issues": ["validated_chart_context_unavailable"],
        },
    )

    assert not _is_unrecoverable_generation_failure(result)
