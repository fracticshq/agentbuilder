"""
Authentication helpers shared across auth endpoints.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..config import Settings
from .jwt import create_access_token, create_refresh_token
from .models import Token, UserRole
from .password import hash_password


def _normalize_object_id(value: str | ObjectId) -> str:
    return str(value)


async def is_signup_open(db: AsyncIOMotorDatabase, settings: Settings) -> bool:
    """Allow bootstrap signup for the first operator, then honor explicit config only."""
    if settings.ALLOW_PUBLIC_SIGNUP:
        return True
    existing_user = await db.users.find_one({}, projection={"_id": 1})
    return existing_user is None


async def generate_unique_username(
    db: AsyncIOMotorDatabase,
    email: str,
    requested_username: Optional[str] = None,
) -> str:
    """Create a unique username, preferring the requested value when possible."""
    base = (requested_username or email.split("@", 1)[0]).strip().lower()
    sanitized = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in base).strip("-._")
    candidate = sanitized or "user"
    suffix = 1

    while await db.users.find_one({"username": candidate}, projection={"_id": 1}):
        suffix += 1
        candidate = f"{sanitized or 'user'}-{suffix}"

    return candidate


async def resolve_signup_role(db: AsyncIOMotorDatabase) -> UserRole:
    """Bootstrap the very first operator as an admin."""
    existing_user = await db.users.find_one({}, projection={"_id": 1})
    return UserRole.ADMIN if existing_user is None else UserRole.USER


async def issue_user_tokens(
    db: AsyncIOMotorDatabase,
    settings: Settings,
    user_doc: dict[str, Any],
) -> Token:
    """Mint access + refresh tokens and persist the refresh token hash."""
    user_id = _normalize_object_id(user_doc.get("_id") or user_doc.get("id"))
    role_value = user_doc.get("role", UserRole.USER.value)
    role = role_value.value if isinstance(role_value, UserRole) else str(role_value)
    brands = user_doc.get("brands", [])

    access_token = create_access_token(
        {
            "user_id": user_id,
            "email": user_doc["email"],
            "role": role,
            "brands": brands,
        }
    )
    refresh_token = create_refresh_token({"user_id": user_id})

    await db.refresh_tokens.insert_one(
        {
            "token_hash": hash_password(refresh_token),
            "user_id": user_id,
            "expires_at": datetime.utcnow() + timedelta(days=7),
            "is_revoked": False,
            "created_at": datetime.utcnow(),
            "device_info": None,
        }
    )

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

