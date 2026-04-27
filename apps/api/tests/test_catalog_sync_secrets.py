from types import SimpleNamespace

from app.api.v1.endpoints.catalog import (
    _decrypt_sync_config_for_runtime,
    _expose_sync_config_for_admin,
    _protect_sync_config_secrets,
)
from app.services.runtime_settings_service import RuntimeSettingsService


def build_runtime_settings_service():
    settings = SimpleNamespace(
        SETTINGS_ENCRYPTION_KEY="test-settings-encryption-key",
        PII_ENCRYPTION_KEY="",
        SECRET_KEY="test-secret-key",
    )
    return RuntimeSettingsService(settings)


def test_catalog_sync_access_token_is_encrypted_and_hidden_from_admin():
    service = build_runtime_settings_service()

    protected = _protect_sync_config_secrets(
        {
            "source_type": "shopify",
            "source_url": "example.myshopify.com",
            "access_token": "shpat_catalog_secret",
        },
        runtime_settings_service=service,
    )

    assert "access_token" not in protected
    assert protected["access_token_encrypted"] != "shpat_catalog_secret"

    safe = _expose_sync_config_for_admin(protected)
    assert safe["access_token_configured"] is True
    assert "access_token" not in safe
    assert "access_token_encrypted" not in safe

    runtime = _decrypt_sync_config_for_runtime(protected, service)
    assert runtime["access_token"] == "shpat_catalog_secret"


def test_catalog_sync_blank_update_preserves_existing_secret():
    service = build_runtime_settings_service()
    existing = _protect_sync_config_secrets(
        {
            "source_type": "shopify",
            "source_url": "example.myshopify.com",
            "access_token": "existing_catalog_secret",
        },
        runtime_settings_service=service,
    )

    updated = _protect_sync_config_secrets(
        {
            "source_type": "shopify",
            "source_url": "example.myshopify.com",
        },
        existing=existing,
        runtime_settings_service=service,
    )

    runtime = _decrypt_sync_config_for_runtime(updated, service)
    assert runtime["access_token"] == "existing_catalog_secret"
