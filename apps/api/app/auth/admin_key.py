"""
Simple admin API key guard for write operations.

Used to protect POST/PUT/DELETE routes on brands, agents, and ingestion
until a full JWT login UI is built for the admin dashboard.

Usage:
    @router.post("/", dependencies=[Depends(require_admin_key)])
    async def create_brand(...): ...

Configuration:
    Set ADMIN_API_KEY env var to a strong random key (openssl rand -hex 32).
    Pass as X-Admin-Key header in requests.
    If ADMIN_API_KEY is not set, the guard is bypassed (dev convenience).
"""

import secrets
from fastapi import Depends, HTTPException, status, Header
from typing import Optional
import structlog

from ..dependencies import get_settings

logger = structlog.get_logger()


def is_admin_key_authorized(
    provided_key: Optional[str],
    settings,
) -> bool:
    """Return whether a provided admin key is authorized for the current settings."""
    configured_key = settings.ADMIN_API_KEY
    if not configured_key:
        return settings.ALLOW_ADMIN_KEY_BYPASS and not settings.is_production
    if not provided_key:
        return False
    return secrets.compare_digest(provided_key, configured_key)


async def require_admin_key(
    x_admin_key: Optional[str] = Header(None),
    settings=Depends(get_settings),
) -> None:
    """
    Verify the X-Admin-Key header matches ADMIN_API_KEY.

    Bypassed if ADMIN_API_KEY is not configured (for local dev without auth).
    """
    configured_key = settings.ADMIN_API_KEY
    if not configured_key:
        if is_admin_key_authorized(None, settings):
            return
        logger.warning("admin_write_rejected_unconfigured_key")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin write protection is not configured",
        )

    if not x_admin_key:
        logger.warning("admin_write_rejected_missing_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Admin-Key header required",
            headers={"WWW-Authenticate": "X-Admin-Key"},
        )

    if not is_admin_key_authorized(x_admin_key, settings):
        logger.warning("admin_write_rejected_invalid_key")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key",
        )
