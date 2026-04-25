from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.auth import auth_router
from app.auth.dependencies import get_db
from app.auth.password import hash_password, verify_password


class FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeUpdateResult:
    def __init__(self, matched_count=0, modified_count=0):
        self.matched_count = matched_count
        self.modified_count = modified_count


class FakeCursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]

    async def to_list(self, length=None):
        if length is None:
            return list(self.documents)
        return list(self.documents)[:length]

    def sort(self, *_args, **_kwargs):
        return self


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = [deepcopy(document) for document in (documents or [])]

    def _matches(self, document, query):
        if not query:
            return True

        for key, expected in query.items():
            if key == "$or":
                return any(self._matches(document, branch) for branch in expected)

            actual = document.get(key)
            if isinstance(expected, dict):
                if "$gt" in expected:
                    if actual is None or not actual > expected["$gt"]:
                        return False
                    continue
                if "$ne" in expected:
                    if actual == expected["$ne"]:
                        return False
                    continue

            if actual != expected:
                return False

        return True

    async def find_one(self, query=None, projection=None):
        for document in self.documents:
            if self._matches(document, query or {}):
                if projection:
                    return {
                        key: value
                        for key, value in document.items()
                        if key in projection or projection.get(key) == 1
                    }
                return deepcopy(document)
        return None

    def find(self, query=None):
        return FakeCursor(
            document for document in self.documents if self._matches(document, query or {})
        )

    async def insert_one(self, document):
        stored = deepcopy(document)
        stored.setdefault("_id", ObjectId())
        self.documents.append(stored)
        return FakeInsertResult(stored["_id"])

    async def update_one(self, query, update, upsert=False):
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                if "$set" in update:
                    document.update(deepcopy(update["$set"]))
                self.documents[index] = document
                return FakeUpdateResult(matched_count=1, modified_count=1)

        if upsert:
            stored = deepcopy(query)
            stored.update(deepcopy(update.get("$setOnInsert", {})))
            stored.update(deepcopy(update.get("$set", {})))
            stored.setdefault("_id", ObjectId())
            self.documents.append(stored)
            return FakeUpdateResult(matched_count=0, modified_count=1)

        return FakeUpdateResult()

    async def update_many(self, query, update):
        matched = 0
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                matched += 1
                if "$set" in update:
                    document.update(deepcopy(update["$set"]))
                self.documents[index] = document
        return FakeUpdateResult(matched_count=matched, modified_count=matched)


class FakeDatabase:
    def __init__(self, *, users=None, refresh_tokens=None, password_reset_tokens=None):
        self.users = FakeCollection(users)
        self.refresh_tokens = FakeCollection(refresh_tokens)
        self.password_reset_tokens = FakeCollection(password_reset_tokens)


def build_client(db):
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_auth_config_exposes_signup_and_google_flags(monkeypatch):
    from app.api.v1.auth import google as google_module

    db = FakeDatabase(users=[])
    client = build_client(db)

    monkeypatch.setattr(
        google_module,
        "Settings",
        lambda: SimpleNamespace(ALLOW_PUBLIC_SIGNUP=False, GOOGLE_CLIENT_ID="google-client-id"),
    )

    response = client.get("/api/v1/auth/config")

    assert response.status_code == 200
    assert response.json() == {
        "signup_enabled": True,
        "google_enabled": True,
        "google_client_id": "google-client-id",
    }


def test_password_login_accepts_user_documents_with_object_ids(monkeypatch):
    from app.api.v1.auth import login as login_module

    user_id = ObjectId()
    db = FakeDatabase(
        users=[
            {
                "_id": user_id,
                "email": "anant@fractics.com",
                "username": "anant",
                "password_hash": hash_password("Test@123"),
                "full_name": "Anant",
                "role": "admin",
                "brands": [],
                "is_active": True,
                "is_verified": True,
                "failed_login_attempts": 0,
                "locked_until": None,
                "last_login": None,
                "created_at": "2026-04-23T00:00:00Z",
                "updated_at": "2026-04-23T00:00:00Z",
                "metadata": {},
            }
        ],
        refresh_tokens=[],
    )
    client = build_client(db)

    monkeypatch.setattr(
        login_module,
        "settings",
        SimpleNamespace(ACCESS_TOKEN_EXPIRE_MINUTES=30),
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "anant@fractics.com", "password": "Test@123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert db.users.documents[0]["failed_login_attempts"] == 0


def test_forgot_and_reset_password_flow(monkeypatch):
    from app.api.v1.auth import password_reset as reset_module

    user_id = ObjectId()
    db = FakeDatabase(
        users=[
            {
                "_id": user_id,
                "email": "owner@example.com",
                "username": "owner",
                "password_hash": hash_password("OldPassword123!"),
                "role": "admin",
                "brands": [],
                "is_active": True,
                "is_verified": True,
                "failed_login_attempts": 0,
                "locked_until": None,
                "created_at": "2026-04-23T00:00:00Z",
                "updated_at": "2026-04-23T00:00:00Z",
                "metadata": {},
            }
        ],
        refresh_tokens=[
            {
                "_id": ObjectId(),
                "token_hash": "placeholder",
                "user_id": str(user_id),
                "is_revoked": False,
            }
        ],
    )
    client = build_client(db)

    monkeypatch.setattr(
        reset_module,
        "Settings",
        lambda: SimpleNamespace(
            DEBUG=True,
            ADMIN_APP_URL="http://localhost:3000",
            PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=60,
        ),
    )

    forgot_response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "owner@example.com"},
    )

    assert forgot_response.status_code == 200
    reset_url = forgot_response.json()["reset_url"]
    assert reset_url.startswith("http://localhost:3000/reset-password?token=")
    token = reset_url.split("token=", 1)[1]

    reset_response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "NewPassword123!"},
    )

    assert reset_response.status_code == 200
    assert "Password reset successfully" in reset_response.json()["message"]

    updated_user = db.users.documents[0]
    assert verify_password("NewPassword123!", updated_user["password_hash"]) is True
    assert db.refresh_tokens.documents[0]["is_revoked"] is True
    assert db.password_reset_tokens.documents[0]["used_at"] is not None


def test_google_login_creates_first_operator(monkeypatch):
    from app.api.v1.auth import google as google_module

    db = FakeDatabase(users=[], refresh_tokens=[])
    client = build_client(db)

    monkeypatch.setattr(
        google_module,
        "Settings",
        lambda: SimpleNamespace(
            GOOGLE_CLIENT_ID="google-client-id",
            ACCESS_TOKEN_EXPIRE_MINUTES=30,
            REFRESH_TOKEN_EXPIRE_DAYS=7,
            ALLOW_PUBLIC_SIGNUP=False,
        ),
    )
    monkeypatch.setattr(
        google_module,
        "_verify_google_credential",
        lambda credential, expected_client_id: {
            "sub": "google-user-123",
            "email": "founder@example.com",
            "email_verified": True,
            "name": "Founding Admin",
            "picture": "https://example.com/founder.png",
        },
    )

    response = client.post("/api/v1/auth/google", json={"credential": "google-id-token"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert db.users.documents[0]["email"] == "founder@example.com"
    assert db.users.documents[0]["role"] == "admin"
    assert db.users.documents[0]["metadata"]["auth_providers"] == ["google"]
