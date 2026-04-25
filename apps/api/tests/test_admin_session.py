from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin.session import router
from app.auth.dependencies import get_current_active_user, get_db


def build_test_client(*, authenticated_user=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin/session")
    app.dependency_overrides[get_db] = lambda: object()
    if authenticated_user is not None:
        app.dependency_overrides[get_current_active_user] = lambda: authenticated_user
    return TestClient(app)


def test_validate_admin_session_rejects_missing_credentials():
    client = build_test_client()

    response = client.get("/api/v1/admin/session/validate")

    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


def test_validate_admin_session_returns_authenticated_user_details():
    client = build_test_client(
        authenticated_user=type(
            "User",
            (),
            {"email": "admin@example.com", "role": "admin"},
        )()
    )

    response = client.get("/api/v1/admin/session/validate")

    assert response.status_code == 200
    assert response.json() == {
        "authorized": True,
        "email": "admin@example.com",
        "role": "admin",
    }
