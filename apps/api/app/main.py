"""
FastAPI Application Entry Point
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from .config import Settings
from .api.v1 import api_router
from .middleware import setup_middleware
from .monitoring import setup_monitoring
from .connections import connection_manager

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
    logger.info("Starting Agent Builder API", version="1.0.0")
    
    # Setup monitoring and tracing
    setup_monitoring(app)
    
    # Initialize database connections
    logger.info("Connecting to databases...")
    await connection_manager.connect_mongodb()
    await connection_manager.connect_redis()
    
    # Setup MongoDB indexes for admin collections
    if connection_manager.mongodb_db is not None:
        try:
            logger.info("Setting up MongoDB indexes...")
            db = connection_manager.mongodb_db
            
            # Brand indexes (with proper names to avoid conflicts)
            try:
                await db.brands.create_index("id", unique=True, name="brand_id_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise
            
            try:
                await db.brands.create_index("slug", unique=True, name="brand_slug_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise
            
            # Agent indexes (with proper names to avoid conflicts)
            try:
                await db.agents.create_index("id", unique=True, name="agent_id_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise
                    
            try:
                await db.agents.create_index("brand_id", name="agent_brand_id_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise
                    
            try:
                await db.agents.create_index([("brand_id", 1), ("slug", 1)], unique=True, name="agent_brand_slug_idx")
            except Exception as e:
                if "already exists" not in str(e):
                    raise
            
            logger.info("MongoDB indexes created successfully")
        except Exception as e:
            logger.warning("Failed to create MongoDB indexes", error=str(e))
    
    # Check connection health
    health = await connection_manager.health_check()
    logger.info("Connection health check", **health)
    
    yield
    
    logger.info("Shutting down Agent Builder API")
    # Cleanup connections
    await connection_manager.close_all()


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
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Custom middleware
    setup_middleware(app)
    
    # Include API routes
    app.include_router(api_router, prefix="/api/v1")
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": "agent-builder-api"}
    
    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler."""
        logger.error("Unhandled exception", exc_info=exc, path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": "An unexpected error occurred"}
        )
    
    # Instrument with OpenTelemetry
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
