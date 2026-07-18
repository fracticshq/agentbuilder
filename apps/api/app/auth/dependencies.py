"""
FastAPI dependencies for authentication and authorization.
"""

from datetime import datetime
from typing import Optional
from bson import ObjectId
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import structlog

from ..config import Settings
from ..connections import connection_manager
from .jwt import decode_and_verify_token
from .api_keys import verify_api_key, extract_key_id
from .models import (
    GLOBAL_ADMIN_ROLES,
    User,
    UserRole,
    Permission,
    APIKey,
    ROLE_PERMISSIONS,
)
from .admin_key import is_admin_key_authorized

logger = structlog.get_logger()
settings = Settings()

# Security schemes
security = HTTPBearer(auto_error=False)


def _mongo_id_filter(value: str | ObjectId) -> dict:
    try:
        return {"_id": ObjectId(str(value))}
    except Exception:
        return {"_id": value}


async def get_db() -> AsyncIOMotorDatabase:
    """Get database connection."""
    try:
        return connection_manager.get_mongodb_db()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> User:
    """
    Get current user from JWT token.
    
    Args:
        credentials: Bearer token from Authorization header
        db: Database connection
    
    Returns:
        Current user
    
    Raises:
        HTTPException: If authentication fails
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception
    
    token = credentials.credentials
    
    # Verify and decode token
    payload = decode_and_verify_token(token, token_type="access")
    if payload is None:
        logger.warning("invalid_token")
        raise credentials_exception
    
    user_id = payload.get("user_id")
    if user_id is None:
        logger.warning("token_missing_user_id")
        raise credentials_exception
    
    # Get user from database
    users_collection = db.users
    user_doc = await users_collection.find_one(_mongo_id_filter(user_id))
    
    if user_doc is None:
        logger.warning("user_not_found", user_id=user_id)
        raise credentials_exception
    
    user = User(**user_doc)
    
    # Check if user is locked
    if user.is_locked():
        logger.warning("account_locked", user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is locked until {user.locked_until.isoformat()}"
        )
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Get current active user.
    
    Args:
        current_user: Current user from token
    
    Returns:
        Active user
    
    Raises:
        HTTPException: If user is inactive
    """
    if not current_user.is_active:
        logger.warning("inactive_user_access", user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    return current_user


async def get_api_key_user(
    x_api_key: Optional[str] = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> User:
    """
    Get user from API key.
    
    Args:
        x_api_key: API key from X-API-Key header
        db: Database connection
    
    Returns:
        User associated with API key
    
    Raises:
        HTTPException: If API key is invalid
    """
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required"
        )
    
    # Extract key ID
    key_id = extract_key_id(x_api_key)
    if key_id is None:
        logger.warning("invalid_api_key_format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format"
        )
    
    # Get API key from database
    api_keys_collection = db.api_keys
    api_key_doc = await api_keys_collection.find_one({"key_id": key_id})
    
    if api_key_doc is None:
        logger.warning("api_key_not_found", key_id=key_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    api_key = APIKey(**api_key_doc)
    
    # Verify API key
    if not verify_api_key(x_api_key, api_key.key_hash):
        logger.warning("api_key_verification_failed", key_id=key_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    # Check if API key is valid
    if not api_key.is_valid():
        logger.warning("api_key_invalid", key_id=key_id, is_active=api_key.is_active)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is expired or inactive"
        )
    
    # Update last used timestamp
    await api_keys_collection.update_one(
        _mongo_id_filter(api_key.id),
        {
            "$set": {"usage.last_used": datetime.utcnow()},
            "$inc": {"usage.total_requests": 1}
        }
    )
    
    # Get user
    users_collection = db.users
    user_doc = await users_collection.find_one(_mongo_id_filter(api_key.user_id))
    
    if user_doc is None:
        logger.error("api_key_user_not_found", user_id=api_key.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    user = User(**user_doc)
    
    # Check if user is active
    if not user.is_active:
        logger.warning("inactive_user_api_key", user_id=user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    if user.is_locked():
        logger.warning("locked_user_api_key", user_id=user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is locked until {user.locked_until.isoformat()}",
        )
    
    return user


async def get_user_from_token_or_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> User:
    """
    Get user from either JWT token or API key.
    
    Tries JWT first, then falls back to API key.
    
    Args:
        credentials: Bearer token (optional)
        x_api_key: API key (optional)
        db: Database connection
    
    Returns:
        Authenticated user
    
    Raises:
        HTTPException: If authentication fails
    """
    # Try JWT first
    if credentials is not None:
        try:
            return await get_current_active_user(await get_current_user(credentials, db))
        except HTTPException:
            # If JWT fails and no API key, raise error
            if x_api_key is None:
                raise
    
    # Try API key
    if x_api_key is not None:
        return await get_api_key_user(x_api_key, db)
    
    # No authentication provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required (JWT token or API key)"
    )


async def require_dashboard_access(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_admin_key: Optional[str] = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Optional[User]:
    """
    Allow access from an authenticated dashboard user or a valid admin API key.

    The admin key path remains as a compatibility fallback for operator scripts.
    """
    if credentials is not None:
        user = await get_current_active_user(await get_current_user(credentials, db))
        # Widget users must not receive control-plane access merely because
        # they hold a valid JWT. Individual routes still enforce permissions
        # and brand scope for the remaining operational roles.
        if user.role in {UserRole.USER, UserRole.VIEWER}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Dashboard access is restricted to operator roles",
            )
        return user

    # A global admin key cannot bypass tenant RBAC in production. Keep this
    # narrow compatibility path for explicitly enabled local operator flows.
    if (
        x_admin_key
        and not settings.is_production
        and settings.ALLOW_ADMIN_KEY_BYPASS
        and is_admin_key_authorized(x_admin_key, settings)
    ):
        return None

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def is_global_admin(user: User | None) -> bool:
    """Whether an identity has platform-wide, rather than tenant, scope."""
    # ``None`` only represents the explicitly enabled local admin-key fallback.
    return user is None or user.role in GLOBAL_ADMIN_ROLES


def ensure_permission(user: User | None, *required_permissions: Permission) -> None:
    """Enforce an operation permission for a dashboard identity."""
    if is_global_admin(user):
        return
    missing = [
        permission
        for permission in required_permissions
        if permission not in ROLE_PERMISSIONS.get(user.role, [])
    ]
    if missing:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def ensure_brand_access(user: User | None, brand_id: str | None) -> None:
    """Enforce brand scope without leaking another tenant's resource presence."""
    if is_global_admin(user):
        return
    if not brand_id or not user.has_brand_access(brand_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found")


async def require_system_admin(
    current_user: User | None = Depends(require_dashboard_access),
) -> User | None:
    """Require the platform-level privilege needed for global configuration."""
    if not is_global_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System administration access is required",
        )
    return current_user


CONSOLE_ACCESS_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.ADMIN,
    UserRole.ORG_ADMIN,
    UserRole.BRAND_ADMIN,
    UserRole.OPERATOR,
}


async def require_console_access(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_admin_key: Optional[str] = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Optional[User]:
    """
    Require an authenticated dashboard user with Agent Console privileges.

    The X-Admin-Key fallback is intentionally limited to local/non-production
    operator workflows where ADMIN_API_KEY bypass is explicitly allowed.
    """
    if credentials is not None:
        user = await get_current_active_user(await get_current_user(credentials, db))
        if user.role not in CONSOLE_ACCESS_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agent Console access is restricted",
            )
        return user

    if (
        x_admin_key
        and not settings.is_production
        and settings.ALLOW_ADMIN_KEY_BYPASS
        and is_admin_key_authorized(x_admin_key, settings)
    ):
        return None

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Agent Console authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(*allowed_roles: UserRole):
    """
    Dependency factory to require specific roles.
    
    Usage:
        @router.get("/admin")
        async def admin_endpoint(user: User = Depends(require_role(UserRole.ADMIN))):
            ...
    
    Args:
        allowed_roles: Allowed user roles
    
    Returns:
        FastAPI dependency
    """
    async def role_checker(user: User = Depends(get_current_active_user)) -> User:
        if user.role not in allowed_roles:
            logger.warning(
                "insufficient_role",
                user_id=user.id,
                user_role=user.role,
                required_roles=[r.value for r in allowed_roles]
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(r.value for r in allowed_roles)}"
            )
        return user
    
    return role_checker


def require_permission(*required_permissions: Permission):
    """
    Dependency factory to require specific permissions.
    
    Usage:
        @router.delete("/brands/{brand_id}")
        async def delete_brand(
            brand_id: str,
            user: User = Depends(require_permission(Permission.BRAND_DELETE))
        ):
            ...
    
    Args:
        required_permissions: Required permissions
    
    Returns:
        FastAPI dependency
    """
    async def permission_checker(user: User = Depends(get_current_active_user)) -> User:
        # Check if user has all required permissions
        user_permissions = ROLE_PERMISSIONS.get(user.role, [])
        
        missing_permissions = [
            perm for perm in required_permissions
            if perm not in user_permissions
        ]
        
        if missing_permissions:
            logger.warning(
                "insufficient_permissions",
                user_id=user.id,
                user_role=user.role,
                missing_permissions=[p.value for p in missing_permissions]
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {', '.join(p.value for p in required_permissions)}"
            )
        
        return user
    
    return permission_checker


def require_brand_access(brand_id_param: str = "brand_id"):
    """
    Dependency factory to require access to a specific brand.
    
    Usage:
        @router.get("/brands/{brand_id}/agents")
        async def get_brand_agents(
            brand_id: str,
            user: User = Depends(require_brand_access("brand_id"))
        ):
            ...
    
    Args:
        brand_id_param: Name of the path/query parameter containing brand_id
    
    Returns:
        FastAPI dependency
    """
    async def brand_access_checker(
        brand_id: str,
        user: User = Depends(get_current_active_user)
    ) -> User:
        if not user.has_brand_access(brand_id):
            logger.warning(
                "brand_access_denied",
                user_id=user.id,
                brand_id=brand_id,
                user_brands=user.brands
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No access to brand {brand_id}"
            )
        
        return user
    
    return brand_access_checker
