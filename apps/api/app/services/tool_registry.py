from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlparse
import ipaddress
import json
import re
import socket
import time

import httpx
from app.config import Settings
from tools.mcp_client import McpTool
from tools.types import BaseTool, ToolResult

settings = Settings()

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

    def enabled_context_connector_tools(self, agent_config: dict[str, Any] | None, remembered_inputs: dict[str, Any] | None = None) -> list[BaseTool]:
        """Generate runtime tools from enabled context connector HTTP endpoints.

        `remembered_inputs` are conversation-remembered required-field values so
        follow-up turns reuse earlier inputs (universal for any connector agent).
        """
        config = agent_config or {}
        connectors = config.get("context_connectors") if isinstance(config.get("context_connectors"), list) else []

        # Legacy import/fallback only: new admin saves should write context_connectors.
        if not connectors and isinstance(config.get("api_data_source"), dict):
            legacy = config.get("api_data_source") or {}
            if legacy.get("enabled") and str(legacy.get("url") or "").strip():
                connectors = [
                    {
                        "id": "legacy_api_data_source",
                        "name": legacy.get("name") or "Legacy API Data Source",
                        "type": "http_api",
                        "enabled": True,
                        "usage_policy": legacy.get("usage") or "",
                        "auth": {"type": "raw_header", "auth_header": legacy.get("auth_header")},
                        "endpoints": [
                            {
                                "id": "default",
                                "name": legacy.get("name") or "Default API Lookup",
                                "enabled": True,
                                "method": "POST",
                                "url_template": legacy.get("url"),
                                "tool_description": legacy.get("usage") or "Call the configured API data source.",
                            }
                        ],
                    }
                ]

        runtime_tools: list[BaseTool] = []
        for connector in connectors:
            if not isinstance(connector, dict) or not connector.get("enabled") or connector.get("revoked"):
                continue
            if connector.get("type") == "mcp":
                endpoint = str(connector.get("endpoint") or (connector.get("mcp") or {}).get("endpoint") or "").strip()
                if not endpoint:
                    continue
                if not _host_allowed(endpoint, _effective_domain_allowlist(connector, endpoint)):
                    continue
                allowed_tools = {
                    str(tool_name)
                    for tool_name in (connector.get("allowed_tools") or [])
                    if tool_name
                }
                headers = {}
                if isinstance((connector.get("mcp") or {}).get("headers"), dict):
                    headers.update((connector.get("mcp") or {}).get("headers"))
                if isinstance(connector.get("headers"), dict):
                    headers.update(connector.get("headers"))
                if isinstance(connector.get("auth"), dict):
                    headers.update(_connector_auth_headers(connector.get("auth")))
                for tool_def in connector.get("discovered_tools") or []:
                    if not isinstance(tool_def, dict):
                        continue
                    tool_name = str(tool_def.get("name") or tool_def.get("id") or "")
                    if not tool_name or (allowed_tools and tool_name not in allowed_tools):
                        continue
                    runtime_tools.append(
                        ContextMcpTool(
                            connector=connector,
                            name=tool_name,
                            description=tool_def.get("description") or f"Call MCP tool {tool_name}.",
                            parameters_schema=tool_def.get("inputSchema") or tool_def.get("parameters_schema") or {},
                            mcp_endpoint=endpoint,
                            session_id=f"agent:{config.get('id') or connector.get('id') or 'context'}",
                            headers=headers,
                        )
                    )
                continue
            if connector.get("type") not in {"http_api", "http"}:
                continue
            for endpoint in connector.get("endpoints") or []:
                if not isinstance(endpoint, dict):
                    continue
                if not endpoint.get("enabled") or endpoint.get("revoked"):
                    continue
                url_template = str(endpoint.get("url_template") or endpoint.get("url") or "").strip()
                if not url_template:
                    continue
                if not _effective_domain_allowlist(connector, url_template):
                    continue
                runtime_tools.append(ContextConnectorTool(connector, endpoint, remembered_inputs=remembered_inputs))
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


class ContextMcpTool(McpTool):
    """MCP tool wrapper that applies connector runtime safety before execution."""

    def __init__(self, *, connector: dict[str, Any], **kwargs):
        super().__init__(**kwargs)
        self.connector = deepcopy(connector or {})

    async def run(self, **kwargs) -> ToolResult:
        connector_name = self.connector.get("name") or self.connector.get("id") or "MCP Connector"
        safe, reason = _is_safe_external_url(self.mcp_endpoint)
        if not safe:
            return ToolResult(
                success=False,
                data=None,
                error=f"Configured MCP endpoint is not allowed: {reason}",
                metadata={
                    "tool_id": "context_connector_mcp",
                    "connector_id": self.connector.get("id"),
                    "connector_name": connector_name,
                    "endpoint_name": self.name,
                    "url": _redacted_url(self.mcp_endpoint),
                    "blocked_reason": reason,
                },
            )
        if not _host_allowed(self.mcp_endpoint, _effective_domain_allowlist(self.connector, self.mcp_endpoint)):
            return ToolResult(
                success=False,
                data=None,
                error="Configured MCP endpoint host is not in the connector allowlist.",
                metadata={
                    "tool_id": "context_connector_mcp",
                    "connector_id": self.connector.get("id"),
                    "connector_name": connector_name,
                    "endpoint_name": self.name,
                    "url": _redacted_url(self.mcp_endpoint),
                    "blocked_reason": "domain_not_allowlisted",
                },
            )

        started = time.perf_counter()
        result = await super().run(**kwargs)
        result.metadata = {
            **(result.metadata or {}),
            "tool_id": "context_connector_mcp",
            "connector_id": self.connector.get("id"),
            "connector_name": connector_name,
            "endpoint_name": self.name,
            "url": _redacted_url(self.mcp_endpoint),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "request_shape": {
                "payload_keys": sorted(kwargs.keys()),
                "headers": _redacted_headers(self.headers),
            },
        }
        return result


def _safe_tool_part(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "")).strip("_").lower()
    return text[:48] or "connector"


def _parse_auth_header(raw_header: str | None) -> dict[str, str]:
    if not raw_header or ":" not in raw_header:
        return {}
    key, value = raw_header.split(":", 1)
    key = key.strip()
    value = value.strip()
    if not key or "\n" in key or "\r" in key or "\n" in value or "\r" in value:
        return {}
    return {key: value}


def _connector_auth_headers(auth: dict[str, Any] | None) -> dict[str, str]:
    auth = auth or {}
    auth_type = str(auth.get("type") or "").lower()
    if auth_type == "bearer":
        token = auth.get("token") or auth.get("value") or auth.get("bearer_token")
        return {"Authorization": f"Bearer {token}"} if token else {}
    if auth_type == "api_key":
        header_name = auth.get("header_name") or "X-API-Key"
        api_key = auth.get("api_key") or auth.get("value") or auth.get("token")
        return {str(header_name): str(api_key)} if api_key else {}
    if auth_type == "raw_header":
        raw_header = auth.get("auth_header") or auth.get("authorization_header") or auth.get("value")
        parsed = _parse_auth_header(raw_header)
        if parsed:
            return parsed
        if isinstance(raw_header, str) and raw_header.strip():
            return {"Authorization": f"Bearer {raw_header.strip()}"}
    return {}


def _redacted_headers(headers: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in headers.keys())


def _connector_required_fields(endpoint: dict[str, Any]) -> list[str]:
    fields = endpoint.get("runtime_required_fields") or endpoint.get("required_user_fields") or endpoint.get("required_fields") or []
    return [str(field) for field in fields if field]


def _build_connector_request_payload(
    *,
    connector: dict[str, Any],
    endpoint: dict[str, Any],
    query: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload_mode = str(endpoint.get("payload_mode") or "wrapped")
    if payload_mode == "flat_body":
        field_mapping = endpoint.get("field_mapping") if isinstance(endpoint.get("field_mapping"), dict) else {}
        body_schema = endpoint.get("body_schema") if isinstance(endpoint.get("body_schema"), dict) else {}
        schema_properties = body_schema.get("properties") if isinstance(body_schema.get("properties"), dict) else {}
        allowed_body_fields = {str(field) for field in schema_properties.keys()} if schema_properties else set()
        mapped_payload: dict[str, Any] = {}
        consumed_sources: set[str] = set()
        mapped_targets = {str(target) for target in field_mapping.values() if target}
        for source, target in field_mapping.items():
            if not source or not target:
                continue
            if payload.get(source) is not None:
                if allowed_body_fields and str(target) not in allowed_body_fields:
                    consumed_sources.add(str(source))
                    continue
                mapped_payload[str(target)] = payload.get(source)
                consumed_sources.add(str(source))
        for key, value in payload.items():
            if key in consumed_sources or value is None:
                continue
            if key == "birth_place" and key not in mapped_targets:
                continue
            if allowed_body_fields and str(key) not in allowed_body_fields:
                continue
            mapped_payload[str(key)] = value
        return mapped_payload, {
            "payload_mode": "flat_body",
            "mapped_body_keys": sorted(mapped_payload.keys()),
        }

    request_payload = {
        "query": query,
        "payload": payload,
        "usage_policy": connector.get("usage_policy") or "",
    }
    return request_payload, {
        "payload_mode": "wrapped",
        "payload_keys": sorted(payload.keys()),
    }


def _render_url_template(url_template: str, payload: dict[str, Any]) -> str:
    rendered = url_template
    for key, value in (payload or {}).items():
        if isinstance(value, (str, int, float, bool)):
            rendered = rendered.replace("{" + str(key) + "}", str(value))
    return rendered


def _host_from_url_template(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(str(url))
    if "{" in (parsed.netloc or "") or "}" in (parsed.netloc or ""):
        return None
    return (parsed.hostname or "").lower() or None


def _effective_domain_allowlist(connector: dict[str, Any], url: str | None = None) -> list[str]:
    allowlist = [
        str(item).lower().strip()
        for item in (connector.get("domain_allowlist") or [])
        if str(item or "").strip()
    ]
    if allowlist:
        return allowlist
    host = _host_from_url_template(url)
    return [host] if host else []


def _redacted_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return parsed._replace(query="", fragment="").geturl()


def _host_allowed(url: str, allowlist: list[Any] | None) -> bool:
    if not allowlist:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    for allowed in allowlist:
        allowed_host = str(allowed or "").lower().strip()
        if not allowed_host:
            continue
        if host == allowed_host or host.endswith(f".{allowed_host}"):
            return True
    return False


def _is_safe_external_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "invalid_url"
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        return False, "unsupported_url"
    if parsed.scheme == "http" and settings.is_production:
        return False, "insecure_http_blocked"
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


class ContextConnectorTool(BaseTool):
    """Runtime HTTP executor generated from an agent-scoped context connector endpoint."""

    def __init__(self, connector: dict[str, Any], endpoint: dict[str, Any], remembered_inputs: dict[str, Any] | None = None):
        self.connector = deepcopy(connector or {})
        self.endpoint = deepcopy(endpoint or {})
        # Conversation-remembered values for this connector's required fields, so
        # a follow-up turn does not have to re-supply them (universal for any
        # connector agent: birthplace, location, account id, etc.).
        self.remembered_inputs = {k: v for k, v in (remembered_inputs or {}).items() if v not in (None, "")}
        connector_id = self.connector.get("id") or self.connector.get("name") or "connector"
        endpoint_id = self.endpoint.get("id") or self.endpoint.get("name") or "endpoint"
        self.name = f"tool_context_{_safe_tool_part(connector_id)}_{_safe_tool_part(endpoint_id)}"
        self.description = (
            self.endpoint.get("tool_description")
            or f"Call {self.endpoint.get('name') or endpoint_id} from {self.connector.get('name') or connector_id}. "
            "Use only when this approved context source is required."
        )
        required_fields = _connector_required_fields(self.endpoint)
        payload_properties = {
            field: {"type": "string", "description": f"Required user-provided field: {field}"}
            for field in required_fields
        }
        self.parameters_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's question or lookup task.",
                },
                "payload": {
                    "type": "object",
                    "properties": payload_properties,
                    "description": "Structured fields needed by this connector endpoint.",
                },
            },
            "required": ["query"],
        }

    async def run(self, query: str, payload: dict[str, Any] | None = None, **kwargs) -> ToolResult:
        payload = dict(payload or {})
        required_fields = _connector_required_fields(self.endpoint)
        # Fill any required field the caller omitted from conversation memory, so
        # follow-up turns reuse earlier-resolved inputs instead of failing.
        for field in required_fields:
            if payload.get(field) in (None, "") and self.remembered_inputs.get(field) not in (None, ""):
                payload[field] = self.remembered_inputs[field]
        missing = [field for field in required_fields if not payload.get(field)]
        connector_name = self.connector.get("name") or self.connector.get("id") or "Context Connector"
        endpoint_name = self.endpoint.get("name") or self.endpoint.get("id") or "Endpoint"

        if missing:
            return ToolResult(
                success=False,
                data=None,
                error=f"Missing required fields for {endpoint_name}: {', '.join(missing)}",
                metadata={
                    "tool_id": "context_connector",
                    "connector_id": self.connector.get("id"),
                    "connector_name": connector_name,
                    "endpoint_id": self.endpoint.get("id"),
                    "endpoint_name": endpoint_name,
                    "missing_input": missing,
                },
            )

        method = str(self.endpoint.get("method") or "POST").upper()
        if method not in {"GET", "POST", "PUT", "PATCH"}:
            return ToolResult(
                success=False,
                data=None,
                error=f"HTTP method {method} is not allowed for context connectors.",
                metadata={"tool_id": "context_connector", "blocked_reason": "method_not_allowed"},
            )

        url_template = str(self.endpoint.get("url_template") or self.endpoint.get("url") or "")
        allowlist = _effective_domain_allowlist(self.connector, url_template)
        if not allowlist:
            return ToolResult(
                success=False,
                data=None,
                error="Configured connector endpoint requires a concrete domain allowlist.",
                metadata={
                    "tool_id": "context_connector",
                    "connector_id": self.connector.get("id"),
                    "connector_name": connector_name,
                    "endpoint_id": self.endpoint.get("id"),
                    "endpoint_name": endpoint_name,
                    "blocked_reason": "domain_allowlist_required",
                },
            )

        url = _render_url_template(url_template, payload)
        if not _host_allowed(url, allowlist):
            return ToolResult(
                success=False,
                data=None,
                error="Configured connector endpoint host is not in the connector allowlist.",
                metadata={
                    "tool_id": "context_connector",
                    "connector_id": self.connector.get("id"),
                    "connector_name": connector_name,
                    "endpoint_id": self.endpoint.get("id"),
                    "endpoint_name": endpoint_name,
                    "url": _redacted_url(url),
                    "blocked_reason": "domain_not_allowlisted",
                },
            )
        safe, reason = _is_safe_external_url(url)
        if not safe:
            return ToolResult(
                success=False,
                data=None,
                error=f"Configured connector endpoint URL is not allowed: {reason}",
                metadata={
                    "tool_id": "context_connector",
                    "connector_id": self.connector.get("id"),
                    "connector_name": connector_name,
                    "endpoint_id": self.endpoint.get("id"),
                    "endpoint_name": endpoint_name,
                    "url": _redacted_url(url),
                    "blocked_reason": reason,
                },
            )

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(self.connector.get("headers") or {}),
            **(self.endpoint.get("headers") or {}),
            **_connector_auth_headers(self.connector.get("auth") if isinstance(self.connector.get("auth"), dict) else {}),
        }
        timeout = min(max(float(self.endpoint.get("timeout_seconds") or self.connector.get("timeout_seconds") or 20), 1), 60)
        max_response_chars = min(max(int(self.endpoint.get("max_response_chars") or self.connector.get("max_response_chars") or 12000), 1000), 50000)
        retry_count = min(max(int(self.endpoint.get("retry_count") or self.connector.get("retry_count") or 0), 0), 2)
        started = time.perf_counter()

        request_payload, request_shape_extra = _build_connector_request_payload(
            connector=self.connector,
            endpoint=self.endpoint,
            query=query,
            payload=payload,
        )
        try:
            last_exc: httpx.HTTPError | None = None
            async with httpx.AsyncClient(timeout=timeout) as client:
                for attempt in range(retry_count + 1):
                    try:
                        if method == "GET":
                            response = await client.get(url, params=request_payload if self.endpoint.get("payload_mode") == "flat_body" else payload, headers=headers)
                        else:
                            response = await client.request(method, url, json=request_payload, headers=headers)
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "")
                        raw_text = response.text
                        if len(raw_text) > max_response_chars:
                            return ToolResult(
                                success=False,
                                data=None,
                                error="Configured connector response exceeded the maximum allowed size.",
                                metadata={
                                    "tool_id": "context_connector",
                                    "connector_id": self.connector.get("id"),
                                    "connector_name": connector_name,
                                    "endpoint_id": self.endpoint.get("id"),
                                    "endpoint_name": endpoint_name,
                                    "url": _redacted_url(url),
                                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                                    "blocked_reason": "response_too_large",
                                },
                            )
                        data: Any = response.json() if "application/json" in content_type else raw_text
                        break
                    except httpx.HTTPError as exc:
                        last_exc = exc
                        if attempt >= retry_count:
                            raise
        except httpx.HTTPError as exc:
            return ToolResult(
                success=False,
                data=None,
                error=str(exc),
                metadata={
                    "tool_id": "context_connector",
                    "connector_id": self.connector.get("id"),
                    "connector_name": connector_name,
                    "endpoint_id": self.endpoint.get("id"),
                    "endpoint_name": endpoint_name,
                    "url": _redacted_url(url),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )

        serialized = json.dumps(data, default=str) if not isinstance(data, str) else data
        if len(serialized) > max_response_chars:
            serialized = serialized[:max_response_chars]

        return ToolResult(
            success=True,
            data=data,
            metadata={
                "tool_id": "context_connector",
                "connector_id": self.connector.get("id"),
                "connector_name": connector_name,
                "endpoint_id": self.endpoint.get("id"),
                "endpoint_name": endpoint_name,
                "url": _redacted_url(url),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                # The required-field values actually used — persisted into
                # conversation memory so later turns can reuse them.
                "resolved_inputs": {field: payload.get(field) for field in required_fields if payload.get(field) not in (None, "")},
                "request_shape": {
                    "method": method,
                    "required_user_fields": required_fields,
                    "headers": _redacted_headers(headers),
                    **request_shape_extra,
                },
                "sources": [
                    {
                        "title": f"{connector_name} · {endpoint_name}",
                        "url": _redacted_url(url),
                        "snippet": serialized[:500],
                    }
                ],
                "response_summary": serialized[:1000],
            },
        )
