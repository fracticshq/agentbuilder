"""
Application Middleware
"""

import time
import uuid
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from .config import Settings
from .monitoring import REQUEST_COUNT, REQUEST_DURATION

logger = structlog.get_logger()
settings = Settings()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add baseline security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class TrustedHostMiddleware(BaseHTTPMiddleware):
    """Reject requests for unexpected host headers in production."""

    async def dispatch(self, request: Request, call_next):
        allowed_hosts = {host.replace('https://', '').replace('http://', '').split('/')[0] for host in settings.CORS_ALLOW_ORIGINS}
        allowed_hosts.update({"localhost", "127.0.0.1"})
        host = request.headers.get("host", "").split(":")[0]
        if settings.is_production and allowed_hosts and host not in allowed_hosts:
            return await self._reject(request)
        return await call_next(request)

    async def _reject(self, request: Request):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"detail": "Invalid host header"})


logger = structlog.get_logger()
settings = Settings()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add request ID to all requests."""
    
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests and responses."""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        logger.info(
            "Request started",
            method=request.method,
            path=request.url.path,
            request_id=getattr(request.state, "request_id", None)
        )
        
        response = await call_next(request)
        
        process_time = time.time() - start_time
        endpoint = request.scope.get("route").path if request.scope.get("route") else request.url.path
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            status=str(response.status_code),
        ).inc()
        REQUEST_DURATION.labels(
            method=request.method,
            endpoint=endpoint,
        ).observe(process_time)

        logger.info(
            "Request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            process_time=process_time,
            request_id=getattr(request.state, "request_id", None)
        )

        rate_limit_info = getattr(request.state, "rate_limit_info", None)
        if rate_limit_info:
            response.headers.setdefault("X-RateLimit-Limit", str(rate_limit_info["limit"]))
            response.headers.setdefault("X-RateLimit-Remaining", str(rate_limit_info["remaining"]))
            response.headers.setdefault("X-RateLimit-Reset", str(rate_limit_info["reset_at"]))
            retry_after = rate_limit_info.get("retry_after")
            if retry_after:
                response.headers.setdefault("Retry-After", str(retry_after))
        
        response.headers["X-Process-Time"] = str(process_time)
        return response


def setup_middleware(app: FastAPI):
    """Setup application middleware."""
    app.add_middleware(TrustedHostMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)
