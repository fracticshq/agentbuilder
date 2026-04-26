"""
FastAPI Application Entry Point
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from .config import Settings
from .api.v1 import api_router
from .middleware import setup_middleware
from .monitoring import setup_monitoring
from .connections import connection_manager
from .services.runtime_settings_service import RuntimeSettingsService

# Configure structured logging
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Global settings
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Agent Builder API", version="1.0.0", environment=settings.ENVIRONMENT)

    logger.info("Connecting to databases...")
    await connection_manager.connect_mongodb()
    await connection_manager.connect_redis()

    if connection_manager.system_db is not None:
        try:
            logger.info("Setting up MongoDB indexes...")
            system_db = connection_manager.system_db

            try:
                await system_db.brands.create_index("id", unique=True, name="brand_id_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

            try:
                await system_db.brands.create_index("slug", unique=True, name="brand_slug_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

            try:
                await system_db.agents.create_index("id", unique=True, name="agent_id_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

            try:
                await system_db.agents.create_index("brand_id", name="agent_brand_id_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

            try:
                await system_db.agents.create_index([("brand_id", 1), ("slug", 1)], unique=True, name="agent_brand_slug_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

            try:
                await system_db.users.create_index("email", unique=True, name="users_email_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

            try:
                await system_db.users.create_index("username", unique=True, name="users_username_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

            try:
                await system_db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0, name="password_reset_expiry_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

            try:
                await RuntimeSettingsService(settings).ensure_indexes()
            except Exception as e:
                if "already exists" not in str(e):
                    raise

            try:
                await system_db.audit_logs.create_index("created_at", name="audit_logs_created_at_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

            logger.info("MongoDB indexes setup complete")
        except Exception as e:
            logger.error("Failed to setup MongoDB indexes", error=str(e))

    health = await connection_manager.health_check()
    app.state.startup_health = health
    logger.info("Connection health check", **health)

    yield

    logger.info("Shutting down Agent Builder API")
    await connection_manager.close_all()


def _is_origin_allowed(origin: str) -> bool:
    return origin in settings.CORS_ALLOW_ORIGINS


def _has_wildcard_origin() -> bool:
    return "*" in settings.CORS_ALLOW_ORIGINS


def _health_status(health: dict) -> str:
    if settings.REQUIRE_MONGODB and health.get("mongodb") != "healthy":
        return "unhealthy"
    if settings.REQUIRE_REDIS and health.get("redis") != "healthy":
        return "unhealthy"
    return "healthy"


def _validate_startup_security() -> None:
    if settings.is_production:
        if settings.DEBUG:
            raise RuntimeError("DEBUG must be false in production")
        if not settings.ADMIN_API_KEY and not settings.ALLOW_ADMIN_KEY_BYPASS:
            raise RuntimeError("ADMIN_API_KEY must be configured in production")
        if _has_wildcard_origin():
            raise RuntimeError("Wildcard CORS origins are not allowed in production")


_validate_startup_security()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""

    app = FastAPI(
        title="Agent Builder Platform API",
        description="Context-aware RAG assistant with brand-safe, citation-first answers",
        version="1.0.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOW_ORIGINS,
        allow_credentials=not _has_wildcard_origin(),
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Admin-Key", "X-Request-ID"],
    )
    
    # Custom middleware
    setup_middleware(app)
    setup_monitoring(app)
    
    # Include API routes
    app.include_router(api_router, prefix="/api/v1")
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        health = await connection_manager.health_check()
        status = _health_status(health)
        return {
            "status": status,
            "service": "agent-builder-api",
            "environment": settings.ENVIRONMENT,
            "dependencies": health,
        }

    @app.get("/ready")
    async def readiness_check():
        """Readiness endpoint for deploy orchestration."""
        health = await connection_manager.health_check()
        status = _health_status(health)
        if status != "healthy":
            return JSONResponse(status_code=503, content={
                "status": status,
                "service": "agent-builder-api",
                "environment": settings.ENVIRONMENT,
                "dependencies": health,
            })
        return {
            "status": status,
            "service": "agent-builder-api",
            "environment": settings.ENVIRONMENT,
            "dependencies": health,
        }

    @app.get("/live")
    async def liveness_check():
        return {"status": "alive", "service": "agent-builder-api"}

    @app.get("/config-check")
    async def config_check():
        return {
            "environment": settings.ENVIRONMENT,
            "debug": settings.DEBUG,
            "metrics_enabled": settings.ENABLE_METRICS,
            "websockets_enabled": settings.ENABLE_WEBSOCKETS,
            "mongodb_required": settings.REQUIRE_MONGODB,
            "redis_required": settings.REQUIRE_REDIS,
            "admin_key_configured": bool(settings.ADMIN_API_KEY),
            "admin_key_bypass_allowed": settings.ALLOW_ADMIN_KEY_BYPASS,
            "cors_origins": settings.CORS_ALLOW_ORIGINS,
        }
    
    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler."""
        logger.error("Unhandled exception", exc_info=exc, path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": "An unexpected error occurred"}
        )
    
    # Instrument with OpenTelemetry only when tracing is explicitly enabled.
    if settings.ENABLE_TRACING:
        FastAPIInstrumentor.instrument_app(app)
    
    return app


# Create the app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
        log_level=settings.API_LOG_LEVEL.lower()
    )
