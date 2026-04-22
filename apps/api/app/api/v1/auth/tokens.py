"""
Token refresh and management endpoints.
"""

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from datetime import datetime

from ....auth.jwt import create_access_token, decode_and_verify_token
from ....auth.password import verify_password
from ....auth.models import User
from ....auth.dependencies import get_db

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
    payload = decode_and_verify_token(request.refresh_token, token_type="refresh")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Check if refresh token is revoked
    refresh_tokens = await db.refresh_tokens.find({
        "user_id": str(user_id),
        "is_revoked": False,
    }).to_list(length=20)
    matching_token = next(
        (
            token_doc for token_doc in refresh_tokens
            if verify_password(request.refresh_token, token_doc["token_hash"])
        ),
        None,
    )
    if matching_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked or is unknown",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_doc = await db.users.find_one({"_id": ObjectId(str(user_id))})
    if not user_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user = User(**user_doc)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    access_token = create_access_token(
        data={
            "user_id": str(user.id),
            "email": user.email,
            "role": user.role.value,
            "brands": user.brands,
        }
    )

    await db.refresh_tokens.update_one(
        {"_id": matching_token["_id"]},
        {"$set": {"last_used": datetime.utcnow()}}
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
    payload = decode_and_verify_token(request.refresh_token, token_type="refresh")
    if not payload or not payload.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    refresh_tokens = await db.refresh_tokens.find({
        "user_id": str(payload["user_id"]),
        "is_revoked": False,
    }).to_list(length=20)
    matching_token = next(
        (
            token_doc for token_doc in refresh_tokens
            if verify_password(request.refresh_token, token_doc["token_hash"])
        ),
        None,
    )
    if matching_token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Refresh token not found"
        )

    await db.refresh_tokens.update_one(
        {"_id": matching_token["_id"]},
        {
            "$set": {
                "is_revoked": True,
                "revoked_at": datetime.utcnow()
            }
        }
    )

    return {"message": "Refresh token revoked successfully"}
