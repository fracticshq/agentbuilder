"""
Authentication API endpoints.
"""

from fastapi import APIRouter
from .login import router as login_router
from .register import router as register_router
from .tokens import router as tokens_router
from .api_keys import router as api_keys_router
from .users import router as users_router
from .google import router as google_router
from .password_reset import router as password_reset_router

# Main auth router
auth_router = APIRouter(prefix="/auth", tags=["authentication"])

# Include sub-routers
auth_router.include_router(login_router)
auth_router.include_router(register_router)
auth_router.include_router(tokens_router)
auth_router.include_router(api_keys_router)
auth_router.include_router(users_router)
auth_router.include_router(google_router)
auth_router.include_router(password_reset_router)

__all__ = ["auth_router"]
