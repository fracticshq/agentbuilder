from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlparse
import ipaddress
import json
import socket

import httpx
from tools.types import BaseTool, ToolResult


TOOL_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "shopify",
        "provider": "shopify",
        "name": "Shopify",
        "auth_type": "api_token",
        "secret_fields": ["access_token", "admin_access_token", "customer_access_token"],
        "config_schema": {
            "shop_url": {"type": "string", "required": True},
            "access_token": {"type": "string", "secret": True},
            "admin_access_token": {"type": "string", "secret": True},
            "customer_access_token": {"type": "string", "secret": True},
        },
    },
    {
        "id": "http_webhook",
        "provider": "http",
        "name": "HTTP Webhook",
        "auth_type": "header_secret",
        "secret_fields": ["secret", "authorization_header"],
        "config_schema": {
            "url": {"type": "string", "required": True},
            "method": {"type": "string", "default": "POST"},
            "secret": {"type": "string", "secret": True},
            "authorization_header": {"type": "string", "secret": True},
        },
    },
    {
        "id": "hubspot",
        "provider": "hubspot",
        "name": "HubSpot",
        "auth_type": "private_app_token",
        "secret_fields": ["access_token"],
        "config_schema": {"access_token": {"type": "string", "secret": True}},
    },
    {
        "id": "salesforce",
        "provider": "salesforce",
        "name": "Salesforce",
        "auth_type": "api_credentials",
        "secret_fields": ["client_secret", "refresh_token", "access_token"],
        "config_schema": {
            "instance_url": {"type": "string", "required": True},
            "client_id": {"type": "string"},
            "client_secret": {"type": "string", "secret": True},
            "refresh_token": {"type": "string", "secret": True},
            "access_token": {"type": "string", "secret": True},
        },
    },
    {
        "id": "zendesk",
        "provider": "zendesk",
        "name": "Zendesk",
        "auth_type": "api_token",
        "secret_fields": ["api_token"],
        "config_schema": {
            "subdomain": {"type": "string", "required": True},
            "email": {"type": "string"},
            "api_token": {"type": "string", "secret": True},
        },
    },
    {
        "id": "slack",
        "provider": "slack",
        "name": "Slack",
        "auth_type": "bot_token",
        "secret_fields": ["bot_token", "signing_secret"],
        "config_schema": {
            "bot_token": {"type": "string", "secret": True},
            "signing_secret": {"type": "string", "secret": True},
            "default_channel": {"type": "string"},
        },
    },
    {
        "id": "google_sheets",
        "provider": "google",
        "name": "Google Sheets",
        "auth_type": "service_account",
        "secret_fields": ["service_account_json"],
        "config_schema": {
            "spreadsheet_id": {"type": "string", "required": True},
            "service_account_json": {"type": "string", "secret": True},
        },
    },
    {
        "id": "airtable",
        "provider": "airtable",
        "name": "Airtable",
        "auth_type": "personal_access_token",
        "secret_fields": ["personal_access_token"],
        "config_schema": {
            "base_id": {"type": "string", "required": True},
            "personal_access_token": {"type": "string", "secret": True},
        },
    },
    {
        "id": "notion",
        "provider": "notion",
        "name": "Notion",
        "auth_type": "integration_token",
        "secret_fields": ["integration_token"],
        "config_schema": {
            "database_id": {"type": "string"},
            "integration_token": {"type": "string", "secret": True},
        },
    },
    {
        "id": "zapier_webhook",
        "provider": "zapier",
        "name": "Zapier Webhook",
        "auth_type": "webhook_url",
        "secret_fields": ["webhook_url", "secret"],
        "config_schema": {
            "webhook_url": {"type": "string", "required": True, "secret": True},
            "secret": {"type": "string", "secret": True},
        },
    },
    {
        "id": "n8n_webhook",
        "provider": "n8n",
        "name": "n8n Webhook",
        "auth_type": "webhook_url",
        "secret_fields": ["webhook_url", "secret"],
        "config_schema": {
            "webhook_url": {"type": "string", "required": True, "secret": True},
            "secret": {"type": "string", "secret": True},
        },
    },
]


class ToolRegistryService:
    def __init__(self) -> None:
        self._tools_by_id = {tool["id"]: tool for tool in TOOL_REGISTRY}

    def list_tools(self) -> list[dict[str, Any]]:
        return deepcopy(TOOL_REGISTRY)

    def get_tool(self, tool_id: str) -> dict[str, Any] | None:
        tool = self._tools_by_id.get(tool_id)
        return deepcopy(tool) if tool else None

    def secret_fields_for(self, tool_id: str) -> list[str]:
        tool = self._tools_by_id.get(tool_id) or {}
        return list(tool.get("secret_fields") or [])

    def agent_config_shape(self) -> dict[str, Any]:
        return {
            "tools": {
                tool["id"]: {
                    "enabled": False,
                    "provider": tool["provider"],
                    "config": {
                        key: field.get("default")
                        for key, field in tool.get("config_schema", {}).items()
                        if "default" in field and not field.get("secret")
                    },
                }
                for tool in TOOL_REGISTRY
            }
        }

    def enabled_runtime_tools(self, agent_config: dict[str, Any] | None) -> list[BaseTool]:
        config = agent_config or {}
        raw_tools = config.get("tools") or {}
        enabled_entries: list[tuple[str, dict[str, Any]]] = []

        if isinstance(raw_tools, list):
            for entry in raw_tools:
                if not isinstance(entry, dict) or not entry.get("enabled"):
                    continue
                tool_id = entry.get("tool_id") or entry.get("id")
                if tool_id:
                    enabled_entries.append((str(tool_id), entry))
        elif isinstance(raw_tools, dict):
            selected = raw_tools.get("selected") or raw_tools.get("selected_tool_ids") or []
            if isinstance(selected, list):
                enabled_entries.extend((str(tool_id), {"enabled": True}) for tool_id in selected)
            for tool_id, entry in raw_tools.items():
                if isinstance(entry, dict) and entry.get("enabled"):
                    enabled_entries.append((str(tool_id), entry))

        runtime_tools: list[BaseTool] = []
        seen_tool_ids: set[str] = set()
        for tool_id, entry in enabled_entries:
            if tool_id in seen_tool_ids:
                continue
            seen_tool_ids.add(tool_id)
            definition = self.get_tool(tool_id)
            if definition:
                runtime_tools.append(ConfiguredExternalTool(definition, entry))
        return runtime_tools


class ConfiguredExternalTool(BaseTool):
    """Runtime-safe adapter for allowlisted external tool definitions."""

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "The intended action to perform with this integration.",
            },
            "payload": {
                "type": "object",
                "description": "Structured payload for the external integration.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, definition: dict[str, Any], agent_tool_config: dict[str, Any]):
        self.definition = deepcopy(definition)
        self.agent_tool_config = deepcopy(agent_tool_config or {})
        self.name = f"tool_{self.definition['id']}"
        self.description = (
            f"Use the configured {self.definition.get('name', self.definition['id'])} integration. "
            "Only call this when the task explicitly requires this connected external system."
        )

    async def run(self, action: str, payload: dict[str, Any] | None = None, **kwargs) -> ToolResult:
        return ToolResult(
            success=False,
            data=None,
            error=(
                f"{self.definition.get('name', self.definition['id'])} is connected in the agent "
                "configuration, but this v1 runtime only exposes the allowlisted capability. "
                "A provider executor is required before live external actions can run."
            ),
            metadata={
                "tool_id": self.definition["id"],
                "provider": self.definition.get("provider"),
                "action": action,
                "payload_keys": sorted((payload or {}).keys()),
            },
        )


def _parse_auth_header(raw_header: str | None) -> dict[str, str]:
    if not raw_header or ":" not in raw_header:
        return {}
    key, value = raw_header.split(":", 1)
    key = key.strip()
    value = value.strip()
    if not key or "\n" in key or "\r" in key or "\n" in value or "\r" in value:
        return {}
    return {key: value}


def _is_safe_external_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "invalid_url"
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        return False, "unsupported_url"
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return False, "local_urls_blocked"
    try:
        resolved = socket.getaddrinfo(parsed.hostname, None)
        for family, *_rest in resolved:
            address = _rest[-1][0]
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "private_network_blocked"
    except Exception:
        return False, "dns_resolution_failed"
    return True, ""


class ApiDataSourceTool(BaseTool):
    """Live, allowlisted HTTP executor for an agent's configured API data source."""

    name = "tool_api_data_source"
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The user's question or lookup task.",
            },
            "payload": {
                "type": "object",
                "description": "Structured fields required by the API, such as birth_date, birth_time, birth_place, sku, or customer inputs.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, config: dict[str, Any]):
        self.config = deepcopy(config or {})
        name = self.config.get("name") or "API Data Source"
        usage = self.config.get("usage") or "Use this source for approved external context."
        self.description = (
            f"Call the configured {name}. {usage} "
            "Use only when external API context is needed and include only the user's provided fields."
        )

    async def run(self, query: str, payload: dict[str, Any] | None = None, **kwargs) -> ToolResult:
        url = str(self.config.get("url") or "").strip()
        source_name = self.config.get("name") or "API Data Source"
        safe, reason = _is_safe_external_url(url)
        if not safe:
            return ToolResult(
                success=False,
                data=None,
                error=f"Configured API data source URL is not allowed: {reason}",
                metadata={
                    "tool_id": "api_data_source",
                    "provider": "http",
                    "source_name": source_name,
                    "url": url,
                    "blocked_reason": reason,
                },
            )

        body = {
            "query": query,
            "payload": payload or {},
            "usage": self.config.get("usage") or "",
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_parse_auth_header(self.config.get("auth_header")),
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                data: Any
                if "application/json" in content_type:
                    data = response.json()
                else:
                    data = response.text[:8000]
        except httpx.HTTPError as exc:
            return ToolResult(
                success=False,
                data=None,
                error=str(exc),
                metadata={
                    "tool_id": "api_data_source",
                    "provider": "http",
                    "source_name": source_name,
                    "url": url,
                },
            )

        serialized = json.dumps(data, default=str) if not isinstance(data, str) else data
        return ToolResult(
            success=True,
            data=data,
            metadata={
                "tool_id": "api_data_source",
                "provider": "http",
                "source_name": source_name,
                "url": url,
                "sources": [
                    {
                        "title": source_name,
                        "url": url,
                        "snippet": serialized[:500],
                    }
                ],
                "confidence": 0.9,
            },
        )
