"""Widget session token tests — the conversation-hijacking fix.

These verify that the public message endpoints derive conversation/user identity
from a server-signed token, so a caller cannot address another visitor's
conversation by supplying its id.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.auth.widget_session import (
    WidgetSession,
    decode_widget_session,
    encode_widget_session,
    issue_widget_session,
)
from commons.types.requests import MessageRequest


def test_issue_and_decode_round_trip():
    token, session = issue_widget_session("agent-1")
    decoded = decode_widget_session(token, expected_agent_id="agent-1")
    assert decoded == session
    assert session.conversation_id.startswith("conv_")
    assert session.user_id.startswith("user_")


def test_fresh_sessions_have_distinct_identities():
    _, a = issue_widget_session("agent-1")
    _, b = issue_widget_session("agent-1")
    assert a.conversation_id != b.conversation_id
    assert a.user_id != b.user_id


def test_token_is_rejected_for_a_different_agent():
    token, _ = issue_widget_session("agent-1")
    # A token minted for agent-1 must not authorize a conversation on agent-2.
    assert decode_widget_session(token, expected_agent_id="agent-2") is None


def test_tampered_token_is_rejected():
    token, _ = issue_widget_session("agent-1")
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    assert decode_widget_session(tampered, expected_agent_id="agent-1") is None


def test_missing_token_is_rejected():
    assert decode_widget_session(None, expected_agent_id="agent-1") is None
    assert decode_widget_session("", expected_agent_id="agent-1") is None


def test_non_widget_token_is_rejected():
    # A random JWT-shaped string that isn't a widget_session token.
    from jose import jwt
    from app.config import Settings

    forged = jwt.encode(
        {"cid": "conv_x", "uid": "user_x", "aid": "agent-1", "type": "access"},
        Settings().SECRET_KEY,
        algorithm="HS256",
    )
    assert decode_widget_session(forged, expected_agent_id="agent-1") is None


def test_resume_preserves_identity():
    token, session = issue_widget_session("agent-1")
    reissued = encode_widget_session(session)
    decoded = decode_widget_session(reissued, expected_agent_id="agent-1")
    assert decoded == session


# ── HTTP-layer enforcement ────────────────────────────────────────────────

class _FakeAgents:
    def __init__(self, agents):
        self._agents = agents

    async def find_one(self, query, projection=None):
        for agent in self._agents:
            if all(agent.get(k) == v for k, v in query.items()):
                return dict(agent)
        return None


class _FakeSystemDb:
    def __init__(self, agents):
        self.agents = _FakeAgents(agents)


@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.endpoints import messages as messages_module

    monkeypatch.setattr(
        messages_module.connection_manager,
        "get_system_db",
        lambda: _FakeSystemDb([
            {"id": "agent-1", "status": "active", "brand_id": "brand-1", "brand_slug": "brand-one"}
        ]),
    )

    async def bind_scope(**_kwargs):
        return None

    monkeypatch.setattr(messages_module.conversation_scope_store, "bind", bind_scope)

    app = FastAPI()
    app.include_router(messages_module.router, prefix="/api/v1/messages")
    return TestClient(app)


def test_stream_without_token_is_unauthorized(client):
    resp = client.post(
        "/api/v1/messages/stream",
        json={"message": "hi", "user_id": "victim-user", "conversation_id": "victim-conv", "agent_id": "agent-1"},
    )
    assert resp.status_code == 401


def test_session_endpoint_issues_token_for_active_agent(client):
    resp = client.post("/api/v1/messages/session", json={"agent_id": "agent-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"].startswith("conv_")
    assert body["user_id"].startswith("user_")
    decoded = decode_widget_session(body["session_token"], expected_agent_id="agent-1")
    assert decoded is not None
    assert decoded.conversation_id == body["conversation_id"]


def test_session_endpoint_rejects_unknown_agent(client):
    resp = client.post("/api/v1/messages/session", json={"agent_id": "ghost"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_widget_control_requires_a_signed_session_bound_to_its_scope(monkeypatch):
    from app.api.v1.endpoints import messages as messages_module
    from app.services.conversation_scope_store import ConversationScope

    token, session = issue_widget_session("agent-1")
    websocket = SimpleNamespace(
        headers={"sec-websocket-protocol": f"widget-session, {token}"},
        closed=None,
    )

    async def close(*, code, reason):
        websocket.closed = {"code": code, "reason": reason}

    websocket.close = close

    async def get_scope(*, conversation_id, user_id, agent_id):
        assert conversation_id == session.conversation_id
        assert user_id == session.user_id
        assert agent_id == session.agent_id
        return ConversationScope(
            conversation_id=session.conversation_id,
            user_id=session.user_id,
            agent_id="agent-1",
            brand_id="brand-1",
            brand_slug="brand-one",
        )

    monkeypatch.setattr(messages_module.conversation_scope_store, "require_active_widget_scope", get_scope)

    result = await messages_module._require_widget_control_scope(websocket, session.conversation_id)

    assert result is not None
    assert result[0] == session
    assert websocket.closed is None


@pytest.mark.asyncio
async def test_widget_control_rejects_a_valid_token_for_another_conversation():
    from app.api.v1.endpoints import messages as messages_module

    token, _ = issue_widget_session("agent-1")
    websocket = SimpleNamespace(
        headers={"sec-websocket-protocol": f"widget-session, {token}"},
        closed=None,
    )

    async def close(*, code, reason):
        websocket.closed = {"code": code, "reason": reason}

    websocket.close = close

    result = await messages_module._require_widget_control_scope(websocket, "conv_other")

    assert result is None
    assert websocket.closed["code"] == 1008


@pytest.mark.asyncio
async def test_normal_widget_message_rejects_session_when_immutable_scope_is_invalid(monkeypatch):
    from fastapi import HTTPException
    from app.api.v1.endpoints import messages as messages_module
    from app.services.conversation_scope_store import ConversationScopeAuthorizationError

    token, _ = issue_widget_session("agent-1")

    async def reject_scope(**_kwargs):
        raise ConversationScopeAuthorizationError("agent moved brands")

    monkeypatch.setattr(messages_module.conversation_scope_store, "require_active_widget_scope", reject_scope)
    request = MessageRequest(message="hello", user_id="untrusted-user", agent_id="agent-1")

    with pytest.raises(HTTPException) as exc_info:
        await messages_module._require_widget_session(request, token)

    assert exc_info.value.status_code == 401
    assert request.conversation_id is None


@pytest.mark.asyncio
async def test_admin_takeover_requires_operator_brand_scope(monkeypatch):
    from app.api.v1.endpoints import messages as messages_module
    from app.auth.models import UserRole
    from app.services.conversation_scope_store import ConversationScope

    websocket = SimpleNamespace(
        headers={"sec-websocket-protocol": "bearer, dashboard-token"},
        closed=None,
    )

    async def close(*, code, reason):
        websocket.closed = {"code": code, "reason": reason}

    websocket.close = close

    operator = SimpleNamespace(
        role=UserRole.OPERATOR,
        has_permission=lambda permission: permission.value == "message:write",
        has_brand_access=lambda brand_id: brand_id == "brand-1",
    )

    async def current_user(*_args, **_kwargs):
        return operator

    async def active_user(user):
        return user

    async def get_scope(_conversation_id):
        return ConversationScope(
            conversation_id="conv_1",
            user_id="user_1",
            agent_id="agent-1",
            brand_id="brand-2",
            brand_slug="brand-two",
        )

    monkeypatch.setattr(messages_module, "get_current_user", current_user)
    monkeypatch.setattr(messages_module, "get_current_active_user", active_user)
    monkeypatch.setattr(messages_module.conversation_scope_store, "get", get_scope)
    monkeypatch.setattr(messages_module.connection_manager, "get_system_db", lambda: object())

    result = await messages_module._require_admin_takeover_scope(websocket, "conv_1")

    assert result is None
    assert websocket.closed["reason"] == "Conversation is outside your scope"
