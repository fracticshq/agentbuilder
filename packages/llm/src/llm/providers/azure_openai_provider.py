"""
Azure OpenAI LLM Provider Implementation.
"""

from typing import Any, AsyncGenerator, Optional

try:
    from openai import AsyncAzureOpenAI
except ImportError:
    AsyncAzureOpenAI = None

import structlog

from ..types import LLMConfig
from .base import LLMProvider, LLMResponse

logger = structlog.get_logger(__name__)


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI provider using the Responses API."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        if not AsyncAzureOpenAI:
            raise ImportError("openai package not installed. Install with: pip install openai")
        if not config.api_key or not config.api_key.strip():
            raise ValueError("AZURE_OPENAI_API_KEY is not set.")
        if not config.azure_endpoint or not config.azure_endpoint.strip():
            raise ValueError("AZURE_OPENAI_ENDPOINT is not set.")
        if not config.api_version or not config.api_version.strip():
            raise ValueError("AZURE_OPENAI_API_VERSION is not set.")

        self.deployment_name = (config.deployment_name or config.model).strip()
        self.client = AsyncAzureOpenAI(
            api_key=config.api_key,
            azure_endpoint=config.azure_endpoint.strip(),
            api_version=config.api_version.strip(),
        )
        logger.info(
            "azure_openai_provider_initialized",
            model=config.model,
            deployment=self.deployment_name,
            endpoint=config.azure_endpoint,
        )

    @staticmethod
    def _build_input(prompt: str, system_prompt: Optional[str]) -> list[dict[str, Any]]:
        input_items: list[dict[str, Any]] = []
        if system_prompt:
            input_items.append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                }
            )
        input_items.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        )
        return input_items

    @staticmethod
    def _extract_usage(response: Any) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if not usage:
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        return {
            "prompt_tokens": getattr(usage, "input_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "output_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }

    @staticmethod
    def _extract_text(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text

        output = getattr(response, "output", None) or []
        text_chunks: list[str] = []
        for item in output:
            for content in getattr(item, "content", []) or []:
                text_value = getattr(content, "text", None)
                if text_value:
                    text_chunks.append(text_value)
        return "".join(text_chunks)

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a response from Azure OpenAI."""
        system_prompt = kwargs.pop("system_prompt", None)
        temperature = kwargs.pop("temperature", self.config.temperature)
        max_tokens = kwargs.pop("max_tokens", self.config.max_tokens)
        request_kwargs: dict[str, Any] = {
            "model": self.deployment_name,
            "input": self._build_input(prompt, system_prompt),
            **kwargs,
        }
        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_tokens is not None:
            request_kwargs["max_output_tokens"] = max_tokens

        response = await self.client.responses.create(**request_kwargs)

        return LLMResponse(
            content=self._extract_text(response),
            usage=self._extract_usage(response),
        )

    async def stream(self, prompt: str, **kwargs) -> AsyncGenerator[LLMResponse, None]:
        """Stream a response from Azure OpenAI."""
        system_prompt = kwargs.pop("system_prompt", None)
        temperature = kwargs.pop("temperature", self.config.temperature)
        max_tokens = kwargs.pop("max_tokens", self.config.max_tokens)
        request_kwargs: dict[str, Any] = {
            "model": self.deployment_name,
            "input": self._build_input(prompt, system_prompt),
            "stream": True,
            **kwargs,
        }
        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_tokens is not None:
            request_kwargs["max_output_tokens"] = max_tokens

        stream = await self.client.responses.create(**request_kwargs)

        async for event in stream:
            if getattr(event, "type", None) == "response.output_text.delta" and getattr(event, "delta", None):
                yield LLMResponse(content=event.delta)

    async def health_check(self) -> dict:
        """Check if the provider is healthy by issuing a minimal response request."""
        try:
            await self.client.responses.create(
                model=self.deployment_name,
                input="ping",
                max_output_tokens=1,
            )
            return {
                "status": "healthy",
                "provider": "azure_openai",
                "model": self.config.model,
                "deployment": self.deployment_name,
            }
        except Exception as e:
            logger.error("azure_openai_health_check_error", error=str(e))
            return {
                "status": "unhealthy",
                "provider": "azure_openai",
                "deployment": self.deployment_name,
                "error": str(e),
            }
