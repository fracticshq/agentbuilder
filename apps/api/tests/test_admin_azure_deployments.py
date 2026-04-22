from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin.llm import router
from app.dependencies import get_settings
from app.services.azure_openai_deployment_service import (
    AzureDeploymentAuthError,
    AzureDeploymentRequestError,
    AzureOpenAIDeploymentService,
)


def build_settings(**overrides):
    base = {
        "ADMIN_API_KEY": "test-admin-key",
        "ALLOW_ADMIN_KEY_BYPASS": False,
        "is_production": False,
        "AZURE_SUBSCRIPTION_ID": "sub-123",
        "AZURE_RESOURCE_GROUP": "rg-test",
        "AZURE_OPENAI_ACCOUNT_NAME": "aoai-test",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-5.4-mini",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def build_test_client(settings):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin/llm")
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@pytest.mark.asyncio
async def test_service_filters_non_succeeded_deployments(monkeypatch):
    settings = build_settings()
    service = AzureOpenAIDeploymentService(settings)

    async def fake_payload():
        return {
            "value": [
                {
                    "name": "zzz-deployment",
                    "sku": {"name": "Standard"},
                    "properties": {
                        "provisioningState": "Creating",
                        "model": {"name": "gpt-4.1", "version": "2025-04-14"},
                    },
                },
                {
                    "name": "gpt-5.4-mini",
                    "sku": {"name": "Standard"},
                    "properties": {
                        "provisioningState": "Succeeded",
                        "model": {"name": "gpt-5.4-mini", "version": "2025-04-14"},
                    },
                },
                {
                    "name": "assistants-mini",
                    "sku": {"name": "GlobalStandard"},
                    "properties": {
                        "provisioningState": "Succeeded",
                        "model": {"name": "gpt-4.1-mini", "version": "2025-04-14"},
                    },
                },
            ]
        }

    monkeypatch.setattr(service, "_fetch_deployments_payload", fake_payload)

    response = await service.list_deployments()

    assert response["provider"] == "azure_openai"
    assert response["default_deployment"] == "gpt-5.4-mini"
    assert [item["deployment_name"] for item in response["deployments"]] == [
        "assistants-mini",
        "gpt-5.4-mini",
    ]
    assert response["deployments"][0]["model_name"] == "gpt-4.1-mini"


def test_route_rejects_missing_admin_key():
    client = build_test_client(build_settings())

    response = client.get("/api/v1/admin/llm/azure/deployments")

    assert response.status_code == 401
    assert response.json()["detail"] == "X-Admin-Key header required"


def test_route_returns_503_when_arm_config_missing():
    client = build_test_client(build_settings(AZURE_SUBSCRIPTION_ID=""))

    response = client.get(
        "/api/v1/admin/llm/azure/deployments",
        headers={"X-Admin-Key": "test-admin-key"},
    )

    assert response.status_code == 503
    assert "AZURE_SUBSCRIPTION_ID" in response.json()["detail"]


def test_route_returns_503_for_auth_failures(monkeypatch):
    client = build_test_client(build_settings())

    async def fake_list_deployments(self):
        raise AzureDeploymentAuthError("Failed to acquire Azure management token.")

    monkeypatch.setattr(AzureOpenAIDeploymentService, "list_deployments", fake_list_deployments)

    response = client.get(
        "/api/v1/admin/llm/azure/deployments",
        headers={"X-Admin-Key": "test-admin-key"},
    )

    assert response.status_code == 503
    assert "Failed to acquire Azure management token" in response.json()["detail"]


def test_route_returns_502_for_arm_request_failures(monkeypatch):
    client = build_test_client(build_settings())

    async def fake_list_deployments(self):
        raise AzureDeploymentRequestError("Azure ARM request failed with status 403.")

    monkeypatch.setattr(AzureOpenAIDeploymentService, "list_deployments", fake_list_deployments)

    response = client.get(
        "/api/v1/admin/llm/azure/deployments",
        headers={"X-Admin-Key": "test-admin-key"},
    )

    assert response.status_code == 502
    assert "Azure ARM request failed" in response.json()["detail"]
