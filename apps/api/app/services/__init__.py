"""
Services module for the FastAPI application.
"""

__all__ = ["MessageService", "IngestionService", "HealthService"]


def __getattr__(name: str):
    if name == "MessageService":
        from .message_service import MessageService

        return MessageService
    if name == "IngestionService":
        from .ingestion_service import IngestionService

        return IngestionService
    if name == "HealthService":
        from .health_service import HealthService

        return HealthService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
