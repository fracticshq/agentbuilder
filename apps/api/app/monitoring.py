"""
Application Monitoring and Observability
"""

from fastapi import FastAPI
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
import structlog

logger = structlog.get_logger()

# Prometheus metrics
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration', ['method', 'endpoint'])
MESSAGE_COUNT = Counter('messages_total', 'Total messages processed', ['status'])
MESSAGE_DURATION = Histogram('message_processing_seconds', 'Message processing duration')


def setup_monitoring(app: FastAPI):
    """Setup monitoring and metrics."""
    
    @app.get("/metrics")
    async def get_metrics():
        """Prometheus metrics endpoint."""
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    
    logger.info("Monitoring setup complete")
