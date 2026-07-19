"""Regressions for fail-closed human-takeover WebSocket state."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketDisconnect

from app.api.v1.endpoints import messages as messages_endpoint
from app.websocket_manager import (
    ConnectionManager,
    TakeoverBufferIntegrityError,
    TakeoverStateUnavailableError,
)


class _FailingRedis:
    async def hset(self, *_args, **_kwargs):
        raise RuntimeError("redis credential: private")

    async def rpush(self, *_args, **_kwargs):
        raise RuntimeError("redis credential: private")


@pytest.mark.asyncio
async def test_configured_but_failing_redis_never_uses_local_takeover_state(monkeypatch):
    manager = ConnectionManager()
    monkeypatch.setattr(manager, "_redis", lambda: _FailingRedis())

    with pytest.raises(TakeoverStateUnavailableError):
        await manager.set_human_control("conv-1", True)
    with pytest.raises(TakeoverStateUnavailableError):
        await manager.buffer_takeover_message("conv-1", "user", "hello")

    assert manager._local_control == {}
    assert manager._local_buffers == {}


@pytest.mark.asyncio
async def test_invalid_redis_takeover_buffer_is_an_integrity_failure(monkeypatch):
    class _Redis:
        async def lrange(self, *_args):
            return [b'{"role": "user", "content": "unterminated"']

    manager = ConnectionManager()
    monkeypatch.setattr(manager, "_redis", lambda: _Redis())

    with pytest.raises(TakeoverBufferIntegrityError):
        await manager.get_takeover_buffer("conv-1")
    assert manager._local_buffers == {}


@pytest.mark.asyncio
async def test_release_with_invalid_buffer_keeps_operator_in_control(monkeypatch):
    class _Manager:
        def __init__(self):
            self.notices = []
            self.release_attempts = 0

        async def connect_admin(self, *_args, **_kwargs):
            return None

        async def disconnect_admin(self, *_args, **_kwargs):
            return None

        async def get_takeover_buffer(self, *_args, **_kwargs):
            raise TakeoverBufferIntegrityError("backend details must not reach the operator")

        async def set_human_control(self, *_args, **_kwargs):
            self.release_attempts += 1

        async def send_to_admin(self, _conversation_id, message):
            self.notices.append(message)

    class _WebSocket:
        headers = {}

        async def receive_text(self):
            if not hasattr(self, "sent_release"):
                self.sent_release = True
                return json.dumps({"type": "release_control"})
            raise WebSocketDisconnect()

    manager = _Manager()
    monkeypatch.setattr(messages_endpoint, "ws_manager", manager)
    monkeypatch.setattr(
        messages_endpoint,
        "_require_admin_takeover_scope",
        AsyncMock(return_value=SimpleNamespace(agent_id="agent-1", brand_slug="brand-1")),
    )
    monkeypatch.setattr(messages_endpoint, "_enforce_websocket_rate_limit", AsyncMock(return_value=True))
    monkeypatch.setattr(messages_endpoint, "get_settings", lambda: SimpleNamespace(ENABLE_HUMAN_TAKEOVER=True))

    await messages_endpoint.admin_websocket_endpoint(_WebSocket(), "conv-1", message_service=AsyncMock())

    assert manager.release_attempts == 0
    assert manager.notices == [{
        "type": "system_notice",
        "content": "Human takeover is temporarily unavailable. AI control remains with the operator; retry release.",
    }]
    assert "backend details" not in manager.notices[0]["content"]


@pytest.mark.asyncio
async def test_subscription_retries_after_listener_failure_while_recipients_remain(monkeypatch):
    class _Socket:
        def __init__(self):
            self.messages = []

        async def send_json(self, message):
            self.messages.append(message)

    class _PubSub:
        def __init__(self, redis, should_fail):
            self.redis = redis
            self.should_fail = should_fail

        async def subscribe(self, *_args):
            return None

        async def unsubscribe(self, *_args):
            return None

        async def aclose(self):
            return None

        async def listen(self):
            if self.should_fail:
                raise RuntimeError("transient redis listener failure")
            await self.redis.message_ready.wait()
            yield {
                "type": "message",
                "data": json.dumps({"origin": "other-instance", "message": {"type": "notice"}}),
            }

    class _Redis:
        def __init__(self):
            self.created = 0
            self.message_ready = asyncio.Event()

        def pubsub(self):
            self.created += 1
            return _PubSub(self, should_fail=self.created == 1)

    manager = ConnectionManager()
    redis = _Redis()
    socket = _Socket()
    manager.widget_connections["conv-1"] = {socket}
    monkeypatch.setattr(manager, "_redis", lambda: redis)

    manager._start_sub("conv-1", "widget")
    for _ in range(50):
        if redis.created >= 2:
            break
        await asyncio.sleep(0.01)
    assert redis.created >= 2

    redis.message_ready.set()
    for _ in range(50):
        if socket.messages:
            break
        await asyncio.sleep(0.01)
    assert socket.messages == [{"type": "notice"}]

    task = manager._sub_tasks.get("conv-1:widget")
    # Match the production disconnect path: subscriptions remain active while
    # this process still has a local recipient, so remove it before cleanup.
    manager.widget_connections.pop("conv-1", None)
    manager._stop_sub("conv-1", "widget")
    if task is not None:
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_failed_local_send_removes_closed_socket():
    class _ClosedSocket:
        async def send_json(self, _message):
            raise RuntimeError("closed")

    manager = ConnectionManager()
    manager.widget_connections["conv-1"] = {_ClosedSocket()}

    await manager.send_to_widget("conv-1", {"type": "notice"})

    assert "conv-1" not in manager.widget_connections
