"""Public privacy lifecycle contracts stay tenant-bound and non-cacheable."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.widget_session import issue_widget_session
from app.services.conversation_scope_store import ConversationScope


class _PrivacyService:
    deletion_status = "pending"

    async def export_subject(self, **kwargs):
        return {
            "schema_version": "v1",
            "generated_at": datetime.now(timezone.utc),
            "subject": {"id": kwargs["subject_id"], "conversation_ids": ["conv_1"]},
            "data": {},
            "external_processors": [],
        }

    async def delete_subject(self, **kwargs):
        return {
            "id": "privacy_1",
            "status": self.deletion_status,
            "completed_at": datetime.now(timezone.utc),
            "deleted": {},
            "verified": {},
            "external_processors": [{"name": "strapi", "status": "pending_contract"}],
        }

    async def delete_long_term_memory(self, **_kwargs):
        return {"deleted": 3, "verified": True}


def _client(monkeypatch, *, deletion_status="pending"):
    from app.api.v1.endpoints import messages as messages_module

    session_token, session = issue_widget_session("agent-1")

    async def require_scope(*, conversation_id, user_id, agent_id):
        assert conversation_id == session.conversation_id
        assert user_id == session.user_id
        assert agent_id == session.agent_id
        return ConversationScope(
            conversation_id=session.conversation_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            brand_id="brand-1",
            brand_slug="brand-one",
        )

    updates = []

    async def set_consent(**kwargs):
        updates.append(kwargs)

    monkeypatch.setattr(messages_module.conversation_scope_store, "require_active_widget_scope", require_scope)
    monkeypatch.setattr(messages_module.conversation_scope_store, "set_long_term_memory_consent", set_consent)
    service = _PrivacyService()
    service.deletion_status = deletion_status
    monkeypatch.setattr(messages_module, "PrivacyLifecycleService", lambda _settings: service)

    app = FastAPI()
    app.include_router(messages_module.router, prefix="/api/v1/messages")
    return TestClient(app), session_token, updates


def test_public_privacy_export_requires_a_signed_session(monkeypatch):
    client, _, _ = _client(monkeypatch)

    response = client.get("/api/v1/messages/privacy/export")

    assert response.status_code == 401


def test_public_privacy_export_is_no_store_and_tenant_bound(monkeypatch):
    client, token, _ = _client(monkeypatch)

    response = client.get(
        "/api/v1/messages/privacy/export",
        headers={"X-Widget-Session": token},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["subject"]["conversation_ids"] == ["conv_1"]


def test_public_privacy_deletion_reports_pending_external_processor(monkeypatch):
    client, token, _ = _client(monkeypatch)

    response = client.delete(
        "/api/v1/messages/privacy",
        headers={"X-Widget-Session": token},
    )

    assert response.status_code == 202
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["external_processors"][0]["name"] == "strapi"


def test_public_privacy_deletion_returns_200_only_after_completed_receipt(monkeypatch):
    client, token, _ = _client(monkeypatch, deletion_status="completed")

    response = client.delete(
        "/api/v1/messages/privacy",
        headers={"X-Widget-Session": token},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_public_privacy_deletion_keeps_noncompleted_states_pending(monkeypatch):
    client, token, _ = _client(monkeypatch, deletion_status="failed")

    response = client.delete(
        "/api/v1/messages/privacy",
        headers={"X-Widget-Session": token},
    )

    assert response.status_code == 202


def test_withdrawing_consent_erases_long_term_facts(monkeypatch):
    client, token, updates = _client(monkeypatch)

    response = client.put(
        "/api/v1/messages/privacy/consent",
        headers={"X-Widget-Session": token},
        json={"long_term_memory_consent": False, "policy_version": "privacy-v1"},
    )

    assert response.status_code == 200
    assert response.json()["withdrawal"] == {"deleted": 3, "verified": True}
    assert updates[0]["granted"] is False
    assert updates[0]["policy_version"] == "privacy-v1"
