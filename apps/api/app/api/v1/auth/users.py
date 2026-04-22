"""
User management endpoints.
"""

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

from ....auth.models import User, UserRole
from ....auth.password import hash_password, validate_password_strength
from ....auth.dependencies import get_current_active_user, require_role
from ....auth.dependencies import get_db

router = APIRouter()


class UserResponse(BaseModel):
    """User response model."""
    id: str
    username: str
    email: str
    full_name: Optional[str]
    role: UserRole
    brand_id: Optional[str]
    disabled: bool
    created_at: datetime
    updated_at: datetime


class UpdateUserRequest(BaseModel):
    """Update user request."""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = None


class UpdateUserRoleRequest(BaseModel):
    """Update user role request (admin only)."""
    role: UserRole


def _primary_brand_id(user: User) -> Optional[str]:
    return user.brands[0] if user.brands else None


def _serialize_user_response(user_doc: dict | User) -> UserResponse:
    user = user_doc if isinstance(user_doc, User) else User(**user_doc)
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        brand_id=_primary_brand_id(user),
        disabled=not user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
):
    """
    Get current user's profile information.
    
    Requires authentication.
    """
    return _serialize_user_response(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_current_user(
    request: UpdateUserRequest,
    current_user: User = Depends(get_current_active_user),
    db = Depends(get_db)
):
    """
    Update current user's profile.
    
    Requires authentication.
    
    - **email**: New email address
    - **full_name**: New full name
    - **password**: New password (will be hashed)
    """
    update_data = {"updated_at": datetime.utcnow()}
    
    # Update email if provided
    if request.email:
        # Check if email is already taken by another user
        existing_user = await db.users.find_one({
            "email": request.email,
            "_id": {"$ne": ObjectId(current_user.id)}
        })
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use"
            )
        update_data["email"] = request.email
    
    # Update full name if provided
    if request.full_name is not None:
        update_data["full_name"] = request.full_name
    
    # Update password if provided
    if request.password:
        is_valid, error_msg = validate_password_strength(request.password)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
        update_data["password_hash"] = hash_password(request.password)
    
    # Update user
    await db.users.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": update_data}
    )
    
    # Fetch updated user
    user_doc = await db.users.find_one({"_id": ObjectId(current_user.id)})
    return _serialize_user_response(user_doc)


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db = Depends(get_db)
):
    """
    List all users (admin only).
    
    Requires admin role.
    """
    cursor = db.users.find().sort("created_at", -1)
    users = await cursor.to_list(length=1000)
    
    return [_serialize_user_response(user) for user in users]


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db = Depends(get_db)
):
    """
    Get user by ID (admin only).
    
    Requires admin role.
    """
    user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return _serialize_user_response(user_doc)


@router.patch("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: str,
    request: UpdateUserRoleRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db = Depends(get_db)
):
    """
    Update user role (admin only).
    
    Requires admin role.
    
    - **role**: New role (admin, user, viewer)
    """
    # Prevent self-demotion
    if str(current_user.id) == user_id and request.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot demote yourself from admin role"
        )
    
    # Update role
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "role": request.role.value,
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Fetch updated user
    user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    return _serialize_user_response(user_doc)


@router.patch("/users/{user_id}/disable", response_model=UserResponse)
async def disable_user(
    user_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db = Depends(get_db)
):
    """
    Disable a user account (admin only).
    
    Requires admin role.
    """
    # Prevent self-disable
    if str(current_user.id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable your own account"
        )
    
    # Disable user
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "is_active": False,
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Fetch updated user
    user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    return _serialize_user_response(user_doc)


@router.patch("/users/{user_id}/enable", response_model=UserResponse)
async def enable_user(
    user_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db = Depends(get_db)
):
    """
    Enable a disabled user account (admin only).
    
    Requires admin role.
    """
    # Enable user
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "is_active": True,
                "failed_login_attempts": 0,
                "locked_until": None,
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Fetch updated user
    user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    return _serialize_user_response(user_doc)
