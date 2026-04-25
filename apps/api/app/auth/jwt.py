"""
JWT token operations.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
import structlog

from ..config import Settings

logger = structlog.get_logger()
settings = Settings()


def create_signed_token(
    data: Dict[str, Any],
    token_type: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT token for the given token type."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": token_type
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm="HS256"
    )

    return encoded_jwt


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Data to encode in the token
        expires_delta: Custom expiration time (optional)
    
    Returns:
        Encoded JWT token
    """
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    encoded_jwt = create_signed_token(data, "access", expires_delta)

    logger.debug(
        "access_token_created",
        user_id=data.get("user_id"),
        expires=expire.isoformat()
    )
    
    return encoded_jwt


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT refresh token.
    
    Args:
        data: Data to encode in the token
        expires_delta: Custom expiration time (optional)
    
    Returns:
        Encoded JWT refresh token
    """
    expire = datetime.utcnow() + (expires_delta or timedelta(days=7))
    encoded_jwt = create_signed_token(
        data,
        "refresh",
        expires_delta or timedelta(days=7),
    )
    
    logger.debug(
        "refresh_token_created",
        user_id=data.get("user_id"),
        expires=expire.isoformat()
    )
    
    return encoded_jwt


def verify_token(token: str, token_type: str = "access") -> bool:
    """
    Verify if a JWT token is valid.
    
    Args:
        token: JWT token to verify
        token_type: Expected token type (access or refresh)
    
    Returns:
        True if valid, False otherwise
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        
        # Check token type
        if payload.get("type") != token_type:
            logger.warning(
                "token_type_mismatch",
                expected=token_type,
                actual=payload.get("type")
            )
            return False
        
        # Check expiration
        exp = payload.get("exp")
        if exp is None:
            return False
        
        if datetime.fromtimestamp(exp) < datetime.utcnow():
            logger.debug("token_expired", exp=exp)
            return False
        
        return True
        
    except JWTError as e:
        logger.warning("token_validation_failed", error=str(e))
        return False


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode a JWT token without verification.
    
    Args:
        token: JWT token to decode
    
    Returns:
        Token payload or None if invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        return payload
        
    except JWTError as e:
        logger.warning("token_decode_failed", error=str(e))
        return None


def decode_and_verify_token(token: str, token_type: str = "access") -> Optional[Dict[str, Any]]:
    """
    Decode and verify a JWT token.
    
    Args:
        token: JWT token
        token_type: Expected token type
    
    Returns:
        Token payload if valid, None otherwise
    """
    if not verify_token(token, token_type):
        return None
    
    return decode_token(token)


def get_token_expiry(token: str) -> Optional[datetime]:
    """
    Get the expiration time of a token.
    
    Args:
        token: JWT token
    
    Returns:
        Expiration datetime or None
    """
    payload = decode_token(token)
    if payload is None:
        return None
    
    exp = payload.get("exp")
    if exp is None:
        return None
    
    return datetime.fromtimestamp(exp)


def is_token_expired(token: str) -> bool:
    """
    Check if a token is expired.
    
    Args:
        token: JWT token
    
    Returns:
        True if expired, False otherwise
    """
    expiry = get_token_expiry(token)
    if expiry is None:
        return True
    
    return datetime.utcnow() > expiry
