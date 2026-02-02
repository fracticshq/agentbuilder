import os
import logging
from typing import List, Optional
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

def fetch_akv_secrets(vault_name: str) -> dict:
    """Fetch secrets from Azure Key Vault."""
    secrets = {}
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
        
        vault_url = f"https://{vault_name}.vault.azure.net/"
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)
        
        # List of secrets we want to try and fetch if missing
        secret_keys = [
            "OPENAI-API-KEY",
            "VOYAGE-API-KEY",
            "MONGODB-URI",
            "SECRET-KEY",
            "PII-ENCRYPTION-KEY",
            "JWT-SECRET",
            "QWEN-API-KEY"
        ]
        
        for key in secret_keys:
            try:
                # AKV uses dashes, envs use underscores
                secret = client.get_secret(key)
                env_key = key.replace("-", "_")
                secrets[env_key] = secret.value
                logger.info(f"Fetched {env_key} from Azure Key Vault")
            except Exception:
                # Secret might not exist or no permission
                continue
                
    except ImportError:
        logger.warning("Azure SDK not installed, skipping Key Vault fetch")
    except Exception as e:
        logger.error(f"Error fetching from Key Vault: {e}")
        
    return secrets


class Settings(BaseSettings):
    """Application settings."""
    
    # API Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_LOG_LEVEL: str = "info"
    DEBUG: bool = False
    
    # OpenAI Configuration
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    
    # Qwen Configuration
    QWEN_API_KEY: str = ""
    QWEN_MODEL: str = "qwen-max"
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # Default LLM Provider
    DEFAULT_LLM_PROVIDER: str = "openai"
    
    # MongoDB Configuration
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGO_SYSTEM_DB: str = "system"  # System database for brands, users, etc.
    MONGODB_DATABASE: str = "agent-builder"  # Legacy - deprecated
    MONGODB_COLLECTION: str = "documents"    # Legacy - deprecated
    
    # Voyage AI Configuration
    VOYAGE_API_KEY: str = ""
    VOYAGE_MODEL: str = "voyage-large-2-instruct"
    
    # Redis Configuration
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_SSL: bool = False
    
    # Server Configuration
    API_WORKERS: int = 1
    API_RELOAD: bool = True
    
    # CORS Configuration
    CORS_ALLOW_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",  # Admin Dashboard
        "http://localhost:5173",  # Widget
        "http://127.0.0.1:3001",
        "http://127.0.0.1:5173"
    ]
    
    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    
    # Feature Flags
    ENABLE_WEBSOCKETS: bool = True
    ENABLE_SSE: bool = True
    ENABLE_METRICS: bool = True
    ENABLE_TRACING: bool = False
    
    # Rate Limiting
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10
    
    # File Upload Configuration
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_FILE_TYPES: str = "pdf,txt,md,docx,html"
    UPLOAD_DIR: str = "./uploads"
    
    # Security Configuration
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Memory System Configuration (Phase 5)
    PII_ENCRYPTION_KEY: str = ""
    SHORT_TERM_TTL: int = 259200  # 72 hours
    EPISODIC_TTL: int = 7776000  # 90 days
    SUMMARY_CACHE_TTL: int = 86400  # 24 hours
    CONFIDENCE_THRESHOLD: float = 0.70
    AUTO_SUMMARY_TURNS: int = 4
    MAX_MESSAGES_PER_CONVERSATION: int = 1000
    MAX_FACTS_PER_USER: int = 100
    MAX_SUMMARIES_PER_CONVERSATION: int = 50
    ENABLE_AUTO_SUMMARY: bool = True
    ENABLE_PII_VAULTING: bool = True
    ENABLE_FACT_EXTRACTION: bool = True
    ENABLE_GRAPH_RULES: bool = True
    ENABLE_TTL_CLEANUP: bool = True
    REDIS_FALLBACK_TO_MONGO: bool = True
    REDIS_CONNECTION_TIMEOUT: int = 5
    SUMMARY_MODEL: str = "gpt-4o-mini"
    SUMMARY_MAX_TOKENS: int = 150
    SUMMARY_TEMPERATURE: float = 0.3
    
    # Azure Key Vault Configuration
    AZURE_KEYVAULT_NAME: Optional[str] = None
    USE_AZURE_KEYVAULT: bool = False

    def __init__(self, **values):
        super().__init__(**values)
        if self.USE_AZURE_KEYVAULT and self.AZURE_KEYVAULT_NAME:
            akv_secrets = fetch_akv_secrets(self.AZURE_KEYVAULT_NAME)
            for key, value in akv_secrets.items():
                if not getattr(self, key, None):
                    setattr(self, key, value)

    @field_validator("CORS_ALLOW_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v
    
    @field_validator("REDIS_SSL", "API_RELOAD", "ENABLE_WEBSOCKETS", "ENABLE_SSE", "ENABLE_METRICS", "ENABLE_TRACING", "ENABLE_AUTO_SUMMARY", "ENABLE_PII_VAULTING", "ENABLE_FACT_EXTRACTION", "ENABLE_GRAPH_RULES", "ENABLE_TTL_CLEANUP", "REDIS_FALLBACK_TO_MONGO", "USE_AZURE_KEYVAULT", mode="before")
    @classmethod
    def parse_bool_fields(cls, v):
        """Parse boolean fields from string."""
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return v
    
    @field_validator("API_WORKERS", "RATE_LIMIT_REQUESTS_PER_MINUTE", "RATE_LIMIT_BURST", "MAX_FILE_SIZE_MB", "ACCESS_TOKEN_EXPIRE_MINUTES", "SHORT_TERM_TTL", "EPISODIC_TTL", "SUMMARY_CACHE_TTL", "AUTO_SUMMARY_TURNS", "MAX_MESSAGES_PER_CONVERSATION", "MAX_FACTS_PER_USER", "MAX_SUMMARIES_PER_CONVERSATION", "REDIS_CONNECTION_TIMEOUT", "SUMMARY_MAX_TOKENS", mode="before")
    @classmethod
    def parse_int_fields(cls, v):
        """Parse integer fields from string."""
        if isinstance(v, str):
            return int(v)
        return v
    
    @field_validator("CONFIDENCE_THRESHOLD", "SUMMARY_TEMPERATURE", mode="before")
    @classmethod
    def parse_float_fields(cls, v):
        """Parse float fields from string."""
        if isinstance(v, str):
            return float(v)
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
