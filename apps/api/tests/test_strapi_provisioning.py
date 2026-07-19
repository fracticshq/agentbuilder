from types import SimpleNamespace

import pytest

from app.api.v1.admin import agents as agents_module
from app.services import runtime_settings_service as runtime_settings_module
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.strapi_provisioning_service import StrapiProvisioningService


def build_settings(**overrides):
    base = {
        "SECRET_KEY": "test-secret-key",
        "SETTINGS_ENCRYPTION_KEY": "test-settings-encryption-key",
        "PII_ENCRYPTION_KEY": "pii-seed",
        "STRAPI_URL": "http://localhost:1337",
        "STRAPI_API_TOKEN": "token-123",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class ProdSettings(SimpleNamespace):
    @property
    def is_production(self):
        return self.ENVIRONMENT == "production"


class FakeRuntimeSettingsService:
    def __init__(self, config):
        self._config = config

    async def get_strapi_runtime_config(self):
        return self._config


@pytest.mark.asyncio
async def test_runtime_settings_service_resolves_strapi_values(monkeypatch):
    # This test covers the host/local configuration contract. The container
    # rewrite has different intentional behavior and must not leak host Docker
    # state into a deterministic unit assertion.
    monkeypatch.setattr(runtime_settings_module.Path, "exists", lambda _path: False)
    service = RuntimeSettingsService(build_settings())
    config = await service.get_strapi_runtime_config()

    assert config == {
        "base_url": "http://localhost:1337",
        "api_token": "token-123",
    }


@pytest.mark.asyncio
async def test_production_strapi_config_uses_environment_not_stored_settings(monkeypatch):
    settings = ProdSettings(
        SECRET_KEY="test-secret-key",
        SETTINGS_ENCRYPTION_KEY="test-settings-encryption-key",
        PII_ENCRYPTION_KEY="pii-seed",
        ENVIRONMENT="production",
        STRAPI_URL="https://strapi.example.com",
        STRAPI_API_TOKEN="env-token",
    )
    service = RuntimeSettingsService(settings)

    async def fail_if_loaded():
        raise AssertionError("stored runtime settings should not be loaded in production")

    monkeypatch.setattr(service, "_load_stored_documents", fail_if_loaded)

    config = await service.get_strapi_runtime_config()

    assert config == {
        "base_url": "https://strapi.example.com",
        "api_token": "env-token",
    }


@pytest.mark.asyncio
async def test_best_effort_provisioning_returns_false_when_disabled():
    service = StrapiProvisioningService("", "")
    result = await service.provision_agent_dashboard_best_effort(
        {"slug": "essco-bathware", "name": "Essco"},
        {"id": "agent-1", "name": "Essco", "status": "active"},
    )

    assert result is False


@pytest.mark.asyncio
async def test_best_effort_sync_swallows_provisioning_errors(monkeypatch):
    class FailingProvisioningService:
        def __init__(self, base_url, api_token):
            self.base_url = base_url
            self.api_token = api_token

        async def provision_agent_dashboard_best_effort(self, brand_doc, agent_doc):
            raise RuntimeError("strapi unavailable")

    monkeypatch.setattr(agents_module, "StrapiProvisioningService", FailingProvisioningService)

    await agents_module.sync_agent_to_strapi_best_effort(
        FakeRuntimeSettingsService({"base_url": "http://localhost:1337", "api_token": "abc"}),
        {"id": "brand-1", "slug": "essco-bathware", "name": "Essco"},
        {"id": "agent-1", "brand_id": "brand-1", "status": "active"},
    )


@pytest.mark.parametrize(
    ("existing_status", "updated_status", "expected"),
    [
        (None, "active", True),
        (None, "draft", False),
        ("draft", "active", True),
        ("active", "active", True),
        ("active", "inactive", True),
        ("inactive", "inactive", False),
    ],
)
def test_should_sync_agent_dashboard(existing_status, updated_status, expected):
    existing = {"status": existing_status} if existing_status is not None else None
    updated = {"status": updated_status}

    assert agents_module.should_sync_agent_dashboard(existing, updated) is expected
