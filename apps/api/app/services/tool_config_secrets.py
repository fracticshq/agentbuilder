from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from app.services.agent_config_secrets import (
    decrypt_shopify_configuration_for_runtime,
    expose_agent_for_admin,
    protect_agent_configuration_secrets,
)
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.tool_registry import ToolRegistryService


SECRET_SUFFIX = "_encrypted"
SECRET_KEY_PATTERN = re.compile(
    r"(token|secret|password|api[_-]?key|authorization|credential|auth[_-]?header)",
    re.IGNORECASE,
)


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


def _api_data_source_to_context_connector(api_data_source: dict[str, Any]) -> dict[str, Any] | None:
    url = str(api_data_source.get("url") or "").strip()
    if not url:
        return None
    connector: dict[str, Any] = {
        "id": "legacy_api_data_source",
        "name": api_data_source.get("name") or "Legacy API Data Source",
        "type": "http_api",
        "enabled": bool(api_data_source.get("enabled", True)),
        "auth": {
            "type": "raw_header",
        },
        "usage_policy": api_data_source.get("usage") or "",
        "endpoints": [
            {
                "id": "default",
                "name": api_data_source.get("name") or "Default API Lookup",
                "enabled": True,
                "method": "POST",
                "url_template": url,
                "required_user_fields": [],
                "response_mapping": {},
                "tool_description": api_data_source.get("usage") or "Call the configured API data source.",
            }
        ],
    }
    for key in ("auth_header", f"auth_header{SECRET_SUFFIX}", "auth_header_configured"):
        if key in api_data_source:
            connector["auth"][key] = api_data_source[key]
    return connector


def _with_migrated_context_connectors(config: dict[str, Any], *, drop_legacy: bool) -> dict[str, Any]:
    migrated = deepcopy(config or {})
    connectors = migrated.get("context_connectors")
    if isinstance(connectors, list) and connectors:
        if drop_legacy:
            migrated.pop("api_data_source", None)
        return migrated
    api_data_source = migrated.get("api_data_source")
    if isinstance(api_data_source, dict):
        connector = _api_data_source_to_context_connector(api_data_source)
        if connector:
            migrated["context_connectors"] = [connector]
            if drop_legacy:
                migrated.pop("api_data_source", None)
    return migrated


def _protect_secretish_mapping(
    incoming: dict[str, Any],
    *,
    existing: dict[str, Any] | None,
    runtime_settings_service: RuntimeSettingsService,
) -> dict[str, Any]:
    """Encrypt secret-looking values in a shallow mapping such as auth or headers."""
    protected = deepcopy(incoming or {})
    existing = existing or {}

    for key, value in list(protected.items()):
        key_string = str(key)
        encrypted_field = f"{key_string}{SECRET_SUFFIX}"
        if key_string.endswith(SECRET_SUFFIX) or key_string.endswith("_configured"):
            continue
        if not SECRET_KEY_PATTERN.search(key_string):
            continue

        if isinstance(value, str) and value.strip():
            protected[encrypted_field] = _encrypt_secret(runtime_settings_service, value)
        elif existing.get(encrypted_field):
            protected[encrypted_field] = existing[encrypted_field]
        elif existing.get(key_string):
            protected[encrypted_field] = _encrypt_secret(runtime_settings_service, existing.get(key_string))

        protected.pop(key_string, None)
        protected[f"{key_string}_configured"] = bool(protected.get(encrypted_field))

    return protected


def _expose_secretish_mapping(stored: dict[str, Any]) -> dict[str, Any]:
    exposed = deepcopy(stored or {})
    for key in list(exposed.keys()):
        key_string = str(key)
        if key_string.endswith(SECRET_SUFFIX):
            public_key = key_string[: -len(SECRET_SUFFIX)]
            exposed.pop(key_string, None)
            exposed.pop(public_key, None)
            exposed[f"{public_key}_configured"] = True
        elif SECRET_KEY_PATTERN.search(key_string) and not key_string.endswith("_configured"):
            exposed.pop(key_string, None)
            exposed[f"{key_string}_configured"] = True
    return exposed


def _decrypt_secretish_mapping(
    stored: dict[str, Any],
    *,
    runtime_settings_service: RuntimeSettingsService,
) -> dict[str, Any]:
    runtime = deepcopy(stored or {})
    for key, value in list(runtime.items()):
        key_string = str(key)
        if not key_string.endswith(SECRET_SUFFIX):
            continue
        public_key = key_string[: -len(SECRET_SUFFIX)]
        if value and not runtime.get(public_key):
            runtime[public_key] = _decrypt_secret(runtime_settings_service, value)
    return runtime


def _connector_identity(connector: dict[str, Any]) -> str:
    return str(connector.get("id") or connector.get("name") or "").strip()


def _endpoint_identity(endpoint: dict[str, Any]) -> str:
    return str(endpoint.get("id") or endpoint.get("name") or "").strip()


def _matching_existing_connector(
    connector: dict[str, Any],
    existing_connectors: list[dict[str, Any]],
) -> dict[str, Any]:
    connector_id = _connector_identity(connector)
    for existing in existing_connectors:
        if _connector_identity(existing) == connector_id:
            return existing
    return {}


def _matching_existing_endpoint(
    endpoint: dict[str, Any],
    existing_endpoints: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoint_id = _endpoint_identity(endpoint)
    for existing in existing_endpoints:
        if _endpoint_identity(existing) == endpoint_id:
            return existing
    return {}


def _protect_context_connectors(
    incoming: list[Any],
    *,
    existing: list[Any] | None,
    runtime_settings_service: RuntimeSettingsService,
) -> list[dict[str, Any]]:
    existing_connectors = [item for item in (existing or []) if isinstance(item, dict)]
    protected_connectors: list[dict[str, Any]] = []

    for raw_connector in incoming or []:
        if not isinstance(raw_connector, dict):
            continue
        connector = deepcopy(raw_connector)
        existing_connector = _matching_existing_connector(connector, existing_connectors)

        if isinstance(connector.get("auth"), dict):
            connector["auth"] = _protect_secretish_mapping(
                connector["auth"],
                existing=existing_connector.get("auth") if isinstance(existing_connector.get("auth"), dict) else None,
                runtime_settings_service=runtime_settings_service,
            )
        if isinstance(connector.get("headers"), dict):
            connector["headers"] = _protect_secretish_mapping(
                connector["headers"],
                existing=existing_connector.get("headers") if isinstance(existing_connector.get("headers"), dict) else None,
                runtime_settings_service=runtime_settings_service,
            )

        existing_endpoints = existing_connector.get("endpoints") if isinstance(existing_connector.get("endpoints"), list) else []
        endpoints = []
        for raw_endpoint in connector.get("endpoints") or []:
            if not isinstance(raw_endpoint, dict):
                continue
            endpoint = deepcopy(raw_endpoint)
            existing_endpoint = _matching_existing_endpoint(endpoint, existing_endpoints)
            if isinstance(endpoint.get("headers"), dict):
                endpoint["headers"] = _protect_secretish_mapping(
                    endpoint["headers"],
                    existing=existing_endpoint.get("headers") if isinstance(existing_endpoint.get("headers"), dict) else None,
                    runtime_settings_service=runtime_settings_service,
                )
            endpoints.append(endpoint)
        connector["endpoints"] = endpoints

        if connector.get("type") == "mcp" and isinstance(connector.get("mcp"), dict):
            existing_mcp = existing_connector.get("mcp") if isinstance(existing_connector.get("mcp"), dict) else {}
            mcp_config = deepcopy(connector["mcp"])
            if isinstance(mcp_config.get("headers"), dict):
                mcp_config["headers"] = _protect_secretish_mapping(
                    mcp_config["headers"],
                    existing=existing_mcp.get("headers") if isinstance(existing_mcp.get("headers"), dict) else None,
                    runtime_settings_service=runtime_settings_service,
                )
            if isinstance(mcp_config.get("env"), dict):
                mcp_config["env"] = _protect_secretish_mapping(
                    mcp_config["env"],
                    existing=existing_mcp.get("env") if isinstance(existing_mcp.get("env"), dict) else None,
                    runtime_settings_service=runtime_settings_service,
                )
            connector["mcp"] = mcp_config

        protected_connectors.append(connector)

    return protected_connectors


def _expose_context_connectors_for_admin(stored: list[Any]) -> list[dict[str, Any]]:
    exposed_connectors: list[dict[str, Any]] = []
    for raw_connector in stored or []:
        if not isinstance(raw_connector, dict):
            continue
        connector = deepcopy(raw_connector)
        if isinstance(connector.get("auth"), dict):
            connector["auth"] = _expose_secretish_mapping(connector["auth"])
        if isinstance(connector.get("headers"), dict):
            connector["headers"] = _expose_secretish_mapping(connector["headers"])
        connector["endpoints"] = [
            {
                **endpoint,
                **(
                    {"headers": _expose_secretish_mapping(endpoint["headers"])}
                    if isinstance(endpoint, dict) and isinstance(endpoint.get("headers"), dict)
                    else {}
                ),
            }
            for endpoint in (connector.get("endpoints") or [])
            if isinstance(endpoint, dict)
        ]
        if connector.get("type") == "mcp" and isinstance(connector.get("mcp"), dict):
            mcp_config = deepcopy(connector["mcp"])
            if isinstance(mcp_config.get("headers"), dict):
                mcp_config["headers"] = _expose_secretish_mapping(mcp_config["headers"])
            if isinstance(mcp_config.get("env"), dict):
                mcp_config["env"] = _expose_secretish_mapping(mcp_config["env"])
            connector["mcp"] = mcp_config
        exposed_connectors.append(connector)
    return exposed_connectors


def _decrypt_context_connectors_for_runtime(
    stored: list[Any],
    *,
    runtime_settings_service: RuntimeSettingsService,
) -> list[dict[str, Any]]:
    runtime_connectors: list[dict[str, Any]] = []
    for raw_connector in stored or []:
        if not isinstance(raw_connector, dict):
            continue
        connector = deepcopy(raw_connector)
        if isinstance(connector.get("auth"), dict):
            connector["auth"] = _decrypt_secretish_mapping(
                connector["auth"],
                runtime_settings_service=runtime_settings_service,
            )
        if isinstance(connector.get("headers"), dict):
            connector["headers"] = _decrypt_secretish_mapping(
                connector["headers"],
                runtime_settings_service=runtime_settings_service,
            )
        endpoints = []
        for raw_endpoint in connector.get("endpoints") or []:
            if not isinstance(raw_endpoint, dict):
                continue
            endpoint = deepcopy(raw_endpoint)
            if isinstance(endpoint.get("headers"), dict):
                endpoint["headers"] = _decrypt_secretish_mapping(
                    endpoint["headers"],
                    runtime_settings_service=runtime_settings_service,
                )
            endpoints.append(endpoint)
        connector["endpoints"] = endpoints
        if connector.get("type") == "mcp" and isinstance(connector.get("mcp"), dict):
            mcp_config = deepcopy(connector["mcp"])
            if isinstance(mcp_config.get("headers"), dict):
                mcp_config["headers"] = _decrypt_secretish_mapping(
                    mcp_config["headers"],
                    runtime_settings_service=runtime_settings_service,
                )
            if isinstance(mcp_config.get("env"), dict):
                mcp_config["env"] = _decrypt_secretish_mapping(
                    mcp_config["env"],
                    runtime_settings_service=runtime_settings_service,
                )
            connector["mcp"] = mcp_config
        runtime_connectors.append(connector)
    return runtime_connectors


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
    config = _with_migrated_context_connectors(config, drop_legacy=True)
    registry = ToolRegistryService()
    tools = deepcopy(config.get("tools") or {})
    existing_tools = deepcopy((existing_config or {}).get("tools") or {})
    if isinstance(config.get("api_data_source"), dict):
        config["api_data_source"] = _protect_api_data_source(
            config["api_data_source"],
            existing=(existing_config or {}).get("api_data_source") if isinstance(existing_config, dict) else None,
            runtime_settings_service=runtime_settings_service,
        )
    if isinstance(config.get("context_connectors"), list):
        config["context_connectors"] = _protect_context_connectors(
            config["context_connectors"],
            existing=(existing_config or {}).get("context_connectors") if isinstance(existing_config, dict) else None,
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
    config = _with_migrated_context_connectors(config, drop_legacy=False)
    tools = deepcopy(config.get("tools") or {})
    if isinstance(config.get("api_data_source"), dict):
        config["api_data_source"] = _expose_api_data_source_for_admin(config["api_data_source"])
    if isinstance(config.get("context_connectors"), list):
        config["context_connectors"] = _expose_context_connectors_for_admin(config["context_connectors"])

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
    runtime = _with_migrated_context_connectors(runtime, drop_legacy=False)
    registry = ToolRegistryService()
    tools = deepcopy(runtime.get("tools") or {})
    if isinstance(runtime.get("api_data_source"), dict):
        runtime["api_data_source"] = _decrypt_api_data_source_for_runtime(
            runtime["api_data_source"],
            runtime_settings_service=runtime_settings_service,
        )
    if isinstance(runtime.get("context_connectors"), list):
        runtime["context_connectors"] = _decrypt_context_connectors_for_runtime(
            runtime["context_connectors"],
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
