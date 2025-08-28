"""
API v1 Router
"""

from fastapi import APIRouter
from .endpoints import messages, ingestion, status

api_router = APIRouter()

# Include endpoint routers
api_router.include_router(messages.router, prefix="/messages", tags=["messages"])
api_router.include_router(ingestion.router, prefix="/ingest", tags=["ingestion"])
api_router.include_router(status.router, prefix="/status", tags=["status"])
