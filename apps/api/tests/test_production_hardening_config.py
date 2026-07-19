import pytest
import base64
from pydantic import ValidationError

from app.config import Settings


def _production_settings(**overrides):
    values = {
        "ENVIRONMENT": "production",
        "SECRET_KEY": "test-secret-key",
        "ADMIN_API_KEY": "test-admin-key",
        "SETTINGS_ENCRYPTION_KEY": "test-settings-key",
        "PII_ENCRYPTION_KEY": "test-pii-key",
        "MONGODB_URI": "mongodb://mongo.internal:27017",
        "REDIS_URL": "redis://redis.internal:6379",
        "MCP_SERVICE_AUTH_TOKEN": "test-mcp-key",
        "STRAPI_PRIVACY_SUBJECT_HMAC_KEY": "privacy-subject-hmac-key-which-is-long-enough",
        "STRAPI_URL": "https://strapi.example.test",
        "STRAPI_API_TOKEN": "test-strapi-key",
        "VECTOR_BACKEND": "qdrant",
        "QDRANT_URL": "http://qdrant:6333",
        "QDRANT_API_KEY": "test-qdrant-key",
        "MALWARE_SCAN_MODE": "clamav",
        "MALWARE_SCAN_HOST": "clamav.internal",
        "MALWARE_SCAN_PORT": 3310,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_defaults_to_fail_closed_rate_limits_and_requires_qdrant_auth():
    settings = _production_settings()
    assert settings.RATE_LIMIT_FAIL_CLOSED is True

    with pytest.raises(ValidationError, match="QDRANT_API_KEY"):
        _production_settings(QDRANT_API_KEY="")


def test_production_rejects_fail_open_rate_limits():
    with pytest.raises(ValidationError, match="RATE_LIMIT_FAIL_CLOSED"):
        _production_settings(RATE_LIMIT_FAIL_CLOSED=False)


def test_production_requires_a_clamav_scanner_for_uploads():
    with pytest.raises(ValidationError, match="MALWARE_SCAN_MODE"):
        _production_settings(MALWARE_SCAN_MODE="disabled")


def test_production_rejects_a_loopback_malware_scanner():
    with pytest.raises(ValidationError, match="MALWARE_SCAN_HOST"):
        _production_settings(MALWARE_SCAN_HOST="127.0.0.1")


def test_production_requires_a_signing_secret_when_shopify_webhooks_are_enabled():
    with pytest.raises(ValidationError, match="SHOPIFY_WEBHOOK_SECRET"):
        _production_settings(SHOPIFY_WEBHOOKS_ENABLED=True, SHOPIFY_WEBHOOK_SECRET="")


def test_shopify_admin_api_release_label_is_validated():
    with pytest.raises(ValidationError, match="SHOPIFY_ADMIN_API_VERSION"):
        Settings(SECRET_KEY="test-secret", SHOPIFY_ADMIN_API_VERSION="latest")


def test_strapi_privacy_defaults_to_contract_pending_even_with_dashboard_url():
    settings = Settings(
        SECRET_KEY="test-secret",
        STRAPI_URL="https://dashboard-strapi.example.test",
        STRAPI_API_TOKEN="legacy-dashboard-token",
    )

    assert settings.STRAPI_PRIVACY_MODE == "contract_pending"


def test_active_strapi_privacy_fails_closed_without_its_own_endpoint_and_keys():
    with pytest.raises(ValidationError, match="STRAPI_PRIVACY_URL"):
        Settings(
            SECRET_KEY="test-secret",
            STRAPI_PRIVACY_MODE="active",
            STRAPI_URL="https://dashboard-strapi.example.test",
            STRAPI_API_TOKEN="legacy-dashboard-token",
        )


def test_active_strapi_privacy_accepts_a_pinned_ed25519_key_without_dashboard_token():
    settings = Settings(
        SECRET_KEY="test-secret",
        STRAPI_PRIVACY_MODE="active",
        STRAPI_PRIVACY_URL="https://privacy-strapi.example.test",
        STRAPI_PRIVACY_SUBJECT_HMAC_KEY="privacy-subject-hmac-key-which-is-long-enough",
        STRAPI_PRIVACY_REQUEST_SIGNING_KEY="privacy-request-signing-key-which-is-long-enough",
        STRAPI_PRIVACY_REQUEST_KEY_ID="privacy-key-1",
        STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY=base64.b64encode(b"p" * 32).decode("ascii"),
        STRAPI_URL="",
        STRAPI_API_TOKEN="",
    )

    assert settings.STRAPI_PRIVACY_MODE == "active"


def test_production_privacy_worker_does_not_require_legacy_dashboard_token():
    settings = _production_settings(
        STRAPI_PRIVACY_WORKER=True,
        STRAPI_API_TOKEN="",
        STRAPI_URL="",
    )

    assert settings.STRAPI_PRIVACY_WORKER is True
