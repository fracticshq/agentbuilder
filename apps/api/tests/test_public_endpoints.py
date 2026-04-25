from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.public import router


class FakeCursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, *_args, **_kwargs):
        return self

    async def to_list(self, length=None):
        if length is None:
            return list(self.documents)
        return list(self.documents)[:length]


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])

    async def find_one(self, query=None):
        query = query or {}
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return dict(document)
        return None

    def find(self, query=None):
        query = query or {}
        return FakeCursor(
            dict(document)
            for document in self.documents
            if all(document.get(key) == value for key, value in query.items())
        )


class FakeSystemDb:
    def __init__(self):
        self.agents = FakeCollection(
            [
                {
                    "id": "agent-active",
                    "brand_id": "brand-1",
                    "name": "Essco Assistant",
                    "description": "Handles shower and faucet queries",
                    "configuration": {"features": {"websockets": True}},
                    "status": "active",
                },
                {
                    "id": "agent-draft",
                    "brand_id": "brand-1",
                    "name": "Draft Agent",
                    "description": "Should stay hidden",
                    "configuration": {},
                    "status": "draft",
                },
            ]
        )
        self.brands = FakeCollection(
            [
                {
                    "id": "brand-1",
                    "name": "Essco Bathware",
                    "slug": "essco-bathware",
                    "colors": {"primary": "#f43f5e"},
                    "logo_url": "https://example.com/logo.png",
                    "website": "https://example.com",
                    "updated_at": datetime(2026, 4, 23, tzinfo=timezone.utc),
                }
            ]
        )


def test_public_widget_bootstrap_endpoints_are_accessible(monkeypatch):
    from app.api.v1.endpoints import public as public_module

    public_module.connection_manager.system_db = FakeSystemDb()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/public")
    client = TestClient(app)

    list_response = client.get("/api/v1/public/agents")
    assert list_response.status_code == 200
    assert list_response.json() == [
        {
            "id": "agent-active",
            "brand_id": "brand-1",
            "name": "Essco Assistant",
            "description": "Handles shower and faucet queries",
            "configuration": {"features": {"websockets": True}},
            "status": "active",
        }
    ]

    agent_response = client.get("/api/v1/public/agents/agent-active")
    assert agent_response.status_code == 200
    assert agent_response.json()["name"] == "Essco Assistant"

    brand_response = client.get("/api/v1/public/brands/brand-1")
    assert brand_response.status_code == 200
    assert brand_response.json()["slug"] == "essco-bathware"
