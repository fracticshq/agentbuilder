"""
API v1 Router
"""

from fastapi import APIRouter, Depends
from .endpoints import messages, ingestion, status, knowledge, activity, catalog
from .admin import router as admin_router
from .auth import auth_router
from ...security.rate_limiter import rate_limit_dependency

api_router = APIRouter(dependencies=[Depends(rate_limit_dependency)])

# Include authentication router (no prefix, it has its own /auth prefix)
api_router.include_router(auth_router)

# Include endpoint routers
api_router.include_router(messages.router, prefix="/messages", tags=["messages"])
api_router.include_router(ingestion.router, prefix="/ingest", tags=["ingestion"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(status.router, prefix="/status", tags=["status"])
api_router.include_router(activity.router, prefix="/activity", tags=["activity"])
api_router.include_router(catalog.router, prefix="/catalog", tags=["catalog"])

# Include admin routers
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
