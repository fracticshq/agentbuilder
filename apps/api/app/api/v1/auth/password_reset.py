"""
Password reset endpoints for the admin dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from ....config import Settings
from ....auth.jwt import create_signed_token, decode_and_verify_token
from ....auth.password import hash_password, validate_password_strength, verify_password
from ....auth.dependencies import get_db

router = APIRouter()


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_url: str | None = None


class ResetPasswordConfirmRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    request: ForgotPasswordRequest,
    db=Depends(get_db),
):
    settings = Settings()
    generic_response = ForgotPasswordResponse(
        message="If an account exists for that email, password reset instructions have been generated."
    )

    user_doc = await db.users.find_one({"email": request.email})
    if not user_doc:
        return generic_response

    expires_delta = timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
    expires_at = datetime.utcnow() + expires_delta
    token = create_signed_token(
        {
            "user_id": str(user_doc["_id"]),
            "email": user_doc["email"],
        },
        token_type="password_reset",
        expires_delta=expires_delta,
    )

    await db.password_reset_tokens.insert_one(
        {
            "token_hash": hash_password(token),
            "user_id": str(user_doc["_id"]),
            "email": user_doc["email"],
            "expires_at": expires_at,
            "used_at": None,
            "created_at": datetime.utcnow(),
        }
    )

    if settings.DEBUG:
        reset_url = f"{settings.ADMIN_APP_URL.rstrip('/')}/reset-password?token={token}"
        return ForgotPasswordResponse(
            message=generic_response.message,
            reset_url=reset_url,
        )

    return generic_response


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordConfirmRequest,
    db=Depends(get_db),
):
    payload = decode_and_verify_token(request.token, token_type="password_reset")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired password reset token",
        )

    is_valid, error_message = validate_password_strength(request.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )

    token_docs = await db.password_reset_tokens.find(
        {
            "user_id": str(payload["user_id"]),
            "used_at": None,
            "expires_at": {"$gt": datetime.utcnow()},
        }
    ).to_list(length=20)
    token_doc = next(
        (
            candidate
            for candidate in token_docs
            if verify_password(request.token, candidate["token_hash"])
        ),
        None,
    )
    if token_doc is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password reset token is invalid or has already been used",
        )

    await db.users.update_one(
        {"_id": ObjectId(str(payload["user_id"]))},
        {
            "$set": {
                "password_hash": hash_password(request.new_password),
                "updated_at": datetime.utcnow(),
                "failed_login_attempts": 0,
                "locked_until": None,
            }
        },
    )
    await db.password_reset_tokens.update_many(
        {"user_id": str(payload["user_id"]), "used_at": None},
        {"$set": {"used_at": datetime.utcnow()}},
    )
    await db.refresh_tokens.update_many(
        {"user_id": str(payload["user_id"]), "is_revoked": False},
        {"$set": {"is_revoked": True, "revoked_at": datetime.utcnow()}},
    )

    return {"message": "Password reset successfully. Please log in with your new password."}

