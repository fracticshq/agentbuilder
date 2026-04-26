"""
Application Monitoring and Observability
"""

from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
import structlog

from .config import Settings

logger = structlog.get_logger()
settings = Settings()

# Prometheus metrics
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration', ['method', 'endpoint'])
MESSAGE_COUNT = Counter('messages_total', 'Total messages processed', ['status'])
MESSAGE_DURATION = Histogram('message_processing_seconds', 'Message processing duration', ['mode', 'status'])
RATE_LIMIT_COUNT = Counter('rate_limit_events_total', 'Rate limit decisions', ['policy', 'identifier_type', 'outcome'])
GUARDRAIL_COUNT = Counter('guardrail_events_total', 'Guardrail decisions', ['action', 'reason'])
AGENT_FALLBACK_COUNT = Counter('agent_fallback_events_total', 'Agent fallback events', ['stage', 'reason'])
STRAPI_SYNC_COUNT = Counter('strapi_sync_events_total', 'Strapi sync attempts', ['operation', 'status'])


def setup_monitoring(app: FastAPI):
    """Setup monitoring and metrics."""

    @app.get("/metrics")
    async def get_metrics():
        """Prometheus metrics endpoint."""
        if not settings.ENABLE_METRICS:
            raise HTTPException(status_code=404, detail="Metrics disabled")
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    logger.info("Monitoring setup complete")
