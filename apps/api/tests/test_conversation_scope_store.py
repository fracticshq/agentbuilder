from copy import deepcopy

import pytest

from app.connections import connection_manager
from app.services.conversation_scope_store import ConversationScopeStore


class _Result:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class _Collection:
    def __init__(self):
        self.documents = {}

    async def create_index(self, *args, **kwargs):
        return kwargs.get("name")

    async def insert_one(self, document):
        self.documents[document["_id"]] = deepcopy(document)
        return _Result()

    async def find_one(self, query):
        document = self.documents.get(query.get("_id"))
        return deepcopy(document) if document else None

    async def update_one(self, query, update):
        document = self.documents.get(query.get("_id"))
        if document is None:
            return _Result(matched_count=0)
        document.update(deepcopy(update.get("$set", {})))
        return _Result()


class _SystemDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.mark.asyncio
async def test_conversation_scope_is_durably_bound_to_the_signed_session_identity(monkeypatch):
    system_db = _SystemDb()
    monkeypatch.setattr(connection_manager, "get_system_db", lambda: system_db)
    store = ConversationScopeStore()

    bound = await store.bind(
        conversation_id="conv_1",
        user_id="user_1",
        agent_id="agent_1",
        brand_id="brand_1",
        brand_slug="brand-one",
    )

    assert bound == await store.get("conv_1")
    stored = system_db["widget_conversation_scopes"].documents["conv_1"]
    assert stored["agent_id"] == "agent_1"
    assert stored["brand_id"] == "brand_1"
    assert stored["expires_at"] > stored["created_at"]
