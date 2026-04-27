from types import SimpleNamespace

from app.services.agent_config_secrets import (
    decrypt_shopify_configuration_for_runtime,
    expose_agent_for_admin,
    protect_agent_configuration_secrets,
)
from app.services.runtime_settings_service import RuntimeSettingsService


def build_runtime_settings_service():
    settings = SimpleNamespace(
        SETTINGS_ENCRYPTION_KEY="test-settings-encryption-key",
        PII_ENCRYPTION_KEY="",
        SECRET_KEY="test-secret-key",
    )
    return RuntimeSettingsService(settings)


def test_shopify_agent_tokens_are_encrypted_and_hidden_from_admin():
    service = build_runtime_settings_service()

    protected = protect_agent_configuration_secrets(
        {
            "data_source": "shopify",
            "shopify": {
                "shop_url": "https://example.myshopify.com/",
                "access_token": "shpat_secret",
            },
        },
        runtime_settings_service=service,
    )

    shopify = protected["shopify"]
    assert shopify["shop_url"] == "example.myshopify.com"
    assert "access_token" not in shopify
    assert shopify["access_token_encrypted"] != "shpat_secret"

    admin_agent = expose_agent_for_admin({"configuration": protected}, service)
    admin_shopify = admin_agent["configuration"]["shopify"]
    assert admin_shopify["access_token_configured"] is True
    assert "access_token" not in admin_shopify
    assert "access_token_encrypted" not in admin_shopify


def test_blank_shopify_token_update_preserves_existing_secret():
    service = build_runtime_settings_service()
    existing = protect_agent_configuration_secrets(
        {
            "data_source": "shopify",
            "shopify": {
                "shop_url": "example.myshopify.com",
                "access_token": "existing_secret",
            },
        },
        runtime_settings_service=service,
    )

    updated = protect_agent_configuration_secrets(
        {
            "data_source": "shopify",
            "shopify": {
                "shop_url": "example.myshopify.com",
                "access_token": "",
            },
        },
        existing_config=existing,
        runtime_settings_service=service,
    )

    runtime_config = decrypt_shopify_configuration_for_runtime(updated, service)
    assert runtime_config["shopify"]["access_token"] == "existing_secret"


def test_legacy_top_level_shopify_tokens_are_migrated_to_nested_secret_storage():
    service = build_runtime_settings_service()

    protected = protect_agent_configuration_secrets(
        {
            "data_source": "shopify",
            "shopify": {"shop_url": "legacy.myshopify.com"},
            "shopify_access_token": "legacy_secret",
        },
        runtime_settings_service=service,
    )

    assert "shopify_access_token" not in protected
    assert "access_token" not in protected["shopify"]
    assert protected["shopify"]["access_token_encrypted"]

    runtime_config = decrypt_shopify_configuration_for_runtime(protected, service)
    assert runtime_config["shopify"]["access_token"] == "legacy_secret"
