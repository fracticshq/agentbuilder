"""
Tests for OpenAIProvider init-time API key validation.

These tests should FAIL before Fix 2 is applied (no validation at __init__).
"""
import pytest

from llm.types import LLMConfig, ProviderType
from llm.providers.openai_provider import OpenAIProvider


def test_raises_on_empty_api_key():
    """OpenAIProvider must raise ValueError immediately when api_key is empty."""
    config = LLMConfig(provider=ProviderType.OPENAI, api_key="", model="gpt-4o-mini")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIProvider(config)


def test_raises_on_whitespace_api_key():
    """OpenAIProvider must raise ValueError when api_key is only whitespace."""
    config = LLMConfig(provider=ProviderType.OPENAI, api_key="   ", model="gpt-4o-mini")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIProvider(config)


def test_valid_api_key_does_not_raise():
    """A non-empty api_key must not raise at init time."""
    config = LLMConfig(provider=ProviderType.OPENAI, api_key="sk-test-key", model="gpt-4o-mini")
    # Should construct without error (no network call at init)
    provider = OpenAIProvider(config)
    assert provider is not None
