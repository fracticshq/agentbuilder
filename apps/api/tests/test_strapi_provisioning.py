from types import SimpleNamespace

import pytest

from app.api.v1.admin import agents as agents_module
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


class FakeRuntimeSettingsService:
    def __init__(self, config):
        self._config = config

    async def get_strapi_runtime_config(self):
        return self._config


@pytest.mark.asyncio
async def test_runtime_settings_service_resolves_strapi_values():
    service = RuntimeSettingsService(build_settings())
    config = await service.get_strapi_runtime_config()

    assert config == {
        "base_url": "http://localhost:1337",
        "api_token": "token-123",
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
