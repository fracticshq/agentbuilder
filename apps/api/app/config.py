import os
import logging
from typing import List, Optional, Union
from pydantic import field_validator, model_validator
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
            "AZURE-OPENAI-API-KEY",
            "AZURE-OPENAI-ENDPOINT",
            "AZURE-OPENAI-API-VERSION",
            "AZURE-OPENAI-DEPLOYMENT",
            "AZURE-SUBSCRIPTION-ID",
            "AZURE-RESOURCE-GROUP",
            "AZURE-OPENAI-ACCOUNT-NAME",
            "VOYAGE-API-KEY",
            "MONGODB-URI",
            "REDIS-URL",
            "SECRET-KEY",
            "SETTINGS-ENCRYPTION-KEY",
            "PII-ENCRYPTION-KEY",
            "JWT-SECRET",
            "ADMIN-API-KEY",
            "QWEN-API-KEY",
            "STRAPI-API-TOKEN",
            "FIRECRAWL-API-KEY",
            "GOOGLE-CLIENT-ID",
            "ATLAS-PUBLIC-KEY",
            "ATLAS-PRIVATE-KEY",
            "ATLAS-PROJECT-ID",
            "ATLAS-CLUSTER-NAME",
            "ATLAS-AUTO-CREATE-VECTOR-INDEXES",
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


def _load_dotenv_early(env_path: str | None = None):
    """Manually parse .env so AKV flags are visible before Settings is instantiated."""
    import pathlib
    path = pathlib.Path(env_path) if env_path else (
        pathlib.Path(__file__).resolve().parents[3] / ".env"
    )
    if not path.exists():
        return
    try:
        from dotenv import dotenv_values
        for k, v in dotenv_values(path).items():
            if k not in os.environ:
                os.environ[k] = v or ""
    except ImportError:
        pass  # python-dotenv not installed — skip silently


# Pre-load AKV secrets into environment BEFORE Settings class is defined
# This ensures Pydantic picks them up during its normal env loading
def _preload_akv_secrets(env_path: str | None = None):
    """Load AKV secrets into environment before Settings initialization."""
    _load_dotenv_early(env_path)  # must be first — reads .env so USE_AZURE_KEYVAULT is visible
    use_akv = os.getenv("USE_AZURE_KEYVAULT", "false").lower() == "true"
    vault_name = os.getenv("AZURE_KEYVAULT_NAME")
    
    if use_akv and vault_name:
        logger.info(f"Pre-loading secrets from Azure Key Vault: {vault_name}")
        secrets = fetch_akv_secrets(vault_name)
        for key, value in secrets.items():
            if not os.getenv(key):  # Only set if not already in environment
                os.environ[key] = value
                logger.info(f"Injected {key} into environment from AKV")

# Execute at module load time
_preload_akv_secrets()

class Settings(BaseSettings):
    """Application settings."""
    
    # API Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_LOG_LEVEL: str = "info"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    ADMIN_APP_URL: str = "http://localhost:3000"
    
    # OpenAI Configuration
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # Azure OpenAI Configuration
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_MODEL: str = "gpt-5.4-mini"
    AZURE_OPENAI_DEPLOYMENT: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_VERSION: str = ""
    AZURE_SUBSCRIPTION_ID: str = ""
    AZURE_RESOURCE_GROUP: str = ""
    AZURE_OPENAI_ACCOUNT_NAME: str = ""
    GOOGLE_CLIENT_ID: str = ""
    
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
    VECTOR_BACKEND: str = "atlas"  # atlas | qdrant
    VECTOR_INDEX_NAME: str = "vector_index"
    VECTOR_DIMENSIONS: int = 1024
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION_PREFIX: str = "nova"
    ATLAS_PROJECT_ID: str = ""
    ATLAS_CLUSTER_NAME: str = ""
    ATLAS_PUBLIC_KEY: str = ""
    ATLAS_PRIVATE_KEY: str = ""
    ATLAS_AUTO_CREATE_VECTOR_INDEXES: bool = False
    
    # Voyage AI Configuration
    VOYAGE_API_KEY: str = ""
    VOYAGE_BASE_URL: str = "https://api.voyageai.com/v1"
    VOYAGE_MODEL: str = "voyage-3-large"
    VOYAGE_RERANK_MODEL: str = "rerank-2.5"
    
    # Redis Configuration
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_SSL: bool = False
    
    # Server Configuration
    API_WORKERS: int = 1
    API_RELOAD: bool = True
    
    # CORS Configuration
    CORS_ALLOW_ORIGINS: Union[str, List[str]] = [
        "http://localhost:3000",
        "http://localhost:1337",  # Strapi dashboard
        "http://localhost:3001",  # Admin Dashboard
        "http://localhost:5173",  # Strapi Vite HMR
        "http://localhost:5174",  # Widget
        "http://127.0.0.1:3001",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174"
    ]
    
    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    
    # Feature Flags
    ENABLE_WEBSOCKETS: bool = True
    ENABLE_SSE: bool = True
    ENABLE_METRICS: bool = True
    ENABLE_TRACING: bool = False
    ENABLE_HUMAN_TAKEOVER: bool = False
    REQUIRE_REDIS: bool = False
    REQUIRE_MONGODB: bool = True
    
    # Rate Limiting
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10
    RATE_LIMIT_FAIL_CLOSED: bool = False
    RATE_LIMIT_POLICY_WIDGET_CHAT: int = 60
    RATE_LIMIT_POLICY_WIDGET_STREAM: int = 40
    RATE_LIMIT_POLICY_WIDGET_WS_CONNECT: int = 30
    RATE_LIMIT_POLICY_WIDGET_WS_MESSAGE: int = 120
    RATE_LIMIT_POLICY_ADMIN_API: int = 300
    RATE_LIMIT_POLICY_UPLOAD: int = 20
    RATE_LIMIT_POLICY_STRAPI_SYNC: int = 600
    
    # File Upload Configuration
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_FILE_TYPES: str = "pdf,txt,md,docx,html"
    UPLOAD_DIR: str = "./uploads"
    
    # Security Configuration
    SECRET_KEY: str  # Required — set via SECRET_KEY env var or Azure Key Vault
    SETTINGS_ENCRYPTION_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60
    ALLOW_PUBLIC_SIGNUP: bool = False
    # Simple admin API key for protecting write operations until JWT login UI is built.
    # Generate with: openssl rand -hex 32
    ADMIN_API_KEY: str = ""
    ALLOW_ADMIN_KEY_BYPASS: bool = True
    
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
    
    # Strapi Dashboard Integration
    STRAPI_URL: str = "http://localhost:1337"
    STRAPI_API_TOKEN: str = ""
    
    # Shopify MCP service URL. Store identity and store tokens are per-agent
    # configuration values managed from the dashboard, not global env vars.
    SHOPIFY_MCP_URL: str = "http://localhost:3005/mcp"
    SHOPIFY_MCP_USE: bool = True

    # Firecrawl (product catalog scraping)
    FIRECRAWL_API_KEY: str = ""
    USE_FIRECRAWL: bool = True

    # Azure Key Vault Configuration
    AZURE_KEYVAULT_NAME: Optional[str] = None
    USE_AZURE_KEYVAULT: bool = False
    AZURE_CLIENT_ID: Optional[str] = None
    AZURE_CLIENT_SECRET: Optional[str] = None
    AZURE_TENANT_ID: Optional[str] = None

    # Note: AKV secrets are preloaded into os.environ at module load time
    # See _preload_akv_secrets() function above

    @field_validator("CORS_ALLOW_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string or list."""
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v
    
    @field_validator("REDIS_SSL", "API_RELOAD", "ENABLE_WEBSOCKETS", "ENABLE_SSE", "ENABLE_METRICS", "ENABLE_TRACING", "ENABLE_HUMAN_TAKEOVER", "ENABLE_AUTO_SUMMARY", "ENABLE_PII_VAULTING", "ENABLE_FACT_EXTRACTION", "ENABLE_GRAPH_RULES", "ENABLE_TTL_CLEANUP", "REDIS_FALLBACK_TO_MONGO", "USE_AZURE_KEYVAULT", "ALLOW_PUBLIC_SIGNUP", "RATE_LIMIT_FAIL_CLOSED", "ATLAS_AUTO_CREATE_VECTOR_INDEXES", "SHOPIFY_MCP_USE", mode="before")
    @classmethod
    def parse_bool_fields(cls, v):
        """Parse boolean fields from string."""
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return v
    
    @field_validator("API_WORKERS", "RATE_LIMIT_REQUESTS_PER_MINUTE", "RATE_LIMIT_BURST", "RATE_LIMIT_POLICY_WIDGET_CHAT", "RATE_LIMIT_POLICY_WIDGET_STREAM", "RATE_LIMIT_POLICY_WIDGET_WS_CONNECT", "RATE_LIMIT_POLICY_WIDGET_WS_MESSAGE", "RATE_LIMIT_POLICY_ADMIN_API", "RATE_LIMIT_POLICY_UPLOAD", "RATE_LIMIT_POLICY_STRAPI_SYNC", "MAX_FILE_SIZE_MB", "ACCESS_TOKEN_EXPIRE_MINUTES", "PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "SHORT_TERM_TTL", "EPISODIC_TTL", "SUMMARY_CACHE_TTL", "AUTO_SUMMARY_TURNS", "MAX_MESSAGES_PER_CONVERSATION", "MAX_FACTS_PER_USER", "MAX_SUMMARIES_PER_CONVERSATION", "REDIS_CONNECTION_TIMEOUT", "SUMMARY_MAX_TOKENS", "VECTOR_DIMENSIONS", mode="before")
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
    
    @field_validator("DEBUG", "ALLOW_ADMIN_KEY_BYPASS", "REQUIRE_REDIS", "REQUIRE_MONGODB", mode="before")
    @classmethod
    def parse_debug(cls, v):
        """Parse boolean settings from string."""
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return v

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def parse_environment(cls, v):
        if isinstance(v, str):
            return v.lower()
        return v

    @field_validator("VECTOR_BACKEND", mode="before")
    @classmethod
    def parse_vector_backend(cls, v):
        if isinstance(v, str):
            return v.lower()
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @model_validator(mode="after")
    def validate_production_settings(self):
        if not self.is_production:
            return self

        missing = [
            name
            for name in [
                "ADMIN_API_KEY",
                "SETTINGS_ENCRYPTION_KEY",
                "PII_ENCRYPTION_KEY",
                "MONGODB_URI",
                "REDIS_URL",
            ]
            if not str(getattr(self, name, "") or "").strip()
        ]

        if str(self.STRAPI_URL or "").strip() and not str(self.STRAPI_API_TOKEN or "").strip():
            missing.append("STRAPI_API_TOKEN")

        if str(self.STRAPI_API_TOKEN or "").strip():
            strapi_url = str(self.STRAPI_URL or "").strip()
            if "localhost" in strapi_url or "127.0.0.1" in strapi_url:
                missing.append("STRAPI_URL (must not point at localhost in production)")

        if missing:
            raise ValueError(
                "Missing or invalid production configuration: " + ", ".join(missing)
            )

        return self

    class Config:
        # Load from root .env (2 levels up from app/config.py)
        env_file = "../../.env"
        case_sensitive = True
        extra = "ignore"
