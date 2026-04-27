"""
Mock LLM Provider for testing
"""

import asyncio
from typing import AsyncGenerator
from .base import LLMProvider, LLMResponse


class MockProvider(LLMProvider):
    """Mock LLM provider for testing."""
    
    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a mock response."""
        await asyncio.sleep(0.1)  # Simulate API delay
        
        response_text = f"Mock response to: {prompt[:100]}..."
        return LLMResponse(content=response_text)
    
    async def stream(self, prompt: str, **kwargs) -> AsyncGenerator[LLMResponse, None]:
        """Stream a mock response."""
        response_text = f"Mock streaming response to: {prompt[:50]}..."
        
        # Split response into chunks
        chunk_size = 10
        for i in range(0, len(response_text), chunk_size):
            chunk = response_text[i:i + chunk_size]
            await asyncio.sleep(0.05)  # Simulate streaming delay
            yield LLMResponse(content=chunk)
    
    async def health_check(self) -> dict:
        """Return mock health status."""
        return {
            "status": "healthy",
            "provider": "mock",
            "model": self.config.model
        }
