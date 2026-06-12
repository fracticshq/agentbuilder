"""Agent API conversation-scoping tests.

A holder of a valid agent API key must not be able to read or continue another
user's conversation on the same agent by supplying an arbitrary conversation_id.
Conversation identity is derived from a session the key owns.
"""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import HTTPException

from app.api.v1 import agent_api as agent_api_module
from app.services.agent_api_keys import AgentApiKeyContext


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = [deepcopy(d) for d in (documents or [])]

    async def find_one(self, query):
        for document in self.documents:
            if all(document.get(k) == v for k, v in (query or {}).items()):
                return deepcopy(document)
        return None


class FakeSystemDb:
    def __init__(self, agents, sessions):
        self.agents = FakeCollection(agents)
        self.agent_api_sessions = FakeCollection(sessions)

    def __getitem__(self, name):
        return getattr(self, name)


def _context(agent_id="agent-1", brand_id=None):
    return AgentApiKeyContext(
        id="ctx",
        key_id="key-1",
        scopes={"agent-api:*"},
        agent_id=agent_id,
        brand_id=brand_id,
    )


AGENT = {
    "id": "agent-1",
    "brand_id": "brand-1",
    "configuration": {"agent_api": {"enabled": True}},
}


@pytest.fixture
def patched_db(monkeypatch):
    def _install(sessions):
        db = FakeSystemDb([AGENT], sessions)
        monkeypatch.setattr(agent_api_module.connection_manager, "get_system_db", lambda: db)
        return db
    return _install


def _request(**kwargs):
    return agent_api_module.AgentApiMessageRequest(message="hi", **kwargs)


@pytest.mark.asyncio
async def test_unknown_conversation_id_is_rejected(patched_db):
    patched_db(sessions=[])  # no sessions exist
    with pytest.raises(HTTPException) as exc:
        await agent_api_module._resolve_message_target(
            _request(agent_id="agent-1", conversation_id="someone-elses-conv"),
            _context(),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_owned_conversation_id_resolves(patched_db):
    patched_db(sessions=[
        {"id": "s1", "conversation_id": "conv-mine", "agent_id": "agent-1", "brand_id": "brand-1"},
    ])
    agent_id, conversation_id, session = await agent_api_module._resolve_message_target(
        _request(agent_id="agent-1", conversation_id="conv-mine"),
        _context(),
    )
    assert agent_id == "agent-1"
    assert conversation_id == "conv-mine"
    assert session is not None


@pytest.mark.asyncio
async def test_session_id_path_ignores_client_conversation_override(patched_db):
    patched_db(sessions=[
        {"id": "s1", "conversation_id": "conv-real", "agent_id": "agent-1", "brand_id": "brand-1"},
    ])
    _, conversation_id, _ = await agent_api_module._resolve_message_target(
        _request(session_id="s1", conversation_id="conv-attacker-supplied"),
        _context(),
    )
    # The session's conversation_id wins; the client override is ignored.
    assert conversation_id == "conv-real"


@pytest.mark.asyncio
async def test_fresh_conversation_is_minted_when_none_supplied(patched_db):
    patched_db(sessions=[])
    _, conversation_id, session = await agent_api_module._resolve_message_target(
        _request(agent_id="agent-1"),
        _context(),
    )
    assert conversation_id  # server-minted uuid
    assert session is None


@pytest.mark.asyncio
async def test_conversation_owned_by_other_brand_is_rejected(patched_db):
    patched_db(sessions=[
        {"id": "s1", "conversation_id": "conv-other", "agent_id": "agent-1", "brand_id": "brand-2"},
    ])
    with pytest.raises(HTTPException) as exc:
        await agent_api_module._resolve_message_target(
            _request(agent_id="agent-1", conversation_id="conv-other"),
            _context(brand_id="brand-1"),
        )
    assert exc.value.status_code == 403
