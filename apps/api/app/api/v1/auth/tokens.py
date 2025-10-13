"""
Token refresh and management endpoints.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from datetime import datetime

from app.auth.jwt import create_access_token, verify_token
from app.auth.models import User
from app.dependencies import get_db

router = APIRouter()


class RefreshTokenRequest(BaseModel):
    """Token refresh request."""
    refresh_token: str


class TokenResponse(BaseModel):
    """Token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 1800  # 30 minutes in seconds


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    request: RefreshTokenRequest,
    db = Depends(get_db)
):
    """
    Refresh an access token using a valid refresh token.
    
    - **refresh_token**: Valid refresh token received during login
    
    Returns a new access token.
    """
    # Verify refresh token
    payload = verify_token(request.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Check token type
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. Expected refresh token.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Get user_id from payload
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Check if refresh token is revoked
    revoked_token = await db.refresh_tokens.find_one({
        "token": request.refresh_token,
        "revoked": True
    })
    if revoked_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Get user from database
    from bson import ObjectId
    user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Check if user is disabled
    if user_doc.get("disabled", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    # Create new access token
    access_token = create_access_token(
        data={
            "sub": str(user_doc["_id"]),
            "username": user_doc["username"],
            "role": user_doc["role"]
        }
    )
    
    # Update last_accessed timestamp for refresh token
    await db.refresh_tokens.update_one(
        {"token": request.refresh_token},
        {"$set": {"last_accessed": datetime.utcnow()}}
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=1800
    )


@router.post("/revoke")
async def revoke_refresh_token(
    request: RefreshTokenRequest,
    db = Depends(get_db)
):
    """
    Revoke a refresh token.
    
    - **refresh_token**: The refresh token to revoke
    """
    # Mark token as revoked
    result = await db.refresh_tokens.update_one(
        {"token": request.refresh_token},
        {
            "$set": {
                "revoked": True,
                "revoked_at": datetime.utcnow()
            }
        }
    )
    
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Refresh token not found"
        )
    
    return {"message": "Refresh token revoked successfully"}
