"""
API Key management endpoints.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta

from app.auth.models import User, UserRole, Permission
from app.auth.api_keys import generate_api_key, hash_api_key
from app.auth.dependencies import get_current_active_user, require_permission
from app.dependencies import get_db

router = APIRouter()


class CreateAPIKeyRequest(BaseModel):
    """API key creation request."""
    name: str = Field(..., min_length=3, max_length=100, description="Descriptive name for the API key")
    brand_id: Optional[str] = Field(None, description="Brand ID to scope this key to")
    permissions: List[Permission] = Field(default_factory=lambda: [Permission.READ_MESSAGES], description="Permissions for this key")
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
    - **permissions**: List of permissions (default: READ_MESSAGES)
    - **expires_in_days**: Optional expiration (max 365 days)
    """
    # Generate API key
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    
    # Calculate expiration
    expires_at = None
    if request.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=request.expires_in_days)
    
    # Create API key document
    key_doc = {
        "user_id": str(current_user.id),
        "name": request.name,
        "key_hash": key_hash,
        "key_prefix": api_key[:8],  # Store prefix for identification
        "brand_id": request.brand_id,
        "permissions": [p.value for p in request.permissions],
        "disabled": False,
        "created_at": datetime.utcnow(),
        "expires_at": expires_at,
        "last_used": None
    }
    
    # Insert key
    from bson import ObjectId
    result = await db.api_keys.insert_one(key_doc)
    key_doc["id"] = str(result.inserted_id)
    
    return CreateAPIKeyResponse(
        id=key_doc["id"],
        name=key_doc["name"],
        key_preview=f"{key_doc['key_prefix']}...{api_key[-4:]}",
        api_key=api_key,
        brand_id=key_doc.get("brand_id"),
        permissions=[Permission(p) for p in key_doc["permissions"]],
        created_at=key_doc["created_at"],
        expires_at=key_doc.get("expires_at"),
        last_used=key_doc.get("last_used")
    )


@router.get("/keys", response_model=List[APIKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_active_user),
    db = Depends(get_db)
):
    """
    List all API keys for the current user.
    
    Requires authentication.
    """
    from bson import ObjectId
    
    # Build query
    query = {"user_id": str(current_user.id)}
    
    # Fetch keys
    cursor = db.api_keys.find(query).sort("created_at", -1)
    keys = await cursor.to_list(length=100)
    
    # Format response
    return [
        APIKeyResponse(
            id=str(key["_id"]),
            name=key["name"],
            key_preview=f"{key['key_prefix']}...****",
            brand_id=key.get("brand_id"),
            permissions=[Permission(p) for p in key["permissions"]],
            created_at=key["created_at"],
            expires_at=key.get("expires_at"),
            last_used=key.get("last_used")
        )
        for key in keys
    ]


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
    from bson import ObjectId
    
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
    
    return APIKeyResponse(
        id=str(key["_id"]),
        name=key["name"],
        key_preview=f"{key['key_prefix']}...****",
        brand_id=key.get("brand_id"),
        permissions=[Permission(p) for p in key["permissions"]],
        created_at=key["created_at"],
        expires_at=key.get("expires_at"),
        last_used=key.get("last_used")
    )


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
    from bson import ObjectId
    
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
    from bson import ObjectId
    
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
        {"$set": {"disabled": True, "disabled_at": datetime.utcnow()}}
    )
    
    # Fetch updated key
    key = await db.api_keys.find_one({"_id": ObjectId(key_id)})
    
    return APIKeyResponse(
        id=str(key["_id"]),
        name=key["name"],
        key_preview=f"{key['key_prefix']}...****",
        brand_id=key.get("brand_id"),
        permissions=[Permission(p) for p in key["permissions"]],
        created_at=key["created_at"],
        expires_at=key.get("expires_at"),
        last_used=key.get("last_used")
    )
