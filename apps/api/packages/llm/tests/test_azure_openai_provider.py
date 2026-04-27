import pytest

from llm.providers.azure_openai_provider import AzureOpenAIProvider
from llm.types import LLMConfig, ProviderType


def test_raises_on_empty_api_key():
    config = LLMConfig(
        provider=ProviderType.AZURE_OPENAI,
        api_key="",
        model="gpt-5.4-mini",
        azure_endpoint="https://example-resource.openai.azure.com/",
        api_version="2025-01-01-preview",
    )
    with pytest.raises(ValueError, match="AZURE_OPENAI_API_KEY"):
        AzureOpenAIProvider(config)


def test_raises_on_missing_endpoint():
    config = LLMConfig(
        provider=ProviderType.AZURE_OPENAI,
        api_key="azure-test-key",
        model="gpt-5.4-mini",
        azure_endpoint="",
        api_version="2025-01-01-preview",
    )
    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        AzureOpenAIProvider(config)


def test_raises_on_missing_api_version():
    config = LLMConfig(
        provider=ProviderType.AZURE_OPENAI,
        api_key="azure-test-key",
        model="gpt-5.4-mini",
        azure_endpoint="https://example-resource.openai.azure.com/",
        api_version="",
    )
    with pytest.raises(ValueError, match="AZURE_OPENAI_API_VERSION"):
        AzureOpenAIProvider(config)


def test_valid_config_uses_model_as_default_deployment():
    config = LLMConfig(
        provider=ProviderType.AZURE_OPENAI,
        api_key="azure-test-key",
        model="gpt-5.4-mini",
        azure_endpoint="https://example-resource.openai.azure.com/",
        api_version="2025-01-01-preview",
    )
    provider = AzureOpenAIProvider(config)
    assert provider.deployment_name == "gpt-5.4-mini"
