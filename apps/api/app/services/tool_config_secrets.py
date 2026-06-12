from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.agent_config_secrets import (
    decrypt_shopify_configuration_for_runtime,
    expose_agent_for_admin,
    protect_agent_configuration_secrets,
)
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.tool_registry import ToolRegistryService


SECRET_SUFFIX = "_encrypted"


def _encrypt_secret(runtime_settings_service: RuntimeSettingsService, value: str | None) -> str:
    if not value:
        return ""
    return runtime_settings_service._encrypt(value.strip())


def _decrypt_secret(runtime_settings_service: RuntimeSettingsService, value: str | None) -> str:
    if not value:
        return ""
    return runtime_settings_service._decrypt(value)


def _protect_tool_config(
    tool_id: str,
    incoming: dict[str, Any],
    *,
    existing: dict[str, Any] | None,
    runtime_settings_service: RuntimeSettingsService,
    registry: ToolRegistryService,
) -> dict[str, Any]:
    protected = deepcopy(incoming or {})
    existing = existing or {}

    for field in registry.secret_fields_for(tool_id):
        encrypted_field = f"{field}{SECRET_SUFFIX}"
        incoming_value = protected.get(field)

        if isinstance(incoming_value, str) and incoming_value.strip():
            protected[encrypted_field] = _encrypt_secret(runtime_settings_service, incoming_value)
        elif existing.get(encrypted_field):
            protected[encrypted_field] = existing[encrypted_field]
        elif existing.get(field):
            protected[encrypted_field] = _encrypt_secret(runtime_settings_service, existing[field])

        protected.pop(field, None)

    return protected


def _expose_tool_config_for_admin(
    tool_id: str,
    stored: dict[str, Any],
    *,
    registry: ToolRegistryService,
) -> dict[str, Any]:
    exposed = deepcopy(stored or {})
    for field in registry.secret_fields_for(tool_id):
        encrypted_field = f"{field}{SECRET_SUFFIX}"
        configured = bool(exposed.get(encrypted_field) or exposed.get(field))
        exposed.pop(encrypted_field, None)
        exposed.pop(field, None)
        exposed[f"{field}_configured"] = configured
    return exposed


def _decrypt_tool_config_for_runtime(
    tool_id: str,
    stored: dict[str, Any],
    *,
    runtime_settings_service: RuntimeSettingsService,
    registry: ToolRegistryService,
) -> dict[str, Any]:
    runtime = deepcopy(stored or {})
    for field in registry.secret_fields_for(tool_id):
        encrypted_field = f"{field}{SECRET_SUFFIX}"
        if runtime.get(encrypted_field) and not runtime.get(field):
            runtime[field] = _decrypt_secret(runtime_settings_service, runtime.get(encrypted_field))
    return runtime


def _protect_api_data_source(
    incoming: dict[str, Any],
    *,
    existing: dict[str, Any] | None,
    runtime_settings_service: RuntimeSettingsService,
) -> dict[str, Any]:
    protected = deepcopy(incoming or {})
    existing = existing or {}
    incoming_header = protected.get("auth_header")
    encrypted_field = f"auth_header{SECRET_SUFFIX}"

    if isinstance(incoming_header, str) and incoming_header.strip():
        protected[encrypted_field] = _encrypt_secret(runtime_settings_service, incoming_header)
    elif existing.get(encrypted_field):
        protected[encrypted_field] = existing[encrypted_field]
    elif existing.get("auth_header"):
        protected[encrypted_field] = _encrypt_secret(runtime_settings_service, existing.get("auth_header"))

    protected.pop("auth_header", None)
    return protected


def _expose_api_data_source_for_admin(stored: dict[str, Any]) -> dict[str, Any]:
    exposed = deepcopy(stored or {})
    configured = bool(exposed.get("auth_header") or exposed.get(f"auth_header{SECRET_SUFFIX}"))
    exposed.pop("auth_header", None)
    exposed.pop(f"auth_header{SECRET_SUFFIX}", None)
    exposed["auth_header_configured"] = configured
    return exposed


def _decrypt_api_data_source_for_runtime(
    stored: dict[str, Any],
    *,
    runtime_settings_service: RuntimeSettingsService,
) -> dict[str, Any]:
    runtime = deepcopy(stored or {})
    encrypted_field = f"auth_header{SECRET_SUFFIX}"
    if runtime.get(encrypted_field) and not runtime.get("auth_header"):
        runtime["auth_header"] = _decrypt_secret(runtime_settings_service, runtime.get(encrypted_field))
    return runtime


def protect_full_agent_configuration_secrets(
    incoming_config: dict[str, Any],
    *,
    existing_config: dict[str, Any] | None = None,
    runtime_settings_service: RuntimeSettingsService,
) -> dict[str, Any]:
    config = protect_agent_configuration_secrets(
        incoming_config,
        existing_config=existing_config,
        runtime_settings_service=runtime_settings_service,
    )
    registry = ToolRegistryService()
    tools = deepcopy(config.get("tools") or {})
    existing_tools = deepcopy((existing_config or {}).get("tools") or {})
    if isinstance(config.get("api_data_source"), dict):
        config["api_data_source"] = _protect_api_data_source(
            config["api_data_source"],
            existing=(existing_config or {}).get("api_data_source") if isinstance(existing_config, dict) else None,
            runtime_settings_service=runtime_settings_service,
        )

    for tool_id, tool_config in list(tools.items()):
        if registry.get_tool(tool_id) is None or not isinstance(tool_config, dict):
            continue
        tools[tool_id] = _protect_tool_config(
            tool_id,
            tool_config,
            existing=existing_tools.get(tool_id) if isinstance(existing_tools, dict) else None,
            runtime_settings_service=runtime_settings_service,
            registry=registry,
        )

    if tools:
        config["tools"] = tools
    return config


def expose_full_agent_for_admin(
    agent_doc: dict[str, Any],
    runtime_settings_service: RuntimeSettingsService | None = None,
) -> dict[str, Any]:
    agent = expose_agent_for_admin(agent_doc, runtime_settings_service)
    registry = ToolRegistryService()
    config = deepcopy(agent.get("configuration") or {})
    tools = deepcopy(config.get("tools") or {})
    if isinstance(config.get("api_data_source"), dict):
        config["api_data_source"] = _expose_api_data_source_for_admin(config["api_data_source"])

    for tool_id, tool_config in list(tools.items()):
        if registry.get_tool(tool_id) is None or not isinstance(tool_config, dict):
            continue
        tools[tool_id] = _expose_tool_config_for_admin(tool_id, tool_config, registry=registry)

    if tools:
        config["tools"] = tools
    agent["configuration"] = config
    return agent


def decrypt_full_agent_configuration_for_runtime(
    config: dict[str, Any],
    runtime_settings_service: RuntimeSettingsService,
) -> dict[str, Any]:
    runtime = decrypt_shopify_configuration_for_runtime(config, runtime_settings_service)
    registry = ToolRegistryService()
    tools = deepcopy(runtime.get("tools") or {})
    if isinstance(runtime.get("api_data_source"), dict):
        runtime["api_data_source"] = _decrypt_api_data_source_for_runtime(
            runtime["api_data_source"],
            runtime_settings_service=runtime_settings_service,
        )

    for tool_id, tool_config in list(tools.items()):
        if registry.get_tool(tool_id) is None or not isinstance(tool_config, dict):
            continue
        tools[tool_id] = _decrypt_tool_config_for_runtime(
            tool_id,
            tool_config,
            runtime_settings_service=runtime_settings_service,
            registry=registry,
        )

    if tools:
        runtime["tools"] = tools
    return runtime
