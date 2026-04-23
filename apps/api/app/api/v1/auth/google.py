"""
Google identity sign-in / sign-up endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ....config import Settings
from ....auth.dependencies import get_db
from ....auth.service import generate_unique_username, is_signup_open, issue_user_tokens, resolve_signup_role

router = APIRouter()


class GoogleAuthRequest(BaseModel):
    credential: str


class AuthConfigResponse(BaseModel):
    signup_enabled: bool
    google_enabled: bool
    google_client_id: str | None = None


def _verify_google_credential(credential: str, expected_client_id: str) -> dict[str, Any]:
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in support is not installed on the API server",
        ) from exc

    try:
        payload = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            expected_client_id,
        )
    except Exception as exc:  # pragma: no cover - provider library errors vary
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google credential",
        ) from exc

    if payload.get("email_verified") is not True:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account email is not verified",
        )

    return payload


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config(db=Depends(get_db)):
    settings = Settings()
    signup_enabled = await is_signup_open(db, settings)
    google_enabled = bool(settings.GOOGLE_CLIENT_ID)
    return AuthConfigResponse(
        signup_enabled=signup_enabled,
        google_enabled=google_enabled,
        google_client_id=settings.GOOGLE_CLIENT_ID or None,
    )


@router.post("/google")
async def google_login_or_signup(
    request: GoogleAuthRequest,
    db=Depends(get_db),
):
    settings = Settings()
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )

    payload = _verify_google_credential(request.credential, settings.GOOGLE_CLIENT_ID)
    email = payload["email"].lower()
    user_doc = await db.users.find_one({"email": email})

    if user_doc is None:
        if not await is_signup_open(db, settings):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Google signup is disabled. Ask an administrator to create your account.",
            )

        role = await resolve_signup_role(db)
        username = await generate_unique_username(db, email, payload.get("name"))
        now = datetime.utcnow()
        new_user = {
            "username": username,
            "email": email,
            "password_hash": "",
            "full_name": payload.get("name"),
            "role": role.value,
            "brands": [],
            "is_active": True,
            "is_verified": True,
            "failed_login_attempts": 0,
            "locked_until": None,
            "last_login": now,
            "metadata": {
                "auth_providers": ["google"],
                "google_sub": payload.get("sub"),
                "picture": payload.get("picture"),
            },
            "created_at": now,
            "updated_at": now,
        }
        result = await db.users.insert_one(new_user)
        user_doc = {**new_user, "_id": result.inserted_id}
    else:
        metadata = dict(user_doc.get("metadata", {}))
        auth_providers = set(metadata.get("auth_providers", []))
        auth_providers.add("google")
        metadata["auth_providers"] = sorted(auth_providers)
        metadata["google_sub"] = payload.get("sub")
        if payload.get("picture"):
            metadata["picture"] = payload.get("picture")

        await db.users.update_one(
            {"_id": user_doc["_id"]},
            {
                "$set": {
                    "is_verified": True,
                    "last_login": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "metadata": metadata,
                }
            },
        )
        user_doc = await db.users.find_one({"_id": user_doc["_id"]})

    token_response = await issue_user_tokens(db, settings, user_doc)
    return token_response

