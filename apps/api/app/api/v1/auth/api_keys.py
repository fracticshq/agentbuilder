"""
API Key management endpoints.
"""

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta

from ....auth.models import APIKey, User, UserRole, Permission
from ....auth.api_keys import generate_api_key
from ....auth.dependencies import get_current_active_user
from ....auth.dependencies import get_db

router = APIRouter()


class CreateAPIKeyRequest(BaseModel):
    """API key creation request."""
    name: str = Field(..., min_length=3, max_length=100, description="Descriptive name for the API key")
    brand_id: Optional[str] = Field(None, description="Brand ID to scope this key to")
    permissions: List[Permission] = Field(default_factory=lambda: [Permission.MESSAGE_READ], description="Permissions for this key")
    expires_in_days: Optional[int] = Field(None, ge=1, le=365, description="Key expiration in days (max 365)")


class APIKeyResponse(BaseModel):
    """API key response."""
    id: str
    name: str
    key_preview: str
    brand_id: Optional[str]
    permissions: List[Permission]
    created_at: datetime
    expires_at: Optional[datetime]
    last_used: Optional[datetime]


class CreateAPIKeyResponse(APIKeyResponse):
    """Response when creating a new API key (includes full key)."""
    api_key: str
    warning: str = "Save this key securely. It will not be shown again."


def _primary_brand_id(api_key: APIKey) -> Optional[str]:
    return api_key.brand_ids[0] if api_key.brand_ids else None


def _serialize_api_key_response(
    key_doc: dict | APIKey,
    revealed_key: Optional[str] = None,
) -> APIKeyResponse:
    api_key = key_doc if isinstance(key_doc, APIKey) else APIKey(**key_doc)
    response_cls = CreateAPIKeyResponse if revealed_key else APIKeyResponse
    response_kwargs = {
        "id": str(api_key.id),
        "name": api_key.name,
        "key_preview": f"{api_key.key_id}...{revealed_key[-4:] if revealed_key else '****'}",
        "brand_id": _primary_brand_id(api_key),
        "permissions": [Permission(scope) for scope in api_key.scopes],
        "created_at": api_key.created_at,
        "expires_at": api_key.expires_at,
        "last_used": api_key.usage.get("last_used"),
    }
    if revealed_key:
        response_kwargs["api_key"] = revealed_key
    return response_cls(**response_kwargs)


@router.post("/keys", response_model=CreateAPIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    request: CreateAPIKeyRequest,
    current_user: User = Depends(get_current_active_user),
    db = Depends(get_db)
):
    """
    Create a new API key.
    
    Requires authentication. Users can only create keys for themselves.
    Admins can create keys for any user/brand.
    
    - **name**: Descriptive name for the key
    - **brand_id**: Optional brand scope
    - **permissions**: List of permissions (default: MESSAGE_READ)
    - **expires_in_days**: Optional expiration (max 365 days)
    """
    # Generate API key
    api_key, key_id, key_hash = generate_api_key()
    
    # Calculate expiration
    expires_at = None
    if request.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=request.expires_in_days)
    
    # Create API key document
    key_doc = {
        "user_id": str(current_user.id),
        "name": request.name,
        "key_id": key_id,
        "key_hash": key_hash,
        "brand_ids": [request.brand_id] if request.brand_id else [],
        "scopes": [p.value for p in request.permissions],
        "is_active": True,
        "created_at": datetime.utcnow(),
        "expires_at": expires_at,
        "usage": {
            "total_requests": 0,
            "last_used": None,
        },
    }
    
    # Insert key
    result = await db.api_keys.insert_one(key_doc)
    key_doc["_id"] = result.inserted_id
    return _serialize_api_key_response(key_doc, revealed_key=api_key)


@router.get("/keys", response_model=List[APIKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_active_user),
    db = Depends(get_db)
):
    """
    List all API keys for the current user.
    
    Requires authentication.
    """
    # Build query
    query = {"user_id": str(current_user.id)}
    
    # Fetch keys
    cursor = db.api_keys.find(query).sort("created_at", -1)
    keys = await cursor.to_list(length=100)
    return [_serialize_api_key_response(key) for key in keys]


@router.get("/keys/{key_id}", response_model=APIKeyResponse)
async def get_api_key(
    key_id: str,
    current_user: User = Depends(get_current_active_user),
    db = Depends(get_db)
):
    """
    Get details of a specific API key.
    
    Requires authentication. Users can only access their own keys.
    """
    # Fetch key
    key = await db.api_keys.find_one({"_id": ObjectId(key_id)})
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    # Check ownership (admins can access any key)
    if key["user_id"] != str(current_user.id) and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this API key"
        )
    return _serialize_api_key_response(key)


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: str,
    current_user: User = Depends(get_current_active_user),
    db = Depends(get_db)
):
    """
    Delete (revoke) an API key.
    
    Requires authentication. Users can only delete their own keys.
    """
    # Fetch key
    key = await db.api_keys.find_one({"_id": ObjectId(key_id)})
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    # Check ownership (admins can delete any key)
    if key["user_id"] != str(current_user.id) and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this API key"
        )
    
    # Delete key
    await db.api_keys.delete_one({"_id": ObjectId(key_id)})
    
    return None


@router.patch("/keys/{key_id}/disable", response_model=APIKeyResponse)
async def disable_api_key(
    key_id: str,
    current_user: User = Depends(get_current_active_user),
    db = Depends(get_db)
):
    """
    Disable an API key (soft delete).
    
    Requires authentication. Users can only disable their own keys.
    """
    # Fetch key
    key = await db.api_keys.find_one({"_id": ObjectId(key_id)})
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    # Check ownership
    if key["user_id"] != str(current_user.id) and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to disable this API key"
        )
    
    # Disable key
    await db.api_keys.update_one(
        {"_id": ObjectId(key_id)},
        {"$set": {"is_active": False, "revoked_at": datetime.utcnow()}}
    )
    
    # Fetch updated key
    key = await db.api_keys.find_one({"_id": ObjectId(key_id)})
    return _serialize_api_key_response(key)
