"""
Types for LLM package
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class ProviderType(Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    QWEN = "qwen"
    CLAUDE = "claude"
    GEMINI = "gemini"
    LLAMA = "llama"


class LLMConfig(BaseModel):
    """Configuration for LLM providers."""
    provider: ProviderType
    api_key: str
    model: str
    base_url: Optional[str] = None
    api_version: Optional[str] = None
    azure_endpoint: Optional[str] = None
    deployment_name: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    timeout: int = 30
