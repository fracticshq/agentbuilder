from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from zipfile import ZipFile
import io

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin.agent_manifests import router as agent_manifests_router
from app.auth.dependencies import require_dashboard_access
from app.services.agent_manifest_service import AgentManifestService, REQUIRED_PACKAGE_PATHS


class FakeCursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]

    async def to_list(self, length=None):
        return self.documents[:length] if length else self.documents


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = [deepcopy(document) for document in (documents or [])]

    def _matches(self, document, query):
        return all(document.get(key) == value for key, value in (query or {}).items())

    async def find_one(self, query):
        for document in self.documents:
            if self._matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query=None):
        return FakeCursor(document for document in self.documents if self._matches(document, query or {}))

    async def insert_one(self, document):
        self.documents.append(deepcopy(document))
        return SimpleNamespace(inserted_id=document.get("id"))


class FakeSystemDb:
    def __init__(self, agents=None, brands=None):
        self.agents = FakeCollection(agents)
        self.brands = FakeCollection(brands)

    def __getitem__(self, name):
        return getattr(self, name)


def build_agent_doc():
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
            "llm": {"provider": "azure_openai", "model": "gpt-4.1", "temperature": 0.2},
            "prompt_layers": {
                "soul": "Be helpful.",
                "rules": {"grounding": "Use approved sources."},
                "data_source_policy": {"default_sources": ["knowledge_base"]},
            },
            "rag": {"enabled": True, "retrieval": {"top_k": 4}},
            "data_source": "rag",
            "shopify": {
                "enabled": True,
                "shop_url": "example.myshopify.com",
                "access_token_encrypted": "encrypted-shopify-token-blob",
            },
            "tools": {
                "http_webhook": {
                    "enabled": True,
                    "url": "https://example.invalid/hook",
                    "secret_encrypted": "encrypted-webhook-secret-blob",
                },
                "selected_tool_ids": ["http_webhook"],
            },
            "skills": [
                {"skill_id": "knowledge_qa", "enabled": True, "config": {"required_citations": True}}
            ],
        },
    }


def test_agent_manifest_export_contains_required_files_and_strips_secrets():
    files = AgentManifestService().build_package_files(build_agent_doc())

    assert tuple(files.keys()) == REQUIRED_PACKAGE_PATHS
    joined = "\n".join(files.values())
    assert "encrypted-shopify-token-blob" not in joined
    assert "encrypted-webhook-secret-blob" not in joined
    assert "_encrypted" not in joined
    assert "${SHOPIFY_ACCESS_TOKEN}" in files["tools/index.yaml"]
    assert "${HTTP_WEBHOOK_SECRET}" in files["tools/index.yaml"]


def test_agent_manifest_round_trip_import_keeps_draft_safe_payload():
    service = AgentManifestService()
    package_files = service.parse_zip(service.build_zip(build_agent_doc()))
    imported = service.build_import_document(package_files, brand_id="target-brand", brand_slug="target")

    assert imported["status"] == "draft"
    assert imported["brand_id"] == "target-brand"
    assert imported["name"] == "Portable Agent"
    assert imported["configuration"]["prompt_layers"]["soul"] == "Be helpful."
    shopify = imported["configuration"]["tools"]["shopify"]
    assert "access_token" not in shopify
    assert "access_token_encrypted" not in shopify
    assert shopify["access_token_placeholder"] == "${SHOPIFY_ACCESS_TOKEN}"


def test_agent_manifest_admin_routes_export_and_import(monkeypatch):
    from app.api.v1.admin import agent_manifests as route_module

    fake_db = FakeSystemDb(
        agents=[build_agent_doc()],
        brands=[{"id": "brand-2", "slug": "brand-two"}],
    )
    monkeypatch.setattr(route_module.connection_manager, "system_db", fake_db)
    monkeypatch.setattr(route_module.connection_manager, "get_system_db", lambda: fake_db)

    app = FastAPI()
    app.include_router(agent_manifests_router, prefix="/agents")
    app.dependency_overrides[require_dashboard_access] = lambda: None
    client = TestClient(app)

    export_response = client.get("/agents/agent-1/export")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(export_response.content)) as archive:
        assert "agent.yaml" in archive.namelist()

    import_response = client.post(
        "/agents/import",
        data={"brand_id": "brand-2"},
        files={"file": ("agent.zip", export_response.content, "application/zip")},
    )
    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload["agent"]["status"] == "draft"
    assert payload["agent"]["brand_id"] == "brand-2"
    assert fake_db.agents.documents[-1]["brand_slug"] == "brand-two"
