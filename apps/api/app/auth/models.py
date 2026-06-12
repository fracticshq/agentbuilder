"""
Authentication data models.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, model_validator
from bson import ObjectId


class UserRole(str, Enum):
    """User roles for RBAC."""
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    ORG_ADMIN = "org_admin"
    BRAND_ADMIN = "brand_admin"
    OPERATOR = "operator"
    USER = "user"
    VIEWER = "viewer"


class Permission(str, Enum):
    """System permissions."""
    # Brand permissions
    BRAND_READ = "brand:read"
    BRAND_WRITE = "brand:write"
    BRAND_DELETE = "brand:delete"
    
    # Agent permissions
    AGENT_READ = "agent:read"
    AGENT_WRITE = "agent:write"
    AGENT_DELETE = "agent:delete"
    
    # Document permissions
    DOCUMENT_READ = "document:read"
    DOCUMENT_WRITE = "document:write"
    DOCUMENT_DELETE = "document:delete"
    
    # Message permissions
    MESSAGE_READ = "message:read"
    MESSAGE_WRITE = "message:write"
    
    # API Key permissions
    API_KEY_READ = "api_key:read"
    API_KEY_WRITE = "api_key:write"
    API_KEY_DELETE = "api_key:delete"
    
    # User management permissions
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_DELETE = "user:delete"
    
    # System permissions
    SYSTEM_ADMIN = "system:admin"


# Role to permissions mapping
ADMIN_PERMISSIONS = [
    Permission.BRAND_READ, Permission.BRAND_WRITE, Permission.BRAND_DELETE,
    Permission.AGENT_READ, Permission.AGENT_WRITE, Permission.AGENT_DELETE,
    Permission.DOCUMENT_READ, Permission.DOCUMENT_WRITE, Permission.DOCUMENT_DELETE,
    Permission.MESSAGE_READ, Permission.MESSAGE_WRITE,
    Permission.API_KEY_READ, Permission.API_KEY_WRITE, Permission.API_KEY_DELETE,
    Permission.USER_READ, Permission.USER_WRITE, Permission.USER_DELETE,
    Permission.SYSTEM_ADMIN,
]

BRAND_ADMIN_PERMISSIONS = [
    Permission.BRAND_READ, Permission.BRAND_WRITE,
    Permission.AGENT_READ, Permission.AGENT_WRITE, Permission.AGENT_DELETE,
    Permission.DOCUMENT_READ, Permission.DOCUMENT_WRITE, Permission.DOCUMENT_DELETE,
    Permission.MESSAGE_READ, Permission.MESSAGE_WRITE,
    Permission.API_KEY_READ, Permission.API_KEY_WRITE, Permission.API_KEY_DELETE,
]

OPERATOR_PERMISSIONS = [
    Permission.BRAND_READ,
    Permission.AGENT_READ,
    Permission.DOCUMENT_READ,
    Permission.MESSAGE_READ, Permission.MESSAGE_WRITE,
]


GLOBAL_ADMIN_ROLES = {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.ORG_ADMIN}


ROLE_PERMISSIONS = {
    UserRole.SUPER_ADMIN: ADMIN_PERMISSIONS,
    UserRole.ADMIN: ADMIN_PERMISSIONS,
    UserRole.ORG_ADMIN: ADMIN_PERMISSIONS,
    UserRole.BRAND_ADMIN: BRAND_ADMIN_PERMISSIONS,
    UserRole.OPERATOR: OPERATOR_PERMISSIONS,
    UserRole.USER: [
        Permission.BRAND_READ,
        Permission.AGENT_READ, Permission.AGENT_WRITE,
        Permission.DOCUMENT_READ, Permission.DOCUMENT_WRITE,
        Permission.MESSAGE_READ, Permission.MESSAGE_WRITE,
        Permission.API_KEY_READ, Permission.API_KEY_WRITE,
    ],
    UserRole.VIEWER: [
        Permission.BRAND_READ,
        Permission.AGENT_READ,
        Permission.DOCUMENT_READ,
        Permission.MESSAGE_READ,
    ],
}


class User(BaseModel):
    """User model."""
    id: Optional[str] = Field(default=None, alias="_id")
    email: EmailStr
    username: str
    password_hash: str
    full_name: Optional[str] = None
    role: UserRole = UserRole.USER
    brands: List[str] = Field(default_factory=list)  # Brand IDs
    is_active: bool = True
    is_verified: bool = False
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None
    last_login: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)
    
    class Config:
        populate_by_name = True
        json_encoders = {
            ObjectId: str,
            datetime: lambda v: v.isoformat()
        }

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data):
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        if isinstance(normalized.get("_id"), ObjectId):
            normalized["_id"] = str(normalized["_id"])
        if "password_hash" not in normalized and normalized.get("hashed_password"):
            normalized["password_hash"] = normalized["hashed_password"]
        if "brands" not in normalized:
            brand_id = normalized.get("brand_id")
            normalized["brands"] = [brand_id] if brand_id else []
        if "is_active" not in normalized:
            normalized["is_active"] = not normalized.get("disabled", False)
        if "locked_until" not in normalized and normalized.get("account_locked_until"):
            normalized["locked_until"] = normalized["account_locked_until"]
        if "is_verified" not in normalized:
            normalized["is_verified"] = normalized.get("verified", False)
        return normalized
    
    def has_permission(self, permission: Permission) -> bool:
        """Check if user has a specific permission."""
        return permission in ROLE_PERMISSIONS.get(self.role, [])
    
    def has_brand_access(self, brand_id: str) -> bool:
        """Check if user has access to a specific brand."""
        if self.role in GLOBAL_ADMIN_ROLES:
            return True
        return brand_id in self.brands
    
    def is_locked(self) -> bool:
        """Check if account is locked."""
        if self.locked_until is None:
            return False
        return datetime.utcnow() < self.locked_until


class UserInDB(User):
    """User model as stored in database (includes password hash)."""
    pass


class UserCreate(BaseModel):
    """User creation model."""
    email: EmailStr
    username: str
    password: str
    full_name: Optional[str] = None
    role: UserRole = UserRole.USER
    brands: List[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    """User update model."""
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    brands: Optional[List[str]] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """User response model (excludes password)."""
    id: str = Field(alias="_id")
    email: EmailStr
    username: str
    full_name: Optional[str]
    role: UserRole
    brands: List[str]
    is_active: bool
    is_verified: bool
    last_login: Optional[datetime]
    created_at: datetime
    
    class Config:
        populate_by_name = True


class Token(BaseModel):
    """Token response model."""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int  # seconds


class TokenData(BaseModel):
    """Token payload data."""
    user_id: str
    email: str
    role: UserRole
    brands: List[str]
    exp: int  # Expiration timestamp


class RefreshToken(BaseModel):
    """Refresh token model."""
    id: Optional[str] = Field(default=None, alias="_id")
    token_hash: str
    user_id: str
    expires_at: datetime
    is_revoked: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked_at: Optional[datetime] = None
    device_info: Optional[str] = None
    
    class Config:
        populate_by_name = True


class APIKey(BaseModel):
    """API Key model."""
    id: Optional[str] = Field(default=None, alias="_id")
    key_id: str  # First 8 chars of key (public identifier)
    key_hash: str  # Hashed full key
    user_id: str
    name: str
    scopes: List[str] = Field(default_factory=list)  # Permissions
    brand_ids: List[str] = Field(default_factory=list)  # Accessible brands
    rate_limit: dict = Field(default_factory=lambda: {
        "requests_per_minute": 60,
        "requests_per_day": 10000
    })
    usage: dict = Field(default_factory=lambda: {
        "total_requests": 0,
        "last_used": None
    })
    is_active: bool = True
    expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked_at: Optional[datetime] = None
    
    class Config:
        populate_by_name = True

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data):
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        if isinstance(normalized.get("_id"), ObjectId):
            normalized["_id"] = str(normalized["_id"])
        if "key_id" not in normalized and normalized.get("key_prefix"):
            normalized["key_id"] = normalized["key_prefix"]
        if "scopes" not in normalized and normalized.get("permissions"):
            normalized["scopes"] = normalized["permissions"]
        if "brand_ids" not in normalized and normalized.get("brand_id"):
            normalized["brand_ids"] = [normalized["brand_id"]]
        if "is_active" not in normalized:
            normalized["is_active"] = not normalized.get("disabled", False)
        if "revoked_at" not in normalized and normalized.get("disabled_at"):
            normalized["revoked_at"] = normalized["disabled_at"]
        if "usage" not in normalized:
            normalized["usage"] = {
                "total_requests": normalized.get("total_requests", 0),
                "last_used": normalized.get("last_used"),
            }
        return normalized
    
    def is_expired(self) -> bool:
        """Check if API key is expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if API key is valid."""
        return self.is_active and not self.is_expired()


class APIKeyCreate(BaseModel):
    """API Key creation model."""
    name: str
    scopes: List[str] = Field(default_factory=list)
    brand_ids: List[str] = Field(default_factory=list)
    expires_in_days: Optional[int] = 365


class APIKeyResponse(BaseModel):
    """API Key response model."""
    id: str = Field(alias="_id")
    key_id: str
    key: Optional[str] = None  # Only returned on creation
    name: str
    scopes: List[str]
    brand_ids: List[str]
    rate_limit: dict
    usage: dict
    is_active: bool
    expires_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        populate_by_name = True


class LoginRequest(BaseModel):
    """Login request model."""
    username: str  # Can be email or username
    password: str


class RefreshTokenRequest(BaseModel):
    """Refresh token request."""
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    """Password change request."""
    old_password: str
    new_password: str


class PasswordResetRequest(BaseModel):
    """Password reset request."""
    email: EmailStr
