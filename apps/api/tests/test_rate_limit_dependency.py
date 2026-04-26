from fastapi import APIRouter, Depends, FastAPI, WebSocket
from fastapi.testclient import TestClient

import json
import pytest
from types import SimpleNamespace

from app.security import rate_limiter as rate_limiter_module
from app.security.rate_limiter import RateLimiter, rate_limit_dependency


class FailingRedis:
    def pipeline(self):
        raise RuntimeError("redis down")


def test_rate_limit_dependency_supports_http_and_websocket(monkeypatch):
    async def allow_all(*_args, **_kwargs):
        return True, {
            "limit": 60,
            "remaining": 59,
            "reset_at": 1234567890,
            "retry_after": None,
            "policy": "default",
        }

    monkeypatch.setattr("app.security.rate_limiter.check_named_rate_limit", allow_all)

    app = FastAPI()
    router = APIRouter(dependencies=[Depends(rate_limit_dependency)])

    @router.get("/http")
    async def http_endpoint():
        return {"ok": True}

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("ok")
        await websocket.close()

    app.include_router(router)

    client = TestClient(app)

    response = client.get("/http")
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    with client.websocket_connect("/ws") as websocket:
        assert websocket.receive_text() == "ok"


def test_rate_limit_dependency_blocks_http_with_429(monkeypatch):
    async def deny(*_args, **_kwargs):
        return False, {
            "limit": 1,
            "remaining": 0,
            "reset_at": 1234567890,
            "retry_after": 30,
            "policy": "default",
        }

    monkeypatch.setattr("app.security.rate_limiter.check_named_rate_limit", deny)

    app = FastAPI()
    router = APIRouter(dependencies=[Depends(rate_limit_dependency)])

    @router.get("/http")
    async def http_endpoint():
        return {"ok": True}

    app.include_router(router)

    response = TestClient(app).get("/http")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.json()["detail"] == "Rate limit exceeded"


@pytest.mark.asyncio
async def test_rate_limiter_fail_open(monkeypatch):
    monkeypatch.setattr(rate_limiter_module.settings, "RATE_LIMIT_FAIL_CLOSED", False)

    allowed, info = await RateLimiter(FailingRedis()).check_rate_limit(
        key="test",
        limit=10,
        window=60,
    )

    assert allowed is True
    assert info["remaining"] == 10
    assert info["retry_after"] is None


@pytest.mark.asyncio
async def test_rate_limiter_fail_closed(monkeypatch):
    monkeypatch.setattr(rate_limiter_module.settings, "RATE_LIMIT_FAIL_CLOSED", True)

    allowed, info = await RateLimiter(FailingRedis()).check_rate_limit(
        key="test",
        limit=10,
        window=60,
    )

    assert allowed is False
    assert info["remaining"] == 0
    assert info["retry_after"] == 60


@pytest.mark.asyncio
async def test_websocket_rate_limit_sends_clear_event_before_close(monkeypatch):
    from app.api.v1.endpoints.messages import _enforce_websocket_rate_limit

    async def deny(*_args, **_kwargs):
        return False, {
            "limit": 1,
            "remaining": 0,
            "reset_at": 1234567890,
            "retry_after": 45,
            "policy": "widget_ws_message",
        }

    class FakeWebSocket:
        client = SimpleNamespace(host="127.0.0.1")

        def __init__(self):
            self.sent = []
            self.closed = None

        async def send_text(self, payload):
            self.sent.append(json.loads(payload))

        async def close(self, code, reason):
            self.closed = {"code": code, "reason": reason}

    monkeypatch.setattr("app.api.v1.endpoints.messages.check_named_rate_limit", deny)
    websocket = FakeWebSocket()

    allowed = await _enforce_websocket_rate_limit(
        websocket,
        "WS:/messages/ws/widget",
        "widget_ws_message",
        agent_id="agent-1",
        conversation_id="conv-1",
    )

    assert allowed is False
    assert websocket.sent[0]["type"] == "rate_limit"
    assert websocket.sent[0]["retry_after"] == 45
    assert websocket.closed["code"] == 1008
