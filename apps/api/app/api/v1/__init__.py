"""
API v1 Router
"""

from fastapi import APIRouter
from .endpoints import messages, ingestion, status, knowledge, activity
from .admin import router as admin_router
from .auth import auth_router

api_router = APIRouter()

# Include authentication router (no prefix, it has its own /auth prefix)
api_router.include_router(auth_router)

# Include endpoint routers
api_router.include_router(messages.router, prefix="/messages", tags=["messages"])
api_router.include_router(ingestion.router, prefix="/ingest", tags=["ingestion"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(status.router, prefix="/status", tags=["status"])
api_router.include_router(activity.router, prefix="/activity", tags=["activity"])

# Include admin routers
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
