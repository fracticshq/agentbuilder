"""
Rate limiting implementation using Redis.

Fail-open policy
----------------
When Redis is unavailable, ``check_rate_limit`` returns (True, ...) — i.e. all
requests are allowed through.  This is an intentional availability-over-security
trade-off: a Redis outage should not take down the chat widget for end users.

Implications to be aware of:
- During a Redis outage, per-user and per-IP limits are NOT enforced.
- An attacker who can trigger a Redis failure (e.g. OOM, network partition)
  can bypass rate limiting for the duration of the outage.
- Every fail-open event is logged at WARNING level with ``event=rate_limiter_fail_open``
  so alerts/dashboards can detect and page on Redis connectivity issues.

If stricter behaviour is required, replace the ``return True, {...}`` in
``check_rate_limit``'s except block with a 503 raise.
"""

import time
from typing import Optional
from fastapi import HTTPException, status
from redis import asyncio as aioredis
from starlette.requests import HTTPConnection
import structlog

from ..auth.api_keys import extract_key_id
from ..auth.jwt import decode_and_verify_token
from ..config import Settings
from ..connections import connection_manager

logger = structlog.get_logger()
settings = Settings()


class RateLimiter:
    """
    Redis-based rate limiter using sliding window algorithm.
    """
    
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        """
        Initialize rate limiter.
        
        Args:
            redis_client: Redis client (optional, will use connection_manager if not provided)
        """
        self.redis = redis_client
    
    async def _get_redis(self) -> aioredis.Redis:
        """Get Redis client."""
        if self.redis is None:
            self.redis = await connection_manager.get_redis()
        return self.redis
    
    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int,
        cost: int = 1
    ) -> tuple[bool, dict]:
        """
        Check if request is within rate limit using sliding window.
        
        Args:
            key: Unique identifier (user_id, api_key, ip, etc.)
            limit: Maximum requests allowed in window
            window: Time window in seconds
            cost: Cost of this request (default 1)
        
        Returns:
            Tuple of (is_allowed, info_dict)
            info_dict contains: remaining, reset_at, limit
        """
        redis = await self._get_redis()
        now = time.time()
        window_start = now - window
        
        # Redis key for rate limiting
        rate_key = f"rate_limit:{key}"
        
        try:
            # Use pipeline for atomic operations
            pipe = redis.pipeline()
            
            # Remove old entries outside the window
            pipe.zremrangebyscore(rate_key, 0, window_start)
            
            # Count requests in current window
            pipe.zcard(rate_key)
            
            # Add current request with score as timestamp
            pipe.zadd(rate_key, {f"{now}:{cost}": now})
            
            # Set expiration on the key
            pipe.expire(rate_key, window + 1)
            
            # Execute pipeline
            results = await pipe.execute()
            
            current_count = results[1]
            
            # Check if limit exceeded
            is_allowed = current_count + cost <= limit
            remaining = max(0, limit - current_count - cost)
            reset_at = int(now + window)
            
            info = {
                "limit": limit,
                "remaining": remaining,
                "reset_at": reset_at,
                "retry_after": window if not is_allowed else None
            }
            
            if not is_allowed:
                logger.warning(
                    "rate_limit_exceeded",
                    key=key,
                    limit=limit,
                    current=current_count,
                    window=window
                )
            
            return is_allowed, info
            
        except Exception as e:
            # FAIL-OPEN: Redis is unavailable — allow the request through.
            # See module docstring for trade-offs and alerting guidance.
            logger.warning(
                "rate_limiter_fail_open",
                event="rate_limiter_fail_open",
                error=str(e),
                key=key,
                note="rate limiting bypassed — Redis unreachable",
            )
            return True, {
                "limit": limit,
                "remaining": limit,
                "reset_at": int(now + window),
                "retry_after": None
            }
    
    async def check_user_rate_limit(
        self,
        user_id: str,
        endpoint: Optional[str] = None,
        limit: Optional[int] = None,
        window: int = 60
    ) -> tuple[bool, dict]:
        """
        Check rate limit for a user.
        
        Args:
            user_id: User ID
            endpoint: Specific endpoint (optional)
            limit: Custom limit (uses default if not provided)
            window: Time window in seconds
        
        Returns:
            Tuple of (is_allowed, info_dict)
        """
        if limit is None:
            limit = settings.RATE_LIMIT_REQUESTS_PER_MINUTE
        
        key = f"user:{user_id}"
        if endpoint:
            key += f":{endpoint}"
        key += f":{window}"
        
        return await self.check_rate_limit(key, limit, window)
    
    async def check_api_key_rate_limit(
        self,
        api_key_id: str,
        limit: int,
        window: int = 60
    ) -> tuple[bool, dict]:
        """
        Check rate limit for an API key.
        
        Args:
            api_key_id: API key ID
            limit: Rate limit
            window: Time window in seconds
        
        Returns:
            Tuple of (is_allowed, info_dict)
        """
        key = f"api_key:{api_key_id}:{window}"
        return await self.check_rate_limit(key, limit, window)
    
    async def check_ip_rate_limit(
        self,
        ip_address: str,
        limit: int = 100,
        window: int = 60
    ) -> tuple[bool, dict]:
        """
        Check rate limit for an IP address.
        
        Args:
            ip_address: Client IP address
            limit: Rate limit
            window: Time window in seconds
        
        Returns:
            Tuple of (is_allowed, info_dict)
        """
        key = f"ip:{ip_address}:{window}"
        return await self.check_rate_limit(key, limit, window)
    
    async def get_usage(self, key: str, window: int = 60) -> dict:
        """
        Get current usage for a key.
        
        Args:
            key: Rate limit key
            window: Time window in seconds
        
        Returns:
            Dict with usage information
        """
        redis = await self._get_redis()
        rate_key = f"rate_limit:{key}"
        
        try:
            now = time.time()
            window_start = now - window
            
            # Count requests in current window
            count = await redis.zcount(rate_key, window_start, now)
            
            return {
                "requests": count,
                "window": window,
                "window_start": window_start,
                "window_end": now
            }
            
        except Exception as e:
            logger.error("get_usage_failed", error=str(e), key=key)
            return {
                "requests": 0,
                "window": window,
                "error": str(e)
            }
    
    async def reset_rate_limit(self, key: str) -> bool:
        """
        Reset rate limit for a key.
        
        Args:
            key: Rate limit key
        
        Returns:
            True if successful
        """
        redis = await self._get_redis()
        rate_key = f"rate_limit:{key}"
        
        try:
            await redis.delete(rate_key)
            logger.info("rate_limit_reset", key=key)
            return True
            
        except Exception as e:
            logger.error("rate_limit_reset_failed", error=str(e), key=key)
            return False


# Global rate limiter instance
rate_limiter = RateLimiter()


async def check_rate_limit(
    user_id: Optional[str] = None,
    api_key_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    limit: Optional[int] = None,
    window: int = 60
) -> tuple[bool, dict]:
    """
    Convenience function to check rate limit.
    
    Args:
        user_id: User ID (optional)
        api_key_id: API key ID (optional)
        ip_address: IP address (optional)
        endpoint: Endpoint name (optional)
        limit: Custom limit (optional)
        window: Time window in seconds
    
    Returns:
        Tuple of (is_allowed, info_dict)
    """
    # Priority: API key > User > IP
    if api_key_id:
        return await rate_limiter.check_api_key_rate_limit(api_key_id, limit or 60, window)
    elif user_id:
        return await rate_limiter.check_user_rate_limit(user_id, endpoint, limit, window)
    elif ip_address:
        return await rate_limiter.check_ip_rate_limit(ip_address, limit or 100, window)
    else:
        # No identifier provided, allow by default
        return True, {"limit": 0, "remaining": 0, "reset_at": 0, "retry_after": None}


async def rate_limit_dependency(connection: HTTPConnection):
    """
    FastAPI dependency for rate limiting.
    
    Usage:
        @router.get("/endpoint", dependencies=[Depends(rate_limit_dependency)])
        async def endpoint():
            ...
    """
    # Extract identifiers from request headers so the limiter works globally,
    # even on routes that do not depend on the auth helpers.
    user_id = getattr(connection.state, "user_id", None)
    if user_id is None:
        auth_header = connection.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            payload = decode_and_verify_token(token, token_type="access")
            if payload and payload.get("user_id"):
                user_id = str(payload["user_id"])
                connection.state.user_id = user_id

    api_key_id = getattr(connection.state, "api_key_id", None)
    if api_key_id is None:
        api_key = connection.headers.get("X-API-Key")
        parsed_key_id = extract_key_id(api_key) if api_key else None
        if parsed_key_id:
            api_key_id = parsed_key_id
            connection.state.api_key_id = api_key_id

    ip_address = connection.client.host if connection.client else None
    connection_method = getattr(connection, "method", connection.scope["type"].upper())
    endpoint = f"{connection_method}:{connection.url.path}"

    async def _enforce(identifier_type: str, **kwargs) -> dict:
        is_allowed, info = await check_rate_limit(endpoint=endpoint, **kwargs)
        if not is_allowed:
            logger.warning(
                "rate_limit_blocked",
                identifier_type=identifier_type,
                endpoint=endpoint,
                user_id=user_id,
                api_key_id=api_key_id,
                ip_address=ip_address,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={
                    "X-RateLimit-Limit": str(info["limit"]),
                    "X-RateLimit-Remaining": str(info["remaining"]),
                    "X-RateLimit-Reset": str(info["reset_at"]),
                    "Retry-After": str(info["retry_after"]) if info["retry_after"] else "60"
                }
            )
        return info

    # Always enforce an IP bucket so invalid or spoofed auth headers cannot
    # escape throttling by inventing fresh identifiers.
    rate_limit_info = await _enforce(
        "ip",
        ip_address=ip_address,
        limit=settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
    )

    if api_key_id:
        rate_limit_info = await _enforce(
            "api_key",
            api_key_id=api_key_id,
            limit=settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
        )
    elif user_id:
        rate_limit_info = await _enforce(
            "user",
            user_id=user_id,
            limit=settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
        )

    connection.state.rate_limit_info = rate_limit_info
