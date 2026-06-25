from __future__ import annotations

from copy import deepcopy
import inspect
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin.connectors import router as connectors_router
from app.auth.dependencies import require_dashboard_access
from app.auth.models import User, UserRole
from app.connections import connection_manager
from app.dependencies import get_runtime_settings_service
from app.services import agent_manifest_service, tool_config_secrets
from app.services.agent_manifest_service import AgentManifestService
from app.services.context_connector_packs import get_connector_pack
from app.services.lalkitab_runtime import (
    build_lalkitab_runtime_context,
    extract_lalkitab_birth_input,
    select_lalkitab_endpoint_ids,
)
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.tool_config_secrets import (
    decrypt_full_agent_configuration_for_runtime,
    expose_full_agent_for_admin,
    protect_full_agent_configuration_secrets,
)
from app.services.tool_registry import ContextConnectorTool, ToolRegistryService, _build_connector_request_payload, _connector_auth_headers
from tools.types import ToolResult


class FakeUpdateResult:
    def __init__(self, matched_count=0):
        self.matched_count = matched_count


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = [deepcopy(document) for document in (documents or [])]

    def _matches(self, document, query):
        for key, value in (query or {}).items():
            if document.get(key) != value:
                return False
        return True

    async def find_one(self, query):
        for document in self.documents:
            if self._matches(document, query):
                return deepcopy(document)
        return None

    async def update_one(self, query, update):
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                self.documents[index] = document
                return FakeUpdateResult(matched_count=1)
        return FakeUpdateResult()


class FakeSystemDb:
    def __init__(self, agents=None):
        self.agents = FakeCollection(agents)


def runtime_settings_service() -> RuntimeSettingsService:
    return RuntimeSettingsService(
        SimpleNamespace(
            SETTINGS_ENCRYPTION_KEY="test-settings-encryption-key",
            PII_ENCRYPTION_KEY="",
            SECRET_KEY="test-secret-key",
        )
    )


def sample_context_connectors(auth_token: str = "connector-secret") -> list[dict]:
    return [
        {
            "id": "weather",
            "type": "http_api",
            "name": "Weather Context",
            "enabled": True,
            "auth": {"type": "bearer", "token": auth_token},
            "usage_policy": "Fetch approved weather context.",
            "endpoints": [
                {
                    "id": "forecast",
                    "name": "Forecast",
                    "method": "GET",
                    "url_template": "https://api.example.com/forecast",
                    "enabled": True,
                    "required_fields": ["city"],
                    "tool_description": "Fetch a forecast by city.",
                },
                {
                    "id": "disabled_endpoint",
                    "name": "Disabled Endpoint",
                    "method": "GET",
                    "url_template": "https://api.example.com/disabled",
                    "enabled": False,
                    "required_fields": [],
                },
                {
                    "id": "revoked_endpoint",
                    "name": "Revoked Endpoint",
                    "method": "POST",
                    "url_template": "https://api.example.com/revoked",
                    "enabled": True,
                    "revoked": True,
                    "required_fields": [],
                },
            ],
        },
    ]


def _module_mentions_context_connectors(module) -> bool:
    try:
        return "context_connectors" in inspect.getsource(module)
    except OSError:
        return False


def _require_context_connector_secret_helpers() -> None:
    if not _module_mentions_context_connectors(tool_config_secrets):
        pytest.skip("context_connectors secret helpers are not implemented yet")


def _require_context_connector_runtime_helpers() -> None:
    if not hasattr(ToolRegistryService, "enabled_context_connector_tools"):
        pytest.skip("context_connectors runtime tool generation is not implemented yet")


def _require_context_connector_manifest_helpers() -> None:
    if not _module_mentions_context_connectors(agent_manifest_service):
        pytest.skip("context_connectors manifest support is not implemented yet")


def _find_connector(config: dict, connector_id: str) -> dict:
    for connector in config.get("context_connectors") or []:
        if connector.get("id") == connector_id:
            return connector
    raise AssertionError(f"missing connector {connector_id!r}")


def _serialized_runtime_tools_for(config: dict) -> str:
    _require_context_connector_runtime_helpers()
    service = ToolRegistryService()
    tools = service.enabled_context_connector_tools(config)
    tools = [
        {
            "name": tool.name,
            "description": getattr(tool, "description", ""),
            "parameters_schema": getattr(tool, "parameters_schema", {}),
        }
        for tool in tools
    ]
    return json.dumps(tools, sort_keys=True)


def _agent_doc_with_context_connectors() -> dict:
    return {
        "id": "agent-1",
        "brand_id": "brand-1",
        "brand_slug": "brand-one",
        "slug": "portable-agent",
        "name": "Portable Agent",
        "description": "A generic portable agent.",
        "system_prompt": "Be helpful.",
        "metadata": {"purpose": "Support", "role": "Assistant"},
        "configuration": {
            "llm": {"provider": "azure_openai", "model": "gpt-4.1"},
            "prompt_layers": {"soul": "Be helpful."},
            "data_source": "none",
            "context_connectors": sample_context_connectors(),
        },
    }


def _test_user(role: UserRole, brands: list[str] | None = None) -> User:
    return User(
        _id=f"user-{role.value}",
        email=f"{role.value}@example.com",
        username=role.value,
        password_hash="hash",
        role=role,
        brands=brands or [],
        is_active=True,
    )


def _connector_route_client(monkeypatch, user: User | None, agents: list[dict]) -> tuple[TestClient, FakeSystemDb]:
    app = FastAPI()
    app.include_router(connectors_router, prefix="/agents")
    app.dependency_overrides[require_dashboard_access] = lambda: user
    app.dependency_overrides[get_runtime_settings_service] = runtime_settings_service
    fake_db = FakeSystemDb(agents=agents)
    monkeypatch.setattr(connection_manager, "system_db", fake_db)
    return TestClient(app), fake_db


def test_context_connector_secrets_are_masked_and_blank_updates_preserve_existing_secret():
    _require_context_connector_secret_helpers()
    service = runtime_settings_service()
    protected = protect_full_agent_configuration_secrets(
        {"context_connectors": sample_context_connectors()},
        runtime_settings_service=service,
    )

    connector = _find_connector(protected, "weather")
    assert "token" not in connector["auth"]
    assert connector["auth"]["token_encrypted"] != "connector-secret"

    admin_agent = expose_full_agent_for_admin({"configuration": protected}, service)
    admin_connector = _find_connector(admin_agent["configuration"], "weather")
    assert admin_connector["auth"]["token_configured"] is True
    assert "token" not in admin_connector["auth"]
    assert "token_encrypted" not in admin_connector["auth"]

    updated_connectors = sample_context_connectors(auth_token="")
    updated = protect_full_agent_configuration_secrets(
        {"context_connectors": updated_connectors},
        existing_config=protected,
        runtime_settings_service=service,
    )
    runtime = decrypt_full_agent_configuration_for_runtime(updated, service)
    runtime_connector = _find_connector(runtime, "weather")
    assert runtime_connector["auth"]["token"] == "connector-secret"


def test_legacy_api_data_source_save_migrates_to_context_connectors():
    service = runtime_settings_service()
    protected = protect_full_agent_configuration_secrets(
        {
            "api_data_source": {
                "enabled": True,
                "name": "Astrology API",
                "url": "https://api.example.com/lal-kitab",
                "auth_header": "Authorization: Bearer legacy-secret",
                "usage": "Fetch Lal Kitab chart context.",
            }
        },
        runtime_settings_service=service,
    )

    assert "api_data_source" not in protected
    connector = _find_connector(protected, "legacy_api_data_source")
    assert connector["name"] == "Astrology API"
    assert connector["endpoints"][0]["url_template"] == "https://api.example.com/lal-kitab"
    assert "auth_header" not in connector["auth"]
    assert connector["auth"]["auth_header_encrypted"] != "Authorization: Bearer legacy-secret"

    runtime = decrypt_full_agent_configuration_for_runtime(protected, service)
    runtime_connector = _find_connector(runtime, "legacy_api_data_source")
    assert runtime_connector["auth"]["auth_header"] == "Authorization: Bearer legacy-secret"


def test_runtime_connector_tools_expose_enabled_endpoints_only():
    serialized_tools = _serialized_runtime_tools_for(
        {"context_connectors": sample_context_connectors()}
    )

    assert "forecast" in serialized_tools
    assert "disabled_endpoint" not in serialized_tools
    assert "Disabled Endpoint" not in serialized_tools
    assert "revoked_endpoint" not in serialized_tools
    assert "Revoked Endpoint" not in serialized_tools


def test_vedika_lal_kitab_pack_uses_v2_flat_chart_first_schema():
    pack = get_connector_pack("vedika_lal_kitab")

    assert pack
    endpoints = {endpoint["id"]: endpoint for endpoint in pack["endpoints"]}
    assert {
        "lalkitab_chart",
        "lalkitab_debts",
        "lalkitab_houses",
        "lalkitab_lucky",
        "lalkitab_predictions",
        "lalkitab_remedies",
        "lalkitab_totke",
        "lalkitab_varshphal",
    } <= set(endpoints)
    # Geocoding endpoints are part of the pack for birthplace resolution.
    assert {"geocode_search", "geocode_resolve"} <= set(endpoints)
    assert endpoints["geocode_search"]["method"] == "GET"
    assert endpoints["geocode_search"]["url_template"] == "https://api.vedika.io/v2/geocode/search"
    assert endpoints["geocode_resolve"]["url_template"] == "https://api.vedika.io/v2/geocode/resolve"
    chart = endpoints["lalkitab_chart"]
    assert chart["url_template"] == "https://api.vedika.io/v2/astrology/lalkitab/chart"
    assert chart["execution_order"] == 1
    assert chart["payload_mode"] == "flat_body"
    assert chart["runtime_required_fields"] == ["datetime", "latitude", "longitude", "timezone"]
    assert chart["timeout_seconds"] == 45
    assert chart["retry_count"] == 1
    assert chart["max_response_chars"] == 50000
    assert endpoints["lalkitab_remedies"]["requires_prior_endpoint"] == "lalkitab_chart"


def test_flat_body_connector_payload_maps_vedika_fields():
    body, shape = _build_connector_request_payload(
        connector={"usage_policy": "Use Vedika"},
        endpoint={
            "payload_mode": "flat_body",
            "field_mapping": {"birth_date": "date", "birth_time": "time"},
        },
        query="Fetch Lal Kitab chart",
        payload={
            "datetime": "1987-07-16T15:26:00",
            "birth_place": "Delhi",
            "latitude": 28.6139,
            "longitude": 77.209,
            "timezone": "+05:30",
        },
    )

    assert body == {
        "datetime": "1987-07-16T15:26:00",
        "latitude": 28.6139,
        "longitude": 77.209,
        "timezone": "+05:30",
    }
    assert shape["payload_mode"] == "flat_body"
    assert shape["mapped_body_keys"] == ["datetime", "latitude", "longitude", "timezone"]


def test_lalkitab_birth_input_extraction_resolves_common_birth_place_and_timezone():
    normalized, missing = extract_lalkitab_birth_input(
        'Name: Anant, DOB: 16 July 1987, Time of Birth: 1526 (IST india timezone). Place of Birth: Delhi, India. Question - "Will I build a company?"'
    )

    assert normalized["date"] == "1987-07-16"
    assert normalized["time"] == "15:26:00"
    assert normalized["datetime"] == "1987-07-16T15:26:00"
    assert normalized["birth_place"] == "Delhi, India"
    assert normalized["birth_place_resolved"] == "Delhi, India"
    assert normalized["latitude"] == 28.6139
    assert normalized["longitude"] == 77.209
    assert normalized["timezone"] == "+05:30"
    assert missing == []


def test_lalkitab_birth_input_unknown_place_still_requests_coordinates():
    normalized, missing = extract_lalkitab_birth_input(
        "DOB 1987-07-16 birth time 1526 birth place Small Unknown Town"
    )

    assert normalized["time"] == "15:26:00"
    assert missing == ["latitude", "longitude", "timezone"]


def test_connector_raw_auth_accepts_bare_api_key_as_bearer_token():
    assert _connector_auth_headers({"type": "raw_header", "auth_header": "vk_live_test"}) == {
        "Authorization": "Bearer vk_live_test"
    }
    assert _connector_auth_headers({"type": "raw_header", "auth_header": "X-API-Key: abc123"}) == {
        "X-API-Key": "abc123"
    }


def test_lalkitab_intent_selects_chart_first_then_relevant_endpoints():
    assert select_lalkitab_endpoint_ids("Please suggest remedies and totke") == [
        "lalkitab_chart",
        "lalkitab_remedies",
        "lalkitab_totke",
    ]
    full = select_lalkitab_endpoint_ids("Give me a full reading")
    assert full[0] == "lalkitab_chart"
    assert len(full) == 8


@pytest.mark.asyncio
async def test_lalkitab_runtime_calls_chart_before_secondary_endpoints(monkeypatch):
    pack = get_connector_pack("vedika_lal_kitab")
    calls: list[str] = []
    urls: list[str] = []
    for endpoint in pack["endpoints"]:
        endpoint["url_template"] = endpoint["url_template"].replace("/v2/astrology/lalkitab/", "/v1/lal-kitab/")

    async def fake_run(self, query, payload=None, **kwargs):
        endpoint_id = self.endpoint["id"]
        calls.append(endpoint_id)
        urls.append(self.endpoint["url_template"])
        return ToolResult(
            success=True,
            data={"endpoint": endpoint_id, "ok": True},
            metadata={
                "connector_id": self.connector.get("id"),
                "connector_name": self.connector.get("name"),
                "endpoint_id": endpoint_id,
                "endpoint_name": self.endpoint.get("name"),
                "url": self.endpoint.get("url_template"),
                "request_shape": {"payload_mode": self.endpoint.get("payload_mode")},
                "response_summary": endpoint_id,
                "latency_ms": 10,
            },
        )

    monkeypatch.setattr("app.services.lalkitab_runtime.ContextConnectorTool.run", fake_run)

    result = await build_lalkitab_runtime_context(
        {
            "domain": {"template": "astrology_lalkitab"},
            "context_connectors": [pack],
        },
        "DOB 1987-07-16 time 15:26:00 lat 28.6139 lon 77.209 timezone Asia/Kolkata. Give remedies.",
    )

    assert result.handled is True
    assert result.missing_input == []
    assert calls == ["lalkitab_chart", "lalkitab_remedies", "lalkitab_totke"]
    assert urls[0] == "https://api.vedika.io/v2/astrology/lalkitab/chart"
    assert result.api_context["chart_context"]["endpoint"] == "lalkitab_chart"
    assert sorted(result.api_context["secondary_endpoint_results"]) == ["lalkitab_remedies", "lalkitab_totke"]
    assert any(event["type"] == "api_context" for event in result.events)


@pytest.mark.asyncio
async def test_lalkitab_greeting_does_not_load_cached_context_or_call_connectors(monkeypatch):
    pack = get_connector_pack("vedika_lal_kitab")
    calls: list[str] = []

    async def fake_run(self, query, payload=None, **kwargs):
        calls.append(self.endpoint["id"])
        return ToolResult(success=True, data={"endpoint": self.endpoint["id"]}, metadata={})

    monkeypatch.setattr("app.services.lalkitab_runtime.ContextConnectorTool.run", fake_run)

    result = await build_lalkitab_runtime_context(
        {
            "domain": {"template": "astrology_lalkitab"},
            "context_connectors": [pack],
        },
        "hi",
        pending_state={
            "normalized_birth_input": {
                "date": "1987-07-16",
                "time": "15:26:00",
                "latitude": 28.6139,
                "longitude": 77.209,
                "timezone": "+05:30",
            },
            "api_context": {
                "normalized_birth_input": {
                    "date": "1987-07-16",
                    "time": "15:26:00",
                    "latitude": 28.6139,
                    "longitude": 77.209,
                    "timezone": "+05:30",
                },
                "chart_context": {"chart": "cached"},
                "secondary_endpoint_results": {"lalkitab_remedies": {"remedies": "cached"}},
            },
        },
    )

    assert result.handled is False
    assert calls == []


@pytest.mark.asyncio
async def test_lalkitab_followup_reuses_cached_context_without_connector_calls(monkeypatch):
    pack = get_connector_pack("vedika_lal_kitab")
    calls: list[str] = []

    async def fake_run(self, query, payload=None, **kwargs):
        calls.append(self.endpoint["id"])
        return ToolResult(success=True, data={"endpoint": self.endpoint["id"]}, metadata={})

    monkeypatch.setattr("app.services.lalkitab_runtime.ContextConnectorTool.run", fake_run)

    result = await build_lalkitab_runtime_context(
        {
            "domain": {"template": "astrology_lalkitab"},
            "context_connectors": [pack],
        },
        "what does that mean for me?",
        pending_state={
            "api_context": {
                "normalized_birth_input": {
                    "date": "1987-07-16",
                    "time": "15:26:00",
                    "latitude": 28.6139,
                    "longitude": 77.209,
                    "timezone": "+05:30",
                },
                "chart_context": {"chart": "cached"},
                "secondary_endpoint_results": {"lalkitab_predictions": {"prediction": "cached"}},
                "source_provenance": [{"endpoint_id": "lalkitab_chart"}],
            },
        },
    )

    assert result.handled is True
    assert result.used_cached_context is True
    assert result.api_context["chart_context"] == {"chart": "cached"}
    assert result.api_context["secondary_endpoint_results"] == {"lalkitab_predictions": {"prediction": "cached"}}
    assert calls == []


def test_connector_routes_enforce_role_and_brand_scope(monkeypatch):
    agents = [
        {"id": "agent-1", "brand_id": "brand-1", "configuration": {"context_connectors": []}},
        {"id": "agent-2", "brand_id": "brand-2", "configuration": {"context_connectors": []}},
    ]
    brand_admin = _test_user(UserRole.BRAND_ADMIN, ["brand-1"])
    client, fake_db = _connector_route_client(monkeypatch, brand_admin, agents)

    assert client.get("/agents/agent-1/connectors").status_code == 200
    assert client.get("/agents/agent-2/connectors").status_code == 403

    denied = client.put("/agents/agent-2/connectors", json=sample_context_connectors()[0])
    assert denied.status_code == 403
    assert fake_db.agents.documents[1]["configuration"].get("context_connectors") == []

    viewer_client, _ = _connector_route_client(monkeypatch, _test_user(UserRole.VIEWER, ["brand-1"]), agents)
    assert viewer_client.get("/agents/agent-1/connectors").status_code == 403

    operator_client, _ = _connector_route_client(monkeypatch, _test_user(UserRole.OPERATOR, ["brand-1"]), agents)
    assert operator_client.get("/agents/agent-1/connectors").status_code == 200
    assert operator_client.put("/agents/agent-1/connectors", json=sample_context_connectors()[0]).status_code == 403


def test_revoked_connector_cannot_be_reenabled_or_tested(monkeypatch):
    agent = {
        "id": "agent-1",
        "brand_id": "brand-1",
        "configuration": {
            "context_connectors": [
                {
                    **sample_context_connectors()[0],
                    "enabled": False,
                    "revoked": True,
                }
            ]
        },
    }
    client, _ = _connector_route_client(monkeypatch, _test_user(UserRole.BRAND_ADMIN, ["brand-1"]), [agent])

    assert client.post("/agents/agent-1/connectors/weather/toggle", json={"enabled": True}).status_code == 409
    assert client.post("/agents/agent-1/connectors/weather/test", json={"endpoint_id": "forecast"}).status_code == 409


def test_mcp_connector_tools_respect_allowed_tool_list():
    _require_context_connector_runtime_helpers()
    tools = ToolRegistryService().enabled_context_connector_tools(
        {
            "context_connectors": [
                {
                    "id": "vedika_mcp",
                    "type": "mcp",
                    "name": "Vedika MCP",
                    "enabled": True,
                    "endpoint": "https://mcp.example.com/mcp",
                    "allowed_tools": ["lalkitab_chart"],
                    "discovered_tools": [
                        {"name": "lalkitab_chart", "description": "Chart tool", "inputSchema": {}},
                        {"name": "lalkitab_remedies", "description": "Remedies tool", "inputSchema": {}},
                    ],
                }
            ]
        }
    )

    assert [tool.name for tool in tools] == ["lalkitab_chart"]


@pytest.mark.asyncio
async def test_mcp_connector_tool_blocks_private_runtime_endpoint():
    _require_context_connector_runtime_helpers()
    tools = ToolRegistryService().enabled_context_connector_tools(
        {
            "context_connectors": [
                {
                    "id": "local_mcp",
                    "type": "mcp",
                    "name": "Local MCP",
                    "enabled": True,
                    "endpoint": "http://127.0.0.1:9999/mcp",
                    "domain_allowlist": ["127.0.0.1"],
                    "allowed_tools": ["unsafe_tool"],
                    "discovered_tools": [{"name": "unsafe_tool", "description": "Unsafe", "inputSchema": {}}],
                }
            ]
        }
    )

    assert len(tools) == 1
    result = await tools[0].run()
    assert result.success is False
    assert result.metadata["blocked_reason"] == "local_urls_blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "blocked_reason"),
    [
        ("http://localhost:8080/internal", "local_urls_blocked"),
        ("http://127.0.0.1:8080/internal", "local_urls_blocked"),
        ("http://10.0.0.5/internal", "private_network_blocked"),
    ],
)
async def test_http_connector_blocks_localhost_and_private_network_urls(url, blocked_reason):
    tool = ContextConnectorTool(
        {
            "enabled": True,
            "name": "Unsafe API",
            "type": "http_api",
            "auth": {"type": "bearer", "token": "secret"},
        },
        {
            "id": "unsafe",
            "name": "Unsafe Endpoint",
            "method": "GET",
            "url_template": url,
            "enabled": True,
        },
    )

    result = await tool.run("fetch internal data")

    assert result.success is False
    assert blocked_reason in (result.error or "")
    assert result.metadata["blocked_reason"] == blocked_reason


@pytest.mark.asyncio
async def test_http_connector_blocks_hosts_outside_domain_allowlist():
    tool = ContextConnectorTool(
        {
            "enabled": True,
            "name": "Weather API",
            "type": "http_api",
            "domain_allowlist": ["api.example.com"],
        },
        {
            "id": "forecast",
            "name": "Forecast",
            "method": "GET",
            "url_template": "https://example.com/forecast",
            "enabled": True,
        },
    )

    result = await tool.run("fetch weather")

    assert result.success is False
    assert result.metadata["blocked_reason"] == "domain_not_allowlisted"


def test_manifest_export_includes_context_connectors_without_secrets():
    _require_context_connector_manifest_helpers()

    files = AgentManifestService().build_package_files(_agent_doc_with_context_connectors())
    joined = "\n".join(files.values())

    assert "context_connectors" in joined
    assert "Weather Context" in joined
    assert "connector-secret" not in joined
    assert "token_encrypted" not in joined
    assert "${WEATHER_TOKEN}" in files["knowledge/index.yaml"]


def test_manifest_export_migrates_legacy_api_data_source_without_secret():
    files = AgentManifestService().build_package_files(
        {
            **_agent_doc_with_context_connectors(),
            "configuration": {
                "data_source": "none",
                "api_data_source": {
                    "enabled": True,
                    "name": "Legacy API",
                    "url": "https://api.example.com/legacy",
                    "auth_header": "Authorization: Bearer raw-secret",
                    "usage": "Fetch legacy context.",
                },
            },
        }
    )
    knowledge = json.loads(files["knowledge/index.yaml"])
    joined = "\n".join(files.values())

    assert "raw-secret" not in joined
    assert "api_data_source" not in knowledge
    assert knowledge["context_connectors"][0]["id"] == "legacy_api_data_source"
    assert knowledge["context_connectors"][0]["auth"]["auth_header_placeholder"] == "${LEGACY_API_DATA_SOURCE_AUTH_HEADER}"


def test_manifest_import_migrates_legacy_api_data_source_to_context_connectors():
    _require_context_connector_manifest_helpers()
    service = AgentManifestService()
    package_files = service.build_package_files(_agent_doc_with_context_connectors())
    legacy_files = deepcopy(package_files)
    legacy_files["knowledge/index.yaml"] = json.dumps(
        {
            "data_source": "none",
            "api_data_source": {
                "enabled": True,
                "name": "Legacy Weather",
                "url": "https://api.example.com/legacy-weather",
                "usage": "Fetch approved weather context.",
                "auth_header": "${LEGACY_WEATHER_AUTH_HEADER}",
            },
        }
    )

    imported = service.build_import_document(
        legacy_files,
        brand_id="brand-2",
        brand_slug="brand-two",
    )

    connectors = imported["configuration"].get("context_connectors") or []
    assert connectors
    connector = connectors[0]
    assert connector["name"] == "Legacy Weather"
    assert connector["enabled"] is True
    assert "auth_header" not in connector
    assert "auth_header_encrypted" not in connector
    assert connector["auth"] == {
        "type": "raw_header",
        "auth_header_placeholder": "${LEGACY_WEATHER_AUTH_HEADER}",
    }
