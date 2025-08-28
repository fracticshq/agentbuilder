"""
LLM Factory for creating provider instances.
"""

from typing import Dict, Type
from .types import LLMConfig, ProviderType
from .providers.base import LLMProvider

# Import providers as they become available
try:
    from .providers.openai_provider import OpenAIProvider
except ImportError:
    OpenAIProvider = None

try:
    from .providers.qwen_provider import QwenProvider
except ImportError:
    QwenProvider = None

try:
    from .providers.mock_provider import MockProvider
except ImportError:
    MockProvider = None


class LLMFactory:
    """Factory for creating LLM provider instances."""
    
    _providers: Dict[ProviderType, Type[LLMProvider]] = {}
    
    @classmethod
    def register_provider(cls, provider_type: ProviderType, provider_class: Type[LLMProvider]) -> None:
        """Register a provider class."""
        cls._providers[provider_type] = provider_class
    
    @classmethod
    def create_provider(cls, config: LLMConfig) -> LLMProvider:
        """Create a provider instance from config."""
        provider_class = cls._providers.get(config.provider)
        
        if not provider_class:
            raise ValueError(f"Unsupported provider: {config.provider}")
        
        return provider_class(config)
    
    @classmethod
    def get_available_providers(cls) -> list[ProviderType]:
        """Get list of available providers."""
        return list(cls._providers.keys())


# Register available providers
if OpenAIProvider:
    LLMFactory.register_provider(ProviderType.OPENAI, OpenAIProvider)

if QwenProvider:
    LLMFactory.register_provider(ProviderType.QWEN, QwenProvider)

if MockProvider:
    LLMFactory.register_provider(ProviderType.QWEN, MockProvider)  # Use mock for Qwen for now


def create_provider_from_env(provider_name: str, api_key: str, model: str) -> LLMProvider:
    """Create a provider from environment variables."""
    try:
        provider_type = ProviderType(provider_name.lower())
    except ValueError:
        raise ValueError(f"Unknown provider: {provider_name}")
    
    config = LLMConfig(
        provider=provider_type,
        api_key=api_key,
        model=model,
        base_url=None
    )
    
    return LLMFactory.create_provider(config)
