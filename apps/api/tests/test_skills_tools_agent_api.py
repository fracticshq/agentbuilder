from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin.skills import router as skills_router
from app.api.v1.admin.tools import router as tools_router
from app.api.v1.admin.agent_api_keys import router as agent_api_keys_router
from app.auth.dependencies import require_dashboard_access
from app.auth.models import User, UserRole
from app.services.agent_api_keys import (
    AgentApiKeyService,
    DEFAULT_AGENT_API_SCOPES,
    extract_agent_api_key_id,
    hash_agent_api_key,
)
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.skill_registry import BuiltInSkillRegistry
from app.services.tool_config_secrets import (
    decrypt_full_agent_configuration_for_runtime,
    expose_full_agent_for_admin,
    protect_full_agent_configuration_secrets,
)
from app.services.tool_registry import ToolRegistryService


class FakeUpdateResult:
    def __init__(self, matched_count=0):
        self.matched_count = matched_count


class FakeCursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]

    def sort(self, *_args, **_kwargs):
        return self

    async def to_list(self, length=None):
        if length is None:
            return list(self.documents)
        return list(self.documents)[:length]


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = [deepcopy(document) for document in (documents or [])]

    def _matches(self, document, query):
        for key, value in (query or {}).items():
            if isinstance(value, dict) and "$in" in value:
                if document.get(key) not in value["$in"]:
                    return False
            elif document.get(key) != value:
                return False
        return True

    async def insert_one(self, document):
        self.documents.append(deepcopy(document))

    async def find_one(self, query):
        for document in self.documents:
            if self._matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query=None):
        return FakeCursor(document for document in self.documents if self._matches(document, query or {}))

    async def update_one(self, query, update):
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                for dotted_key, increment in update.get("$inc", {}).items():
                    parts = dotted_key.split(".")
                    target = document
                    for part in parts[:-1]:
                        target = target.setdefault(part, {})
                    target[parts[-1]] = target.get(parts[-1], 0) + increment
                self.documents[index] = document
                return FakeUpdateResult(matched_count=1)
        return FakeUpdateResult()


class FakeSystemDb:
    def __init__(self, *, agents=None, api_keys=None):
        self.agents = FakeCollection(agents)
        self.agent_api_keys = FakeCollection(api_keys)

    def __getitem__(self, name):
        return getattr(self, name)


def runtime_settings_service():
    return RuntimeSettingsService(
        SimpleNamespace(
            SETTINGS_ENCRYPTION_KEY="test-settings-encryption-key",
            PII_ENCRYPTION_KEY="",
            SECRET_KEY="test-secret-key",
        )
    )


def test_built_in_skill_registry_contains_plan_ids():
    skill_ids = {skill["id"] for skill in BuiltInSkillRegistry().list_skills()}

    assert skill_ids == {
        "knowledge_qa",
        "api_data_lookup",
        "url_context_boost",
        "product_recommendation",
        "dealer_locator",
        "lead_capture",
        "conversation_summary",
        "human_handoff",
    }


def test_tool_registry_contains_plan_ids_and_secret_schema():
    tools = {tool["id"]: tool for tool in ToolRegistryService().list_tools()}

    assert set(tools) == {
        "shopify",
        "http_webhook",
        "hubspot",
        "salesforce",
        "zendesk",
        "slack",
        "google_sheets",
        "airtable",
        "notion",
        "zapier_webhook",
        "n8n_webhook",
    }
    assert "access_token" in tools["hubspot"]["secret_fields"]
    assert tools["http_webhook"]["provider"] == "http"


def test_admin_registry_routes_return_authenticated_shapes():
    app = FastAPI()
    app.include_router(skills_router, prefix="/skills")
    app.include_router(tools_router, prefix="/tools")
    app.dependency_overrides[require_dashboard_access] = lambda: None
    client = TestClient(app)

    assert client.get("/skills/").json()["skills"][0]["id"]
    assert "enabled_skills" in client.get("/skills/agent-config-shape").json()
    assert "tools" in client.get("/tools/agent-config-shape").json()


def test_tool_config_secrets_are_encrypted_masked_and_decryptable():
    service = runtime_settings_service()
    protected = protect_full_agent_configuration_secrets(
        {
            "tools": {
                "hubspot": {
                    "enabled": True,
                    "access_token": "pat-secret",
                    "portal_id": "123",
                }
            }
        },
        runtime_settings_service=service,
    )

    hubspot = protected["tools"]["hubspot"]
    assert "access_token" not in hubspot
    assert hubspot["access_token_encrypted"] != "pat-secret"

    admin_agent = expose_full_agent_for_admin({"configuration": protected}, service)
    assert admin_agent["configuration"]["tools"]["hubspot"]["access_token_configured"] is True
    assert "access_token_encrypted" not in admin_agent["configuration"]["tools"]["hubspot"]

    runtime = decrypt_full_agent_configuration_for_runtime(protected, service)
    assert runtime["tools"]["hubspot"]["access_token"] == "pat-secret"


def test_api_data_source_secret_is_encrypted_masked_preserved_and_decryptable():
    service = runtime_settings_service()
    protected = protect_full_agent_configuration_secrets(
        {
            "api_data_source": {
                "enabled": True,
                "name": "Astrology API",
                "url": "https://api.example.com/lal-kitab",
                "auth_header": "Authorization: Bearer secret-token",
                "usage": "Use for LalKitab chart context.",
            }
        },
        runtime_settings_service=service,
    )

    assert "api_data_source" not in protected
    connector = next(item for item in protected["context_connectors"] if item["id"] == "legacy_api_data_source")
    assert connector["name"] == "Astrology API"
    assert connector["endpoints"][0]["url_template"] == "https://api.example.com/lal-kitab"
    assert "auth_header" not in connector["auth"]
    assert connector["auth"]["auth_header_encrypted"] != "Authorization: Bearer secret-token"

    admin_agent = expose_full_agent_for_admin({"configuration": protected}, service)
    admin_connector = next(
        item
        for item in admin_agent["configuration"]["context_connectors"]
        if item["id"] == "legacy_api_data_source"
    )
    assert admin_connector["auth"]["auth_header_configured"] is True
    assert "auth_header" not in admin_connector["auth"]
    assert "auth_header_encrypted" not in admin_connector["auth"]

    updated = protect_full_agent_configuration_secrets(
        {
            "api_data_source": {
                "enabled": True,
                "name": "Astrology API",
                "url": "https://api.example.com/lal-kitab",
                "auth_header": "",
                "usage": "Use for LalKitab chart context.",
            }
        },
        existing_config=protected,
        runtime_settings_service=service,
    )
    runtime = decrypt_full_agent_configuration_for_runtime(updated, service)
    runtime_connector = next(item for item in runtime["context_connectors"] if item["id"] == "legacy_api_data_source")
    assert runtime_connector["auth"]["auth_header"] == "Authorization: Bearer secret-token"


@pytest.mark.asyncio
async def test_agent_api_key_authenticates_and_enforces_scopes(monkeypatch):
    from app.services import agent_api_keys as keys_module

    fake_db = FakeSystemDb()
    monkeypatch.setattr(keys_module.connection_manager, "get_system_db", lambda: fake_db)

    service = AgentApiKeyService()
    created = await service.create_key(name="Public API", scopes=DEFAULT_AGENT_API_SCOPES, agent_id="agent-1")
    api_key = created["api_key"]
    key_id = extract_agent_api_key_id(api_key)

    context = await service.authenticate(api_key, required_scope="messages:write")

    assert context.key_id == key_id
    assert context.agent_id == "agent-1"
    assert fake_db.agent_api_keys.documents[0]["usage"]["total_requests"] == 1

    with pytest.raises(Exception) as exc_info:
        await service.authenticate(api_key, required_scope="admin:write")

    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_agent_api_key_accepts_legacy_ui_scope_aliases(monkeypatch):
    from app.services import agent_api_keys as keys_module

    legacy_key = "ab_agent_v1_deadbeef_secret"
    fake_db = FakeSystemDb(api_keys=[{
        "id": "key-doc-1",
        "key_id": "ab_agent_v1_deadbeef",
        "name": "Legacy UI key",
        "key_hash": hash_agent_api_key(legacy_key),
        "scopes": ["agent:read", "message:create", "message:stream", "session:read"],
        "agent_id": "agent-1",
        "brand_id": "brand-1",
        "is_active": True,
        "usage": {"total_requests": 0},
    }])
    monkeypatch.setattr(keys_module.connection_manager, "get_system_db", lambda: fake_db)

    service = AgentApiKeyService()

    assert (await service.authenticate(legacy_key, required_scope="agents:read")).agent_id == "agent-1"
    assert (await service.authenticate(legacy_key, required_scope="messages:write")).agent_id == "agent-1"
    assert (await service.authenticate(legacy_key, required_scope="messages:stream")).agent_id == "agent-1"
    assert (await service.authenticate(legacy_key, required_scope="sessions:read")).agent_id == "agent-1"


def test_admin_agent_api_key_routes_enforce_brand_scope(monkeypatch):
    from app.api.v1.admin import agent_api_keys as route_module
    from app.services import agent_api_keys as keys_module

    fake_db = FakeSystemDb(
        agents=[
            {"id": "agent-1", "brand_id": "brand-1"},
            {"id": "agent-2", "brand_id": "brand-2"},
        ],
        api_keys=[
            {
                "id": "doc-1",
                "key_id": "ab_agent_v1_brand1",
                "name": "Brand 1",
                "key_hash": "hash",
                "scopes": DEFAULT_AGENT_API_SCOPES,
                "agent_id": "agent-1",
                "brand_id": "brand-1",
                "is_active": True,
            },
            {
                "id": "doc-2",
                "key_id": "ab_agent_v1_brand2",
                "name": "Brand 2",
                "key_hash": "hash",
                "scopes": DEFAULT_AGENT_API_SCOPES,
                "agent_id": "agent-2",
                "brand_id": "brand-2",
                "is_active": True,
            },
        ],
    )
    monkeypatch.setattr(keys_module.connection_manager, "get_system_db", lambda: fake_db)
    monkeypatch.setattr(route_module.connection_manager, "get_system_db", lambda: fake_db)

    brand_admin = User(
        _id="user-1",
        email="brand@example.com",
        username="brand",
        password_hash="hash",
        role=UserRole.BRAND_ADMIN,
        brands=["brand-1"],
    )
    app = FastAPI()
    app.include_router(agent_api_keys_router, prefix="/agent-api")
    app.dependency_overrides[require_dashboard_access] = lambda: brand_admin
    client = TestClient(app)

    response = client.get("/agent-api/keys")
    assert response.status_code == 200
    assert [key["key_id"] for key in response.json()["keys"]] == ["ab_agent_v1_brand1"]

    denied = client.post("/agent-api/keys", json={
        "name": "Denied",
        "agent_id": "agent-2",
        "scopes": DEFAULT_AGENT_API_SCOPES,
    })
    assert denied.status_code == 403

    created = client.post("/agent-api/keys", json={
        "name": "Allowed",
        "agent_id": "agent-1",
        "scopes": DEFAULT_AGENT_API_SCOPES,
    })
    assert created.status_code == 200
    assert created.json()["key"]["brand_id"] == "brand-1"


def test_console_roles_are_real_backend_user_roles():
    for role in [UserRole.ADMIN, UserRole.BRAND_ADMIN, UserRole.OPERATOR]:
        user = User(
            _id=f"user-{role.value}",
            email=f"{role.value}@example.com",
            username=role.value,
            password_hash="hash",
            role=role,
            brands=["brand-1"],
        )
        assert user.role == role

    viewer = User(
        _id="viewer-1",
        email="viewer@example.com",
        username="viewer",
        password_hash="hash",
        role=UserRole.VIEWER,
        brands=["brand-1"],
    )
    assert viewer.role == UserRole.VIEWER
