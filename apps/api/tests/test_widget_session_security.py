"""Widget session token tests — the conversation-hijacking fix.

These verify that the public message endpoints derive conversation/user identity
from a server-signed token, so a caller cannot address another visitor's
conversation by supplying its id.
"""

from __future__ import annotations

import pytest

from app.auth.widget_session import (
    WidgetSession,
    decode_widget_session,
    encode_widget_session,
    issue_widget_session,
)


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
        lambda: _FakeSystemDb([{"id": "agent-1", "status": "active"}]),
    )

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
