"""
User registration endpoint.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

from app.auth.models import User, UserRole
from app.auth.password import hash_password, validate_password_strength
from app.dependencies import get_db

router = APIRouter()


class RegisterRequest(BaseModel):
    """User registration request."""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
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
    # Validate password strength
    is_valid, error_msg = validate_password_strength(request.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # Check if username already exists
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
    
    # Hash password
    hashed_password = hash_password(request.password)
    
    # Create user document
    user_doc = {
        "username": request.username,
        "email": request.email,
        "hashed_password": hashed_password,
        "full_name": request.full_name,
        "role": UserRole.USER.value,  # Default role
        "brand_id": request.brand_id,
        "disabled": False,
        "failed_login_attempts": 0,
        "account_locked_until": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    # Insert user
    result = await db.users.insert_one(user_doc)
    user_doc["id"] = str(result.inserted_id)
    
    # Return response
    return RegisterResponse(
        id=user_doc["id"],
        username=user_doc["username"],
        email=user_doc["email"],
        full_name=user_doc.get("full_name"),
        role=UserRole(user_doc["role"]),
        created_at=user_doc["created_at"]
    )
