"""
Role-Based Access Control (RBAC) utilities.
"""

import structlog
from ..auth.models import User, Permission, UserRole, ROLE_PERMISSIONS, GLOBAL_ADMIN_ROLES

logger = structlog.get_logger()


def check_permission(user: User, permission: Permission) -> bool:
    """
    Check if a user has a specific permission.
    
    Args:
        user: User to check
        permission: Required permission
    
    Returns:
        True if user has permission
    """
    user_permissions = ROLE_PERMISSIONS.get(user.role, [])
    has_permission = permission in user_permissions
    
    logger.debug(
        "permission_check",
        user_id=user.id,
        user_role=user.role.value,
        permission=permission.value,
        has_permission=has_permission
    )
    
    return has_permission


def check_multiple_permissions(user: User, permissions: list[Permission], require_all: bool = True) -> bool:
    """
    Check if a user has multiple permissions.
    
    Args:
        user: User to check
        permissions: List of required permissions
        require_all: If True, user must have all permissions. If False, any permission is sufficient.
    
    Returns:
        True if permission check passes
    """
    user_permissions = ROLE_PERMISSIONS.get(user.role, [])
    
    if require_all:
        # User must have ALL permissions
        has_permissions = all(perm in user_permissions for perm in permissions)
    else:
        # User must have ANY permission
        has_permissions = any(perm in user_permissions for perm in permissions)
    
    logger.debug(
        "multiple_permissions_check",
        user_id=user.id,
        user_role=user.role.value,
        required_permissions=[p.value for p in permissions],
        require_all=require_all,
        has_permissions=has_permissions
    )
    
    return has_permissions


def check_brand_access(user: User, brand_id: str) -> bool:
    """
    Check if a user has access to a specific brand.
    
    Args:
        user: User to check
        brand_id: Brand ID to check access for
    
    Returns:
        True if user has access to the brand
    """
    # Admins have access to all brands
    if user.role in GLOBAL_ADMIN_ROLES:
        return True
    
    # Check if brand_id is in user's accessible brands
    has_access = brand_id in user.brands
    
    logger.debug(
        "brand_access_check",
        user_id=user.id,
        brand_id=brand_id,
        user_brands=user.brands,
        has_access=has_access
    )
    
    return has_access


def get_user_permissions(user: User) -> list[Permission]:
    """
    Get all permissions for a user based on their role.
    
    Args:
        user: User to get permissions for
    
    Returns:
        List of permissions
    """
    return ROLE_PERMISSIONS.get(user.role, [])


def can_manage_user(actor: User, target_user: User) -> bool:
    """
    Check if an actor user can manage (edit/delete) a target user.
    
    Rules:
    - Admins can manage all users
    - Users cannot manage other users
    - Users cannot manage themselves (for certain operations)
    
    Args:
        actor: User performing the action
        target_user: User being managed
    
    Returns:
        True if actor can manage target user
    """
    # Admins can manage all users
    if actor.role in GLOBAL_ADMIN_ROLES:
        return True
    
    # Regular users cannot manage other users
    return False


def can_manage_brand(user: User, brand_id: str) -> bool:
    """
    Check if a user can manage a brand (create/edit/delete agents, documents).
    
    Args:
        user: User to check
        brand_id: Brand ID
    
    Returns:
        True if user can manage the brand
    """
    # Must have brand access
    if not check_brand_access(user, brand_id):
        return False
    
    # Must have write permissions
    has_write_permission = (
        check_permission(user, Permission.AGENT_WRITE) or
        check_permission(user, Permission.BRAND_WRITE)
    )
    
    return has_write_permission


def can_delete_brand(user: User, brand_id: str) -> bool:
    """
    Check if a user can delete a brand.
    
    Args:
        user: User to check
        brand_id: Brand ID
    
    Returns:
        True if user can delete the brand
    """
    # Must have brand access
    if not check_brand_access(user, brand_id):
        return False
    
    # Must have delete permission (usually admin only)
    return check_permission(user, Permission.BRAND_DELETE)


def get_accessible_brands(user: User, all_brand_ids: list[str]) -> list[str]:
    """
    Filter a list of brand IDs to only those the user can access.
    
    Args:
        user: User to check
        all_brand_ids: List of all brand IDs to filter
    
    Returns:
        List of accessible brand IDs
    """
    # Admins can access all brands
    if user.role in GLOBAL_ADMIN_ROLES:
        return all_brand_ids
    
    # Filter to only user's accessible brands
    return [brand_id for brand_id in all_brand_ids if brand_id in user.brands]
