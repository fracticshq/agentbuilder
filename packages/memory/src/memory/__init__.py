"""
Memory Package - Agent Builder Platform Memory System

Provides 4-layer memory architecture:
1. Short-Term: Rolling buffer with auto-summary (TTL 72h)
2. Episodic: User facts/preferences with PII vaulting (TTL 90d)
3. Semantic: Brand knowledge base (via retrieval package)
4. Graph: Rules, policies, escalation patterns
"""

from memory.types import (
    Message,
    MessageRole,
    ConversationSummary,
    EpisodicFact,
    GraphRule,
    EscalationTrigger,
    MemoryContext,
    PIIField,
    MemoryStats,
    ExtractedEntity,
    MemoryType,
)

from memory.config import MemoryConfig

from memory.managers.short_term import ShortTermMemory
from memory.managers.episodic import EpisodicMemory
from memory.managers.graph import GraphMemory
from memory.processors.pii_vault import PIIDetector, PIIVault, get_pii_vault
from memory.processors.entity_extractor import EntityExtractor, ConfidenceScorer
from memory.utils.crypto import CryptoUtils, CryptoError, get_crypto_utils

__version__ = "0.1.0"

__all__ = [
    # Types
    "Message",
    "MessageRole",
    "ConversationSummary",
    "EpisodicFact",
    "GraphRule",
    "EscalationTrigger",
    "MemoryContext",
    "PIIField",
    "MemoryStats",
    "ExtractedEntity",
    "MemoryType",
    
    # Config
    "MemoryConfig",
    
    # Managers
    "ShortTermMemory",
    "EpisodicMemory",
    "GraphMemory",
    
    # Processors
    "PIIDetector",
    "PIIVault",
    "get_pii_vault",
    "EntityExtractor",
    "ConfidenceScorer",
    
    # Utils
    "CryptoUtils",
    "CryptoError",
    "get_crypto_utils",
]
