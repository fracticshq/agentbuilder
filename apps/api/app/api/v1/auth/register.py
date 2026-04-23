"""
User registration endpoint.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

from ....config import Settings
from ....auth.models import User, UserRole
from ....auth.password import hash_password, validate_password_strength
from ....auth.dependencies import get_db
from ....auth.service import generate_unique_username, is_signup_open, resolve_signup_role

router = APIRouter()


class RegisterRequest(BaseModel):
    """User registration request."""
    email: EmailStr
    password: str = Field(..., min_length=8)
    username: Optional[str] = Field(default=None, min_length=3, max_length=50)
    full_name: Optional[str] = None
    brand_id: Optional[str] = None


class RegisterResponse(BaseModel):
    """User registration response."""
    id: str
    username: str
    email: str
    full_name: Optional[str]
    role: UserRole
    created_at: datetime
    message: str = "User registered successfully. Please login to continue."


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    request: RegisterRequest,
    db = Depends(get_db)
):
    """
    Register a new user.
    
    - **username**: Unique username (3-50 chars)
    - **email**: Valid email address
    - **password**: Strong password (min 8 chars)
    - **full_name**: Optional full name
    - **brand_id**: Optional brand association (for brand-specific users)
    """
    settings = Settings()
    if not await is_signup_open(db, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public signup is disabled. Ask an administrator to create your account."
        )

    # Validate password strength
    is_valid, error_msg = validate_password_strength(request.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # Check if username already exists
    if request.username:
        existing_user = await db.users.find_one({"username": request.username})
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already registered"
            )
    
    # Check if email already exists
    existing_email = await db.users.find_one({"email": request.email})
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    username = await generate_unique_username(db, request.email, request.username)
    role = await resolve_signup_role(db)

    # Hash password
    password_hash = hash_password(request.password)
    
    # Create user document
    user_doc = {
        "username": username,
        "email": request.email,
        "password_hash": password_hash,
        "full_name": request.full_name,
        "role": role.value,
        "brands": [request.brand_id] if request.brand_id else [],
        "is_active": True,
        "is_verified": False,
        "failed_login_attempts": 0,
        "locked_until": None,
        "last_login": None,
        "metadata": {},
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    # Insert user
    result = await db.users.insert_one(user_doc)
    user_doc["id"] = str(result.inserted_id)
    
    # Return response
    return RegisterResponse(
        id=user_doc["id"],
        username=username,
        email=user_doc["email"],
        full_name=user_doc.get("full_name"),
        role=role,
        created_at=user_doc["created_at"]
    )
