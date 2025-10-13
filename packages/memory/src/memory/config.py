"""
Memory Configuration - Environment-based settings for Agent Builder Memory System
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class MemoryConfig:
    """Configuration for memory system."""
    
    # TTL Settings (in seconds)
    SHORT_TERM_TTL: int = int(os.getenv('SHORT_TERM_TTL', 72 * 3600))  # 72 hours
    EPISODIC_TTL: int = int(os.getenv('EPISODIC_TTL', 90 * 24 * 3600))  # 90 days
    SUMMARY_CACHE_TTL: int = int(os.getenv('SUMMARY_CACHE_TTL', 24 * 3600))  # 24 hours
    
    # Confidence Thresholds
    CONFIDENCE_THRESHOLD: float = float(os.getenv('CONFIDENCE_THRESHOLD', 0.70))
    MIN_FACT_CONFIDENCE: float = 0.70  # Hard minimum from AGENTS.md
    
    # Auto-Summary Settings
    AUTO_SUMMARY_TURNS: int = int(os.getenv('AUTO_SUMMARY_TURNS', 4))  # Every 4 turns
    MAX_MESSAGES_BEFORE_SUMMARY: int = 10  # Force summary if exceeded
    
    # Storage Limits
    MAX_MESSAGES_PER_CONVERSATION: int = int(os.getenv('MAX_MESSAGES_PER_CONVERSATION', 1000))
    MAX_FACTS_PER_USER: int = int(os.getenv('MAX_FACTS_PER_USER', 100))
    MAX_SUMMARIES_PER_CONVERSATION: int = int(os.getenv('MAX_SUMMARIES_PER_CONVERSATION', 50))
    
    # PII Encryption
    PII_ENCRYPTION_KEY: Optional[str] = os.getenv('PII_ENCRYPTION_KEY')
    PII_KEY_ROTATION_DAYS: int = int(os.getenv('PII_KEY_ROTATION_DAYS', 90))
    
    # Database Settings
    MONGODB_URI: str = os.getenv('MONGODB_URI', '')
    MONGODB_DATABASE: str = os.getenv('MONGODB_DATABASE', 'agent-builder')
    REDIS_URL: str = os.getenv('REDIS_URL', 'redis://localhost:6379')
    
    # Collections
    CONVERSATIONS_COLLECTION: str = 'conversations'
    SUMMARIES_COLLECTION: str = 'conversation_summaries'
    EPISODIC_COLLECTION: str = 'episodic_memory'
    GRAPH_RULES_COLLECTION: str = 'graph_rules'
    ESCALATIONS_COLLECTION: str = 'escalation_triggers'
    
    # LLM Settings for Summarization
    SUMMARY_MODEL: str = os.getenv('SUMMARY_MODEL', 'gpt-4o-mini')
    SUMMARY_MAX_TOKENS: int = int(os.getenv('SUMMARY_MAX_TOKENS', 150))
    SUMMARY_TEMPERATURE: float = float(os.getenv('SUMMARY_TEMPERATURE', 0.3))
    
    # Performance Settings
    MESSAGE_ADD_TIMEOUT_MS: int = 50  # P95 target
    MESSAGE_RETRIEVE_TIMEOUT_MS: int = 100  # P95 target
    FACT_EXTRACTION_TIMEOUT_MS: int = 500  # P95 target
    PII_ENCRYPTION_TIMEOUT_MS: int = 10  # Per field
    
    # Logging
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    REDACT_PII_IN_LOGS: bool = os.getenv('REDACT_PII_IN_LOGS', 'true').lower() == 'true'
    
    # Feature Flags
    ENABLE_AUTO_SUMMARY: bool = os.getenv('ENABLE_AUTO_SUMMARY', 'true').lower() == 'true'
    ENABLE_PII_VAULTING: bool = os.getenv('ENABLE_PII_VAULTING', 'true').lower() == 'true'
    ENABLE_FACT_EXTRACTION: bool = os.getenv('ENABLE_FACT_EXTRACTION', 'true').lower() == 'true'
    ENABLE_GRAPH_RULES: bool = os.getenv('ENABLE_GRAPH_RULES', 'true').lower() == 'true'
    ENABLE_TTL_CLEANUP: bool = os.getenv('ENABLE_TTL_CLEANUP', 'true').lower() == 'true'
    
    # Redis Fallback
    REDIS_FALLBACK_TO_MONGO: bool = os.getenv('REDIS_FALLBACK_TO_MONGO', 'true').lower() == 'true'
    REDIS_CONNECTION_TIMEOUT: int = int(os.getenv('REDIS_CONNECTION_TIMEOUT', 5))  # seconds
    
    @classmethod
    def validate(cls) -> bool:
        """Validate configuration."""
        errors = []
        warnings = []
        
        if not cls.MONGODB_URI:
            warnings.append("MONGODB_URI is not set")
        
        if cls.ENABLE_PII_VAULTING and not cls.PII_ENCRYPTION_KEY:
            warnings.append("PII_ENCRYPTION_KEY not set - PII vaulting will be disabled")
        
        if cls.CONFIDENCE_THRESHOLD < cls.MIN_FACT_CONFIDENCE:
            errors.append(f"CONFIDENCE_THRESHOLD must be ≥ {cls.MIN_FACT_CONFIDENCE}")
        
        if cls.AUTO_SUMMARY_TURNS < 1:
            errors.append("AUTO_SUMMARY_TURNS must be ≥ 1")
        
        if errors:
            raise ValueError(f"Memory configuration errors: {', '.join(errors)}")
        
        if warnings:
            import warnings as warn_module
            warn_module.warn(f"Memory configuration warnings: {', '.join(warnings)}")
        
        return True
    
    @classmethod
    def get_summary(cls) -> dict:
        """Get configuration summary (redacted)."""
        return {
            "ttl": {
                "short_term_hours": cls.SHORT_TERM_TTL / 3600,
                "episodic_days": cls.EPISODIC_TTL / (24 * 3600),
                "summary_cache_hours": cls.SUMMARY_CACHE_TTL / 3600,
            },
            "thresholds": {
                "confidence": cls.CONFIDENCE_THRESHOLD,
                "auto_summary_turns": cls.AUTO_SUMMARY_TURNS,
            },
            "limits": {
                "max_messages": cls.MAX_MESSAGES_PER_CONVERSATION,
                "max_facts": cls.MAX_FACTS_PER_USER,
                "max_summaries": cls.MAX_SUMMARIES_PER_CONVERSATION,
            },
            "features": {
                "auto_summary": cls.ENABLE_AUTO_SUMMARY,
                "pii_vaulting": cls.ENABLE_PII_VAULTING,
                "fact_extraction": cls.ENABLE_FACT_EXTRACTION,
                "graph_rules": cls.ENABLE_GRAPH_RULES,
                "ttl_cleanup": cls.ENABLE_TTL_CLEANUP,
            },
            "storage": {
                "database": cls.MONGODB_DATABASE,
                "redis_fallback": cls.REDIS_FALLBACK_TO_MONGO,
            },
            "pii": {
                "encryption_enabled": bool(cls.PII_ENCRYPTION_KEY),
                "redact_in_logs": cls.REDACT_PII_IN_LOGS,
            }
        }


# Validate configuration on import
try:
    MemoryConfig.validate()
except ValueError as e:
    import warnings
    warnings.warn(f"Memory configuration validation failed: {e}")
