import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "validate_azure_env.py"
SPEC = importlib.util.spec_from_file_location("validate_azure_env", MODULE_PATH)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def valid_env():
    return {
        "SUBSCRIPTION_ID": "sub-123456789012",
        "RESOURCE_GROUP": "nova-prod-rg",
        "ACR_NAME": "novaprodacr001",
        "ACA_ENV": "nova-prod-env",
        "SECRET_KEY": "x" * 32,
        "ADMIN_API_KEY": "a" * 32,
        "SETTINGS_ENCRYPTION_KEY": "s" * 32,
        "PII_ENCRYPTION_KEY": "p" * 32,
        "MONGODB_URI": "mongodb+srv://user:pass@example.mongodb.net/",
        "REDIS_URL": "rediss://:pass@example.redis.cache.windows.net:6380",
        "DEFAULT_LLM_PROVIDER": "azure_openai",
        "AZURE_OPENAI_API_KEY": "z" * 32,
        "AZURE_OPENAI_MODEL": "gpt-5.4-mini",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-5.4-mini",
        "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
        "AZURE_OPENAI_API_VERSION": "2025-04-01-preview",
        "VOYAGE_API_KEY": "v" * 32,
        "VOYAGE_BASE_URL": "https://ai.mongodb.com/v1",
        "VOYAGE_MODEL": "voyage-3-large",
        "VOYAGE_RERANK_MODEL": "rerank-2.5",
        "VECTOR_BACKEND": "atlas",
        "VECTOR_INDEX_NAME": "vector_index",
        "VECTOR_DIMENSIONS": "1024",
        "STRAPI_API_TOKEN": "t" * 32,
        "MCP_SERVICE_AUTH_TOKEN": "c" * 32,
        "SESSION_SECRET": "q" * 32,
        "DATABASE_HOST": "pg.postgres.database.azure.com",
        "DATABASE_NAME": "agentbuilder_strapi",
        "DATABASE_USERNAME": "strapiadmin",
        "DATABASE_PASSWORD": "d" * 32,
        "APP_KEYS": ",".join(["k" * 32, "l" * 32, "m" * 32, "n" * 32]),
        "API_TOKEN_SALT": "i" * 32,
        "ADMIN_JWT_SECRET": "j" * 32,
        "TRANSFER_TOKEN_SALT": "r" * 32,
        "ENCRYPTION_KEY": "e" * 32,
        "JWT_SECRET": "w" * 32,
    }


def test_validator_accepts_complete_all_service_env():
    results = validator.build_results("all", valid_env())

    assert all(result.status not in {"missing", "invalid"} for result in results)


def test_validator_rejects_blank_required_secret():
    env = valid_env()
    env["STRAPI_API_TOKEN"] = ""

    results = validator.build_results("all", env)
    failures = {(result.service, result.key, result.status) for result in results}

    assert ("api", "STRAPI_API_TOKEN", "missing") in failures
    assert ("strapi", "STRAPI_API_TOKEN", "missing") in failures


def test_validator_rejects_placeholder_values():
    env = valid_env()
    env["DATABASE_PASSWORD"] = "replace_me"

    results = validator.build_results("strapi", env)

    assert any(
        result.key == "DATABASE_PASSWORD" and result.status == "invalid"
        for result in results
    )


def test_validator_requires_four_app_keys():
    env = valid_env()
    env["APP_KEYS"] = "a" * 32

    results = validator.build_results("strapi", env)

    assert any(result.key == "APP_KEYS" and result.status == "invalid" for result in results)


def test_validator_rejects_bad_url_scheme():
    env = valid_env()
    env["VOYAGE_BASE_URL"] = "http://api.voyageai.com/v1"

    results = validator.build_results("api", env)

    assert any(result.key == "VOYAGE_BASE_URL" and result.status == "invalid" for result in results)


def test_validator_can_allow_missing_local_secrets_when_azure_secret_refs_exist():
    env = valid_env()
    env["AZURE_OPENAI_API_KEY"] = ""

    results = validator.build_results("api", env, allow_missing_secrets=True)

    assert any(
        result.key == "AZURE_OPENAI_API_KEY" and result.status == "external"
        for result in results
    )
    assert all(result.status not in {"missing", "invalid"} for result in results)


def test_validator_requires_shared_mcp_service_token_for_api_and_shopify():
    env = valid_env()
    env["MCP_SERVICE_AUTH_TOKEN"] = ""

    results = validator.build_results("all", env)
    failures = {(result.service, result.key, result.status) for result in results}

    assert ("api", "MCP_SERVICE_AUTH_TOKEN", "missing") in failures
    assert ("shopify", "MCP_SERVICE_AUTH_TOKEN", "missing") in failures
