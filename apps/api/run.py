#!/usr/bin/env python3
"""
FastAPI Application Launcher
"""

import sys
import os
import logging
from pathlib import Path

# Configure basic logging for early messages
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# PRE-LOAD AZURE KEY VAULT SECRETS BEFORE ANY PACKAGE IMPORTS
# This MUST happen first, before memory/retrieval packages are imported
# =============================================================================

def _load_root_env():
    """Load root .env file to get AKV configuration."""
    root_env = Path(__file__).parent.parent.parent / ".env"
    if root_env.exists():
        from dotenv import load_dotenv
        load_dotenv(root_env)
        logger.info(f"Loaded root .env from {root_env}")

def _preload_akv_secrets():
    """Fetch secrets from Azure Key Vault and inject into os.environ."""
    use_akv = os.getenv("USE_AZURE_KEYVAULT", "false").lower() == "true"
    vault_name = os.getenv("AZURE_KEYVAULT_NAME")
    
    if not use_akv or not vault_name:
        logger.info("Azure Key Vault not enabled, skipping secret preload")
        return
    
    logger.info(f"Pre-loading secrets from Azure Key Vault: {vault_name}")
    
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
        
        vault_url = f"https://{vault_name}.vault.azure.net/"
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)
        
        # Secrets to fetch (AKV uses dashes, env vars use underscores)
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
            "GOOGLE-CLIENT-ID"
        ]
        
        for key in secret_keys:
            try:
                secret = client.get_secret(key)
                env_key = key.replace("-", "_")
                if not os.getenv(env_key):
                    os.environ[env_key] = secret.value
                    logger.info(f"✓ Injected {env_key} from AKV")
            except Exception as e:
                logger.debug(f"Could not fetch {key}: {e}")
                
    except ImportError:
        logger.warning("Azure SDK not installed, skipping Key Vault fetch")
    except Exception as e:
        logger.error(f"Error fetching from Key Vault: {e}")

# Execute secret loading FIRST
_load_root_env()
_preload_akv_secrets()

from app.config import Settings

settings = Settings()

if settings.is_production and settings.DEBUG:
    raise RuntimeError("DEBUG must be false in production")

# =============================================================================
# Now add local packages to Python path
# =============================================================================

current_dir = Path(__file__).parent
packages_dir = current_dir.parent.parent / "packages"

for package in ["commons", "memory", "retrieval", "llm", "tools", "agent_runtime"]:
    package_path = packages_dir / package / "src"
    if package_path.exists():
        sys.path.insert(0, str(package_path))


# Now import and run the app
if __name__ == "__main__":
    import uvicorn
    import asyncio
    import sys
    
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Run with reload disabled since we're importing the app directly
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_RELOAD and not settings.is_production,
        log_level=settings.API_LOG_LEVEL.lower()
    )
