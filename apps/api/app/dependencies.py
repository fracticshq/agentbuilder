"""
FastAPI Dependencies
"""

from functools import lru_cache
from .services.message_service import MessageService
from .services.ingestion_service import IngestionService
from .services.health_service import HealthService
from .services.knowledge_service import KnowledgeService
from .config import Settings


@lru_cache()
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()


def get_message_service() -> MessageService:
    """Get message service instance."""
    settings = get_settings()
    return MessageService(settings)


def get_ingestion_service() -> IngestionService:
    """Get ingestion service instance."""
    settings = get_settings()
    return IngestionService(settings)


def get_health_service() -> HealthService:
    """Get health service instance."""
    settings = get_settings()
    return HealthService(settings)


def get_knowledge_service() -> KnowledgeService:
    """Get knowledge service instance."""
    settings = get_settings()
    return KnowledgeService(settings)
