#!/usr/bin/env python3
"""
Sync script for JS apps (Admin/Widget) - NO SECRETS DOWNLOADED
Creates .env.local files with only non-sensitive configuration (API URLs)
All secrets remain in Azure Key Vault and are fetched by the API server at runtime.
"""
import os
from dotenv import load_dotenv

# Load root .env
load_dotenv()

def sync_local_envs():
    """Create .env.local files for JS apps with non-sensitive config only."""
    
    print("Setting up local environment for JS apps...")
    print("(No secrets will be downloaded - they stay in Azure Key Vault)")
    
    # Get API URL from root .env (non-sensitive)
    api_url = os.getenv('API_URL', 'http://localhost:8000')
    
    # 1. Create apps/admin/.env.local
    admin_env_path = "apps/admin/.env.local"
    print(f"\n✓ Creating {admin_env_path}")
    with open(admin_env_path, "w") as f:
        f.write("# Auto-generated local config (NO SECRETS)\n")
        f.write("# All secrets are in Azure Key Vault (fetched by API at runtime)\n\n")
        f.write(f"REACT_APP_API_URL={api_url}\n")

    # 2. Create apps/widget/.env.local
    widget_env_path = "apps/widget/.env.local"
    print(f"✓ Creating {widget_env_path}")
    with open(widget_env_path, "w") as f:
        f.write("# Auto-generated local config (NO SECRETS)\n")
        f.write("# All secrets are in Azure Key Vault (fetched by API at runtime)\n\n")
        f.write(f"VITE_API_URL={api_url}\n")

    print("\n✅ Setup complete!")
    print("\nSecurity Notes:")
    print("- JS apps only know the API endpoint (non-sensitive)")
    print("- API server fetches all secrets from Azure Key Vault at runtime")
    print("- No secrets are stored on developer machines")
    print("- Revoke Azure Key Vault access when a developer leaves")

if __name__ == "__main__":
    sync_local_envs()
