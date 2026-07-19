"""
Memory Types - Pydantic models for Agent Builder Platform Memory System
"""

from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone
from enum import Enum


class MemoryType(str, Enum):
    """Types of memory in the system."""
    SHORT_TERM = "short_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    GRAPH = "graph"


class MessageRole(str, Enum):
    """Message roles in conversations."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    """A single message in a conversation."""
    id: str = Field(description="Unique message ID")
    conversation_id: str = Field(description="Conversation identifier")
    role: MessageRole = Field(description="Message role")
    content: str = Field(description="Message content")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
class ConversationSummary(BaseModel):
    """Summary of conversation turns."""
    id: str = Field(description="Summary ID")
    conversation_id: str = Field(description="Conversation identifier")
    summary: str = Field(description="Compressed summary of turns")
    turn_count: int = Field(description="Number of turns summarized", ge=1)
    start_timestamp: datetime = Field(description="First message timestamp")
    end_timestamp: datetime = Field(description="Last message timestamp")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
class EpisodicFact(BaseModel):
    """A fact about a user extracted from conversations."""
    id: str = Field(description="Fact ID")
    user_id: str = Field(description="User identifier")
    conversation_id: str = Field(description="Source conversation")
    fact_type: str = Field(description="Type of fact (preference, context, profile)")
    fact: str = Field(description="The actual fact or preference")
    confidence: float = Field(description="Confidence score 0.0-1.0", ge=0.0, le=1.0)
    pii_encrypted: bool = Field(default=False, description="Whether fact contains encrypted PII")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(description="TTL expiration (90 days)")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence meets minimum threshold."""
        if v < 0.70:
            raise ValueError("Confidence must be ≥ 0.70 to store episodic fact")
        return v
    
class GraphRule(BaseModel):
    """A rule in the graph memory (condition → action)."""
    id: str = Field(description="Rule ID")
    brand_id: str = Field(description="Brand this rule belongs to")
    name: str = Field(description="Human-readable rule name")
    condition: Dict[str, Any] = Field(description="Condition pattern to match")
    action: Dict[str, Any] = Field(description="Action to take when matched")
    priority: int = Field(default=0, description="Priority (higher = more important)")
    enabled: bool = Field(default=True, description="Whether rule is active")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
class EscalationTrigger(BaseModel):
    """Safety escalation trigger."""
    id: str = Field(description="Trigger ID")
    keywords: List[str] = Field(description="Keywords that trigger escalation")
    severity: Literal["low", "medium", "high", "critical"] = Field(description="Escalation severity")
    action: str = Field(description="Action to take (e.g., 'contact_emergency', 'escalate_technician')")
    message: str = Field(description="Message to display to user")
    enabled: bool = Field(default=True)
    
class MemoryContext(BaseModel):
    """Complete memory context for a conversation."""
    conversation_id: str
    user_id: Optional[str] = None
    recent_messages: List[Message] = Field(default_factory=list)
    summaries: List[ConversationSummary] = Field(default_factory=list)
    episodic_facts: List[EpisodicFact] = Field(default_factory=list)
    matched_rules: List[GraphRule] = Field(default_factory=list)
    escalation_triggers: List[EscalationTrigger] = Field(default_factory=list)
    
    def total_message_count(self) -> int:
        """Total number of recent messages."""
        return len(self.recent_messages)
    
    def has_pii(self) -> bool:
        """Check if any facts contain PII."""
        return any(fact.pii_encrypted for fact in self.episodic_facts)
    
class PIIField(BaseModel):
    """Encrypted PII field."""
    encrypted_value: str = Field(description="Base64-encoded encrypted value")
    iv: str = Field(description="Base64-encoded initialization vector")
    salt: str = Field(description="Base64-encoded PBKDF2 salt")
    field_name: str = Field(description="Original field name")
    key_id: str = Field(description="Identifier of the master key used for encryption")
    key_version: int = Field(ge=1, description="Version of the master key used for encryption")
    encryption_version: int = Field(ge=1, description="Version of the PII encryption envelope")
    algorithm: str = Field(description="Authenticated encryption algorithm")
    kdf: str = Field(description="Key derivation function")
    kdf_iterations: int = Field(ge=1, description="PBKDF2 iteration count")
    encrypted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
class MemoryStats(BaseModel):
    """Memory usage statistics."""
    conversation_id: str
    message_count: int = 0
    summary_count: int = 0
    fact_count: int = 0
    rule_match_count: int = 0
    oldest_message: Optional[datetime] = None
    newest_message: Optional[datetime] = None
    storage_bytes: int = 0
    
class ExtractedEntity(BaseModel):
    """Entity extracted from text."""
    entity_type: str = Field(description="Type of entity (person, location, preference)")
    value: str = Field(description="Entity value")
    confidence: float = Field(description="Extraction confidence", ge=0.0, le=1.0)
    is_pii: bool = Field(default=False, description="Whether entity contains PII")
    context: str = Field(description="Surrounding context")
