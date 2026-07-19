import pytest

from app.services.strapi_client import StrapiClient


def test_blank_token_disables_strapi_sync_client():
    client = StrapiClient("http://strapi.local", "")

    assert client._enabled is False


@pytest.mark.asyncio
async def test_sync_saves_turn_messages_sequentially(monkeypatch):
    client = StrapiClient("http://strapi.local", "token")
    events = []
    assistant_metadata = {"products": [{"sku": "P1"}], "dealers": [], "metadata": {"commerce_intent": {}}}

    async def fake_ensure_session(*_args, **_kwargs):
        events.append("session")

    async def fake_save_message(_conversation_id, _content, role, **_kwargs):
        events.append(f"{role}:start")
        if role == "user":
            assert "agent:start" not in events
            assert _kwargs.get("metadata") is None
        if role == "agent":
            assert _kwargs.get("metadata") == assistant_metadata
        events.append(f"{role}:end")

    monkeypatch.setattr(client, "_ensure_session", fake_ensure_session)
    monkeypatch.setattr(client, "_save_message", fake_save_message)

    await client._sync(
        "conv-1",
        "hello",
        "hi",
        brand_slug="essco-bathware",
        agent_id="agent-1",
        assistant_metadata=assistant_metadata,
    )

    assert events == ["session", "user:start", "user:end", "agent:start", "agent:end"]


@pytest.mark.asyncio
async def test_save_message_payload_includes_optional_metadata(monkeypatch):
    client = StrapiClient("http://strapi.local", "token")
    payloads = []

    async def allow_sync(*_args, **_kwargs):
        return True

    async def record_post(_path, payload, **_kwargs):
        payloads.append(payload)

    async def record_sync_event(*_args, **_kwargs):
        return None

    monkeypatch.setattr(client, "_allow_sync", allow_sync)
    monkeypatch.setattr(client, "_post_with_retry", record_post)
    monkeypatch.setattr(client, "_record_sync_event", record_sync_event)

    metadata = {"products": [{"sku": "P1"}], "dealers": [], "metadata": {"search_query": "speakers"}}

    await client._save_message(
        "conv-1",
        "hello",
        "agent",
        brand_slug="essco-bathware",
        agent_id="agent-1",
        metadata=metadata,
    )

    assert payloads[0]["metadata"] == metadata


@pytest.mark.asyncio
async def test_message_sync_error_records_role(monkeypatch):
    client = StrapiClient("http://strapi.local", "token")
    recorded_events = []

    async def allow_sync(*_args, **_kwargs):
        return True

    async def fail_post(*_args, **_kwargs):
        raise RuntimeError("strapi down")

    async def record_sync_event(*args, **kwargs):
        recorded_events.append((args, kwargs))

    monkeypatch.setattr(client, "_allow_sync", allow_sync)
    monkeypatch.setattr(client, "_post_with_retry", fail_post)
    monkeypatch.setattr(client, "_record_sync_event", record_sync_event)

    await client._save_message("conv-1", "hello", "agent", brand_slug="essco-bathware", agent_id="agent-1")

    assert recorded_events[0][0][:3] == ("message", "error", "conv-1")
    assert recorded_events[0][1]["role"] == "agent"
    assert recorded_events[0][1]["error"] == "strapi down"
