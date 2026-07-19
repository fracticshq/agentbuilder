from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.activity import router
from app.auth.widget_session import issue_widget_session
from app.dependencies import get_activity_service


@pytest.fixture(autouse=True)
def _allow_active_widget_scope(monkeypatch):
    from app.api.v1.endpoints import activity as activity_module

    async def allow_scope(**_kwargs):
        return None

    monkeypatch.setattr(
        activity_module.conversation_scope_store,
        "require_active_widget_scope",
        allow_scope,
    )


class _ActivityService:
    def __init__(self):
        self.requests = []

    async def track(self, request):
        self.requests.append(request)
        return type("Event", (), {"id": "event-1", "timestamp": "2026-07-18T00:00:00Z"})()


def _client(service: _ActivityService) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/activity")
    app.dependency_overrides[get_activity_service] = lambda: service
    return TestClient(app)


def _event_body(**overrides):
    body = {
        "event_type": "message_sent",
        "actor_type": "user",
        "actor_id": "attacker-selected-id",
        "agent_id": "agent-1",
        "conversation_id": "attacker-selected-conversation",
    }
    body.update(overrides)
    return body


def test_widget_activity_requires_signed_session():
    response = _client(_ActivityService()).post("/api/v1/activity/events", json=_event_body())

    assert response.status_code == 401


def test_widget_activity_derives_identity_from_signed_session():
    service = _ActivityService()
    token, session = issue_widget_session("agent-1")

    response = _client(service).post(
        "/api/v1/activity/events",
        json=_event_body(),
        headers={"X-Widget-Session": token},
    )

    assert response.status_code == 201
    assert len(service.requests) == 1
    stored = service.requests[0]
    assert stored.agent_id == session.agent_id
    assert stored.conversation_id == session.conversation_id
    assert stored.actor_id == session.user_id


def test_widget_activity_rejects_token_for_another_agent():
    service = _ActivityService()
    token, _ = issue_widget_session("agent-2")

    response = _client(service).post(
        "/api/v1/activity/events",
        json=_event_body(agent_id="agent-1"),
        headers={"X-Widget-Session": token},
    )

    assert response.status_code == 401
