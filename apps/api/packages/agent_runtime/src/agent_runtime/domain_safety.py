"""Domain-specific LLM prompt sanitization helpers."""

from __future__ import annotations

import re
from typing import Any

# Bathware catalog terms can be valid product names but trip generic model safety filters.
# Keep retrieval/database values unchanged; only neutralize text sent to LLM prompts.
_DOMAIN_TERM_REPLACEMENTS = (
    (re.compile(r"\bcock\b", re.IGNORECASE), "tap"),
    (re.compile(r"\bcocks\b", re.IGNORECASE), "taps"),
)


def sanitize_llm_prompt_text(value: Any) -> Any:
    """Return a copy with domain terms rewritten for LLM prompt safety."""
    if isinstance(value, str):
        sanitized = value
        for pattern, replacement in _DOMAIN_TERM_REPLACEMENTS:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

    if isinstance(value, list):
        return [sanitize_llm_prompt_text(item) for item in value]

    if isinstance(value, tuple):
        return tuple(sanitize_llm_prompt_text(item) for item in value)

    if isinstance(value, dict):
        return {key: sanitize_llm_prompt_text(item) for key, item in value.items()}

    return value
