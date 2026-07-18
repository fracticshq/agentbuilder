"""Regression coverage for P0 tenant-bound control-plane routes."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import activity as activity_module
from app.api.v1.endpoints import ingestion as ingestion_module
from app.api.v1.endpoints import knowledge as knowledge_module
from app.auth.dependencies import require_dashboard_access
from app.auth.models import User, UserRole
from app.dependencies import get_activity_service, get_ingestion_service, get_knowledge_service


class _Agents:
    def __init__(self, agent: dict):
        self.agent = agent

    async def find_one(self, query, *args, **kwargs):
        return self.agent if query.get("id") == self.agent["id"] else None


class _SystemDb:
    def __init__(self, agent: dict):
        self.agents = _Agents(agent)


def _brand_admin() -> User:
    return User(
        _id="brand-admin",
        email="admin@brand-a.example",
        username="brand-a-admin",
        password_hash="hash",
        role=UserRole.BRAND_ADMIN,
        brands=["brand-a"],
    )


def test_knowledge_route_hides_another_tenant_brand():
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix="/api/v1/knowledge")
    app.dependency_overrides[require_dashboard_access] = _brand_admin
    app.dependency_overrides[get_knowledge_service] = lambda: AsyncMock()

    response = TestClient(app).get("/api/v1/knowledge/tree", params={"brand_id": "brand-b"})

    assert response.status_code == 404


def test_activity_read_hides_agent_owned_by_another_tenant(monkeypatch):
    app = FastAPI()
    app.include_router(activity_module.router, prefix="/api/v1/activity")
    app.dependency_overrides[require_dashboard_access] = _brand_admin
    app.dependency_overrides[get_activity_service] = lambda: AsyncMock()
    monkeypatch.setattr(
        activity_module.connection_manager,
        "get_system_db",
        lambda: _SystemDb({"id": "agent-b", "brand_id": "brand-b"}),
    )

    response = TestClient(app).get(
        "/api/v1/activity/analytics",
        params={"agent_id": "agent-b"},
    )

    assert response.status_code == 404


def test_manual_ingestion_cannot_target_another_tenant_agent(monkeypatch):
    app = FastAPI()
    app.include_router(ingestion_module.router, prefix="/api/v1/ingest")
    app.dependency_overrides[require_dashboard_access] = _brand_admin
    app.dependency_overrides[get_ingestion_service] = lambda: AsyncMock()
    monkeypatch.setattr(
        ingestion_module.connection_manager,
        "get_system_db",
        lambda: _SystemDb({"id": "agent-b", "brand_id": "brand-b"}),
    )

    response = TestClient(app).post(
        "/api/v1/ingest/chunks",
        json={"text": "tenant-isolation check", "agent_id": "agent-b"},
    )

    assert response.status_code == 404
