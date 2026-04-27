"""
Base LLM Provider Interface
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional
from ..types import LLMConfig


class LLMResponse:
    """Response from LLM provider."""
    def __init__(self, content: str, usage: Optional[dict] = None):
        self.content = content
        self.usage = usage or {}


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    def __init__(self, config: LLMConfig):
        self.config = config
    
    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a response to the prompt."""
        pass
    
    @abstractmethod
    async def stream(self, prompt: str, **kwargs) -> AsyncGenerator[LLMResponse, None]:
        """Stream a response to the prompt."""
        pass
    
    @abstractmethod
    async def health_check(self) -> dict:
        """Check if the provider is healthy."""
        pass
