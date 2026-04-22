from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin.session import router
from app.dependencies import get_settings


def build_settings(**overrides):
    base = {
        "ADMIN_API_KEY": "test-admin-key",
        "ALLOW_ADMIN_KEY_BYPASS": False,
        "is_production": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def build_test_client(settings):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin/session")
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_validate_admin_session_rejects_missing_key():
    client = build_test_client(build_settings())

    response = client.get("/api/v1/admin/session/validate")

    assert response.status_code == 401
    assert response.json()["detail"] == "X-Admin-Key header required"


def test_validate_admin_session_accepts_valid_key():
    client = build_test_client(build_settings())

    response = client.get(
        "/api/v1/admin/session/validate",
        headers={"X-Admin-Key": "test-admin-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"authorized": True}
