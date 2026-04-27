from __future__ import annotations

from typing import Any

import structlog

from .runtime_settings_service import RuntimeSettingsService

logger = structlog.get_logger(__name__)

SHOPIFY_SECRET_FIELDS = ("access_token", "admin_access_token", "customer_access_token")
SHOPIFY_TOP_LEVEL_SECRET_FIELDS = {
    "shopify_access_token": "access_token",
    "shopify_admin_token": "admin_access_token",
    "shopify_customer_access_token": "customer_access_token",
}


def _decrypt_agent_secret(runtime_settings_service: RuntimeSettingsService, value: str | None) -> str:
    if not value:
        return ""
    try:
        return runtime_settings_service._decrypt(value)
    except Exception as exc:
        logger.warning("agent_secret_decrypt_failed", error=str(exc))
        return ""


def _encrypt_agent_secret(runtime_settings_service: RuntimeSettingsService, value: str | None) -> str:
    if not value:
        return ""
    return runtime_settings_service._encrypt(value.strip())


def _normalize_shopify_url(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().replace("https://", "").replace("http://", "").strip("/")


def protect_agent_configuration_secrets(
    incoming_config: dict[str, Any],
    *,
    existing_config: dict[str, Any] | None = None,
    runtime_settings_service: RuntimeSettingsService,
) -> dict[str, Any]:
    """Store per-agent Shopify secrets encrypted and preserve blank existing values."""
    config = dict(incoming_config or {})
    shopify = dict(config.get("shopify") or {})
    existing_shopify = dict((existing_config or {}).get("shopify") or {})

    if "shop_url" in shopify:
        shopify["shop_url"] = _normalize_shopify_url(shopify.get("shop_url"))

    for top_level_field, nested_field in SHOPIFY_TOP_LEVEL_SECRET_FIELDS.items():
        if config.get(top_level_field) and not shopify.get(nested_field):
            shopify[nested_field] = config.get(top_level_field)
        elif (existing_config or {}).get(top_level_field) and not existing_shopify.get(nested_field):
            existing_shopify[nested_field] = (existing_config or {}).get(top_level_field)
        config.pop(top_level_field, None)

    for field in SHOPIFY_SECRET_FIELDS:
        encrypted_field = f"{field}_encrypted"
        incoming_value = shopify.get(field)

        if isinstance(incoming_value, str) and incoming_value.strip():
            shopify[encrypted_field] = _encrypt_agent_secret(runtime_settings_service, incoming_value)
        elif existing_shopify.get(encrypted_field):
            shopify[encrypted_field] = existing_shopify[encrypted_field]
        elif existing_shopify.get(field):
            shopify[encrypted_field] = _encrypt_agent_secret(runtime_settings_service, existing_shopify[field])

        shopify.pop(field, None)

    if shopify:
        config["shopify"] = shopify
    return config


def expose_agent_for_admin(
    agent_doc: dict[str, Any],
    runtime_settings_service: RuntimeSettingsService | None = None,
) -> dict[str, Any]:
    """Return agent config without exposing stored Shopify token material."""
    agent = {**agent_doc}
    config = dict(agent.get("configuration") or {})
    shopify = dict(config.get("shopify") or {})

    for field in SHOPIFY_SECRET_FIELDS:
        encrypted_field = f"{field}_encrypted"
        configured = bool(shopify.get(encrypted_field) or shopify.get(field))
        shopify.pop(encrypted_field, None)
        shopify.pop(field, None)
        shopify[f"{field}_configured"] = configured

    for top_level_field in SHOPIFY_TOP_LEVEL_SECRET_FIELDS:
        config.pop(top_level_field, None)

    if shopify:
        config["shopify"] = shopify
    agent["configuration"] = config
    return agent


def decrypt_shopify_configuration_for_runtime(
    config: dict[str, Any],
    runtime_settings_service: RuntimeSettingsService,
) -> dict[str, Any]:
    config = dict(config or {})
    shopify = dict(config.get("shopify") or {})

    for top_level_field, nested_field in SHOPIFY_TOP_LEVEL_SECRET_FIELDS.items():
        if config.get(top_level_field) and not shopify.get(nested_field):
            shopify[nested_field] = config.get(top_level_field)

    for field in SHOPIFY_SECRET_FIELDS:
        encrypted_field = f"{field}_encrypted"
        if shopify.get(encrypted_field) and not shopify.get(field):
            shopify[field] = _decrypt_agent_secret(runtime_settings_service, shopify.get(encrypted_field))

    if shopify:
        config["shopify"] = shopify
    return config
