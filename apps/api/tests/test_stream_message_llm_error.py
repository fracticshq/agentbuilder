"""
Tests that LLM authentication/runtime errors yield a parseable error chunk
from stream_message rather than propagating an unhandled exception.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from commons.types.requests import MessageRequest


def _make_settings(api_key="sk-test"):
    s = MagicMock()
    s.DEFAULT_LLM_PROVIDER = "openai"
    s.OPENAI_API_KEY = api_key
    s.OPENAI_MODEL = "gpt-4o-mini"
    s.QWEN_API_KEY = ""
    s.QWEN_MODEL = "qwen-max"
    return s


@pytest.mark.asyncio
async def test_stream_yields_error_chunk_on_llm_failure():
    """When the orchestrator raises, stream_message must yield exactly one
    type='error' chunk with non-trivial content — not an unhandled exception."""
    settings = _make_settings()

    with (
        patch("app.services.message_service.RetrievalPipeline"),
        patch("app.services.message_service.create_provider_from_env") as mock_factory,
        patch("app.services.message_service.Orchestrator") as MockOrch,
        patch("app.services.message_service.connection_manager"),
        patch("app.services.message_service.ToolRegistry"),
        patch("app.services.message_service.RetrievalTool"),
        patch("app.services.message_service.ResponseValidator"),
    ):
        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        mock_orch_instance = AsyncMock()
        mock_orch_instance.run.side_effect = Exception(
            "AuthenticationError: Incorrect API key provided"
        )
        MockOrch.return_value = mock_orch_instance

        from app.services.message_service import MessageService
        svc = MessageService(settings=settings)

        # Stub out memory initialization so the code reaches orchestrator.run
        svc._load_agent_config = AsyncMock()
        svc._ensure_memory_initialized = AsyncMock()
        svc.short_term = AsyncMock()
        svc.short_term.add_message = AsyncMock()
        svc.short_term.get_recent_messages = AsyncMock(return_value=[])

        req = MessageRequest(
            message="Hello",
            agent_id="test-agent",
            conversation_id="conv-test-1",
        )

        chunks = [c async for c in svc.stream_message(req)]

        error_chunks = [c for c in chunks if c.type == "error"]
        assert len(error_chunks) == 1, f"Expected 1 error chunk, got: {[c.type for c in chunks]}"
        assert len(error_chunks[0].content) > 5, "Error chunk content must be non-trivial"
        assert "AuthenticationError" in error_chunks[0].content or "Error" in error_chunks[0].content


@pytest.mark.asyncio
async def test_stream_error_chunk_has_conversation_id():
    """Error chunk must carry the conversation_id so the client can correlate it."""
    settings = _make_settings()

    with (
        patch("app.services.message_service.RetrievalPipeline"),
        patch("app.services.message_service.create_provider_from_env"),
        patch("app.services.message_service.Orchestrator") as MockOrch,
        patch("app.services.message_service.connection_manager"),
        patch("app.services.message_service.ToolRegistry"),
        patch("app.services.message_service.RetrievalTool"),
        patch("app.services.message_service.ResponseValidator"),
    ):
        mock_orch_instance = AsyncMock()
        mock_orch_instance.run.side_effect = Exception("LLM failure")
        MockOrch.return_value = mock_orch_instance

        from app.services.message_service import MessageService
        svc = MessageService(settings=settings)
        svc._load_agent_config = AsyncMock()
        svc._ensure_memory_initialized = AsyncMock()
        svc.short_term = AsyncMock()
        svc.short_term.add_message = AsyncMock()
        svc.short_term.get_recent_messages = AsyncMock(return_value=[])

        req = MessageRequest(
            message="Hi",
            agent_id="test-agent",
            conversation_id="conv-xyz-999",
        )

        chunks = [c async for c in svc.stream_message(req)]
        error_chunks = [c for c in chunks if c.type == "error"]
        assert error_chunks[0].conversation_id == "conv-xyz-999"
