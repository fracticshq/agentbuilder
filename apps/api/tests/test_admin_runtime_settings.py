from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin.settings import router
from app.auth.dependencies import get_db, require_dashboard_access
from app.dependencies import get_runtime_settings_service, get_settings
from app.services.runtime_settings_service import (
    RuntimeSettingsService,
    RuntimeSettingsValidationError,
)


def build_settings(**overrides):
    base = {
        "ADMIN_API_KEY": "test-admin-key",
        "ALLOW_ADMIN_KEY_BYPASS": False,
        "is_production": False,
        "SECRET_KEY": "test-secret-key",
        "SETTINGS_ENCRYPTION_KEY": "test-settings-encryption-key",
        "DEFAULT_LLM_PROVIDER": "azure_openai",
        "AZURE_OPENAI_API_KEY": "",
        "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
        "AZURE_OPENAI_API_VERSION": "2025-04-01-preview",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-5.4-mini",
        "AZURE_OPENAI_MODEL": "gpt-5.4-mini",
        "AZURE_OPENAI_ACCOUNT_NAME": "aoai-account",
        "AZURE_SUBSCRIPTION_ID": "sub-123",
        "AZURE_RESOURCE_GROUP": "rg-main",
        "VOYAGE_API_KEY": "",
        "VOYAGE_MODEL": "voyage-3-large",
        "VOYAGE_RERANK_MODEL": "rerank-2.5",
        "OPENAI_API_KEY": "",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "OPENAI_MODEL": "gpt-4o-mini",
        "QWEN_API_KEY": "",
        "QWEN_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "QWEN_MODEL": "qwen-max",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeRuntimeSettingsService:
    async def list_settings_for_admin(self):
        return {
            "sections": [
                {
                    "id": "azure_openai",
                    "title": "Azure OpenAI",
                    "description": "Test section",
                    "supports_connection_test": True,
                    "fields": [
                        {
                            "key": "azure_openai.api_key",
                            "label": "Azure OpenAI API key",
                            "description": "Masked in UI",
                            "input_type": "password",
                            "secret": True,
                            "required": False,
                            "configured": True,
                            "source": "stored",
                            "masked_value": "••••1234",
                            "options": [],
                        }
                    ],
                }
            ]
        }

    async def update_settings(self, updates):
        return {
            "updated": [
                {"key": key, "action": "updated", "section": "azure_openai"}
                for key in updates
            ],
            "settings": await self.list_settings_for_admin(),
        }

    async def test_connections(self, *, sections=None, overrides=None):
        return {
            "status": "healthy",
            "results": [
                {
                    "section": (sections or ["azure_openai"])[0],
                    "status": "healthy",
                    "detail": "Connected successfully.",
                }
            ],
        }


def build_test_client(settings, runtime_settings_service):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin/settings")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_runtime_settings_service] = lambda: runtime_settings_service
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


@pytest.mark.asyncio
async def test_list_settings_masks_secret_values():
    settings = build_settings(AZURE_OPENAI_API_KEY="env-secret")
    service = RuntimeSettingsService(settings)

    encrypted_secret = service._encrypt("stored-secret")

    async def fake_load_stored_documents():
        return {
            "azure_openai.api_key": {
                "key": "azure_openai.api_key",
                "value_encrypted": encrypted_secret,
                "updated_at": "2026-04-23T00:00:00+00:00",
            }
        }

    service._load_stored_documents = fake_load_stored_documents

    response = await service.list_settings_for_admin()
    azure_section = next(section for section in response["sections"] if section["id"] == "azure_openai")
    api_key_field = next(field for field in azure_section["fields"] if field["key"] == "azure_openai.api_key")

    assert api_key_field["secret"] is True
    assert api_key_field["masked_value"].endswith("cret")
    assert "value" not in api_key_field
    assert api_key_field["source"] == "stored"


@pytest.mark.asyncio
async def test_update_settings_rejects_unknown_keys():
    service = RuntimeSettingsService(build_settings())

    with pytest.raises(RuntimeSettingsValidationError):
        await service.update_settings({"unknown.setting": "value"})


def test_route_rejects_missing_dashboard_auth():
    client = build_test_client(build_settings(), FakeRuntimeSettingsService())

    response = client.get("/api/v1/admin/settings/runtime")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_route_returns_runtime_settings_for_authenticated_dashboard_user():
    client = build_test_client(build_settings(), FakeRuntimeSettingsService())
    client.app.dependency_overrides[require_dashboard_access] = lambda: None

    response = client.get("/api/v1/admin/settings/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sections"][0]["fields"][0]["masked_value"] == "••••1234"


def test_route_updates_runtime_settings():
    client = build_test_client(build_settings(), FakeRuntimeSettingsService())
    client.app.dependency_overrides[require_dashboard_access] = lambda: None

    response = client.put(
        "/api/v1/admin/settings/runtime",
        json={"updates": {"azure_openai.endpoint": "https://example.openai.azure.com/"}},
    )

    assert response.status_code == 200
    assert response.json()["updated"][0]["key"] == "azure_openai.endpoint"


def test_route_tests_runtime_settings_connections():
    client = build_test_client(build_settings(), FakeRuntimeSettingsService())
    client.app.dependency_overrides[require_dashboard_access] = lambda: None

    response = client.post(
        "/api/v1/admin/settings/runtime/test",
        json={"sections": ["azure_openai"]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["results"][0]["section"] == "azure_openai"
