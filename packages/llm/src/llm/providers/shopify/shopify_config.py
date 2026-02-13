"""
Config module for Shopify Orchestrator.
Fetches OpenAI API key from env vars first, then Azure Key Vault as fallback.
"""

import os
from dotenv import load_dotenv
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
from llm.types import LLMConfig
from llm.providers.openai_provider import OpenAIProvider


def fetch_openai_key():
    load_dotenv()

    # Try .env from root if not found
    if not os.getenv("AZURE_KEYVAULT_NAME"):
        root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../../.env"))
        load_dotenv(root_env)

    vault_name = os.getenv("AZURE_KEYVAULT_NAME")
    # Use proper secret name, not model name!
    secret_name = "OPENAI-API-KEY"

    vault_url = f"https://{vault_name}.vault.azure.net/"

    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)

    secret = client.get_secret(secret_name)
    api_key = secret.value

    client.close()
    credential.close()

    return api_key


def get_openai_provider() -> OpenAIProvider:
    load_dotenv()

    # Load root .env too
    root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../../.env"))
    load_dotenv(root_env)

    api_key = fetch_openai_key()
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL")

    config = LLMConfig(
        provider="openai",
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0,
        max_tokens=1000,
    )

    return OpenAIProvider(config)



