"""
Status API Endpoints
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Dict, Any
import structlog

from ....dependencies import get_health_service
from ....services.health_service import HealthService

logger = structlog.get_logger()
router = APIRouter()


class SystemStatus(BaseModel):
    """System status response."""
    status: str
    version: str
    services: Dict[str, Any]
    metrics: Dict[str, Any]


@router.get("/", response_model=SystemStatus)
async def get_system_status(
    health_service: HealthService = Depends(get_health_service)
):
    """Get overall system status."""
    try:
        status = await health_service.get_system_status()
        return status
    except Exception as e:
        logger.error("Error getting system status", error=str(e))
        return SystemStatus(
            status="error",
            version="1.0.0",
            services={},
            metrics={}
        )


@router.get("/health")
async def health_check():
    """Simple health check."""
    return {"status": "healthy"}


@router.get("/metrics")
async def get_metrics(
    health_service: HealthService = Depends(get_health_service)
):
    """Get system metrics."""
    try:
        metrics = await health_service.get_metrics()
        return metrics
    except Exception as e:
        logger.error("Error getting metrics", error=str(e))
        return {"error": "Unable to retrieve metrics"}
