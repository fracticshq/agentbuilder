"""
Login endpoint.
"""

from datetime import datetime, timedelta
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
import structlog

from ....config import Settings
from ....auth import (
    verify_password,
    create_access_token,
    create_refresh_token,
    hash_password,
)
from ....auth.models import (
    LoginRequest,
    Token,
    User,
)
from ....auth.dependencies import get_db, get_current_active_user

logger = structlog.get_logger()
settings = Settings()

router = APIRouter()


@router.post("/login", response_model=Token)
async def login(
    request: LoginRequest,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    User login endpoint.
    
    Authenticates a user with username/email and password.
    Returns JWT access token and refresh token.
    
    Args:
        request: Login credentials
        db: Database connection
    
    Returns:
        JWT tokens
    
    Raises:
        HTTPException: If authentication fails
    """
    users_collection = db.users
    
    # Find user by username or email
    user_doc = await users_collection.find_one({
        "$or": [
            {"username": request.username},
            {"email": request.username}
        ]
    })
    
    if user_doc is None:
        logger.warning("login_failed_user_not_found", username=request.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    user = User(**user_doc)
    
    # Check if account is locked
    if user.is_locked():
        logger.warning("login_failed_account_locked", user_id=user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is locked until {user.locked_until.isoformat() if user.locked_until else 'unknown'}"
        )
    
    # Verify password
    if not verify_password(request.password, user.password_hash):
        # Increment failed login attempts
        failed_attempts = user.failed_login_attempts + 1
        
        update_data = {
            "failed_login_attempts": failed_attempts
        }
        
        # Lock account after 5 failed attempts
        if failed_attempts >= 5:
            locked_until = datetime.utcnow() + timedelta(minutes=15)
            update_data["locked_until"] = locked_until
            
            logger.warning(
                "account_locked_due_to_failed_attempts",
                user_id=user.id,
                failed_attempts=failed_attempts,
                locked_until=locked_until.isoformat()
            )
        
        await users_collection.update_one(
            {"_id": ObjectId(str(user.id))},
            {"$set": update_data}
        )
        
        logger.warning(
            "login_failed_invalid_password",
            user_id=user.id,
            failed_attempts=failed_attempts
        )
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    # Check if user is active
    if not user.is_active:
        logger.warning("login_failed_inactive_user", user_id=user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    # Successful login - reset failed attempts and update last login
    await users_collection.update_one(
        {"_id": ObjectId(str(user.id))},
        {
            "$set": {
                "failed_login_attempts": 0,
                "locked_until": None,
                "last_login": datetime.utcnow()
            }
        }
    )
    
    # Create tokens
    token_data = {
        "user_id": user.id,
        "email": user.email,
        "role": user.role.value,
        "brands": user.brands
    }
    
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"user_id": user.id})
    
    # Store refresh token in database
    refresh_tokens_collection = db.refresh_tokens
    await refresh_tokens_collection.insert_one({
        "token_hash": hash_password(refresh_token),  # Reuse password hash function
        "user_id": str(user.id),
        "expires_at": datetime.utcnow() + timedelta(days=7),
        "is_revoked": False,
        "created_at": datetime.utcnow(),
        "device_info": None  # Can be extracted from User-Agent header
    })
    
    logger.info(
        "user_logged_in",
        user_id=user.id,
        username=user.username,
        email=user.email
    )
    
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # Convert to seconds
    )


@router.post("/logout")
async def logout(
    user: User = Depends(get_current_active_user),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    User logout endpoint.
    
    Revokes all refresh tokens for the user.
    
    Args:
        user: Current authenticated user
        db: Database connection
    
    Returns:
        Success message
    """
    # Revoke all user's refresh tokens
    refresh_tokens_collection = db.refresh_tokens
    result = await refresh_tokens_collection.update_many(
        {"user_id": str(user.id), "is_revoked": False},
        {
            "$set": {
                "is_revoked": True,
                "revoked_at": datetime.utcnow()
            }
        }
    )
    
    logger.info(
        "user_logged_out",
        user_id=user.id,
        revoked_tokens=result.modified_count
    )
    
    return {
        "message": "Successfully logged out",
        "revoked_tokens": result.modified_count
    }
