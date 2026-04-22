from fastapi import APIRouter, Depends, FastAPI, WebSocket
from fastapi.testclient import TestClient

from app.security.rate_limiter import rate_limit_dependency


def test_rate_limit_dependency_supports_http_and_websocket(monkeypatch):
    async def allow_all(**_kwargs):
        return True, {
            "limit": 60,
            "remaining": 59,
            "reset_at": 1234567890,
            "retry_after": None,
        }

    monkeypatch.setattr("app.security.rate_limiter.check_rate_limit", allow_all)

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
