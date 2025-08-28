"""
Application Configuration
"""

import os
from typing import List
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""
    
    # API Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_LOG_LEVEL: str = "info"
    DEBUG: bool = False
    
    # CORS Configuration
    CORS_ALLOW_ORIGINS: List[str] = ["*"]
    
    # Database Configuration
    REDIS_URL: str = "redis://localhost:6379"
    MONGO_URI: str = "mongodb://localhost:27017/agent-builder"
    
    # LLM Configuration
    MODEL_PROVIDER: str = "qwen"
    MODEL_NAME: str = "qwen-turbo"
    API_KEY: str = ""
    
    # Embeddings Configuration
    EMBEDDINGS_PROVIDER: str = "voyage"
    EMBEDDINGS_API_KEY: str = ""
    
    # Memory Configuration
    MEMORY_TTL_HOURS: int = 72
    EPISODIC_CONFIDENCE_THRESHOLD: float = 0.70
    
    # Retrieval Configuration
    MAX_CHUNKS: int = 12
    VECTOR_SEARCH_LIMIT: int = 50
    BM25_SEARCH_LIMIT: int = 50
    
    # Security Configuration
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    @field_validator("CORS_ALLOW_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v
    
    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, v):
        """Parse DEBUG from string."""
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return v
    
    class Config:
        env_file = ".env"
        case_sensitive = True
