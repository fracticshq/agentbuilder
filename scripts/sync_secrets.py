import os
import argparse
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv

# Load root .env to get vault name
load_dotenv()

VAULT_NAME = os.getenv("AZURE_KEYVAULT_NAME", "kv-agentbuilder-dev")
VAULT_URL = f"https://{VAULT_NAME}.vault.azure.net/"

SECRET_MAP = {
    # AKV Name : Env Var Name
    "OPENAI-API-KEY": "OPENAI_API_KEY",
    "VOYAGE-API-KEY": "VOYAGE_API_KEY",
    "MONGODB-URI": "MONGODB_URI",
    "SECRET-KEY": "SECRET_KEY",
    "PII-ENCRYPTION-KEY": "PII_ENCRYPTION_KEY",
}

def sync_secrets():
    print(f"Syncing secrets from {VAULT_NAME}...")
    
    try:
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=VAULT_URL, credential=credential)
        
        secrets = {}
        for akv_name, env_name in SECRET_MAP.items():
            try:
                secret = client.get_secret(akv_name)
                secrets[env_name] = secret.value
                print(f"✓ Fetched {env_name}")
            except Exception as e:
                print(f"✗ Failed to fetch {akv_name}: {e}")

        # 1. Update/Create apps/admin/.env.local
        admin_env_path = "apps/admin/.env.local"
        print(f"Updating {admin_env_path}...")
        with open(admin_env_path, "w") as f:
            f.write("# Auto-generated local env from Azure Key Vault\n")
            # For React apps, we need REACT_APP_ prefix for client-side usage
            # though some secrets shouldn't be on client. 
            # We'll just prefix what's needed for the admin to talk to API
            f.write(f"REACT_APP_API_URL={os.getenv('API_URL', 'http://localhost:8000')}\n")

        # 2. Update/Create apps/widget/.env.local
        widget_env_path = "apps/widget/.env.local"
        print(f"Updating {widget_env_path}...")
        with open(widget_env_path, "w") as f:
            f.write("# Auto-generated local env from Azure Key Vault\n")
            f.write(f"VITE_API_URL={os.getenv('API_URL', 'http://localhost:8000')}\n")

        print("\nSync complete! Your local JS apps are ready.")
        print("Note: The API server will fetch secrets directly from AKV at runtime.")

    except Exception as e:
        print(f"Error during sync: {e}")

if __name__ == "__main__":
    sync_secrets()
