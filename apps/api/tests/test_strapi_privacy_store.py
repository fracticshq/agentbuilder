"""Offline coverage for the durable, opaque Strapi privacy outbox."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from app.connections import connection_manager
from app.services.strapi_privacy_store import (
    STRAPI_PRIVACY_REQUESTS_COLLECTION,
    StrapiPrivacyStore,
    idempotency_reference,
    subject_reference,
)


class _Result:
    def __init__(self, matched_count: int = 0):
        self.matched_count = matched_count


def _value(document, key):
    value = document
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, item) for item in expected):
                return False
            continue
        actual = _value(document, key)
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$in" and actual not in operand:
                    return False
                if operator == "$lte" and (actual is None or actual > operand):
                    return False
        elif actual != expected:
            return False
    return True


class _Collection:
    def __init__(self):
        self.documents = {}

    async def create_index(self, *_args, **kwargs):
        return kwargs.get("name")

    async def insert_one(self, document):
        if document["_id"] in self.documents or any(
            row.get("operation_key") == document.get("operation_key") for row in self.documents.values()
        ):
            raise DuplicateKeyError("duplicate")
        self.documents[document["_id"]] = deepcopy(document)

    async def find_one(self, query, projection=None):
        for row in self.documents.values():
            if _matches(row, query):
                return deepcopy(row)
        return None

    async def find_one_and_update(self, query, update, sort=None, return_document=None):
        candidates = [row for row in self.documents.values() if _matches(row, query)]
        if not candidates:
            return None
        if sort:
            for field, direction in reversed(sort):
                candidates.sort(key=lambda row: _value(row, field), reverse=direction < 0)
        row = candidates[0]
        for key, value in update.get("$set", {}).items():
            row[key] = deepcopy(value)
        for key, value in update.get("$inc", {}).items():
            row[key] = row.get(key, 0) + value
        return deepcopy(row)

    async def update_one(self, query, update, upsert=False):
        row = next((row for row in self.documents.values() if _matches(row, query)), None)
        if row is None:
            return _Result()
        for key, value in update.get("$set", {}).items():
            row[key] = deepcopy(value)
        for key, value in update.get("$inc", {}).items():
            row[key] = row.get(key, 0) + value
        for key in update.get("$unset", {}):
            row.pop(key, None)
        return _Result(1)


class _SystemDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


def _settings(**overrides):
    values = {
        "STRAPI_PRIVACY_MODE": "contract_pending",
        "STRAPI_PRIVACY_LEASE_SECONDS": 30,
        "STRAPI_PRIVACY_MAX_ATTEMPTS": 3,
        "STRAPI_PRIVACY_RETRY_DELAY_SECONDS": 5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def system_db(monkeypatch):
    system = _SystemDb()
    monkeypatch.setattr(connection_manager, "get_system_db", lambda: system)
    return system


def test_subject_reference_is_deterministic_and_tenant_scoped():
    key = "h" * 32
    first = subject_reference(subject_id="subject-a", brand_id="brand-a", secret=key)
    assert first == subject_reference(subject_id="subject-a", brand_id="brand-a", secret=key)
    assert first != subject_reference(subject_id="subject-a", brand_id="brand-b", secret=key)
    assert first != subject_reference(subject_id="subject-b", brand_id="brand-a", secret=key)
    assert first != idempotency_reference(subject_id="subject-a", brand_id="brand-a", secret=key)


@pytest.mark.asyncio
async def test_outbox_creation_is_idempotent_and_contains_no_raw_subject(system_db):
    key = "h" * 32
    reference = subject_reference(subject_id="subject-a", brand_id="brand-a", secret=key)
    idempotency_key = idempotency_reference(subject_id="subject-a", brand_id="brand-a", secret=key)
    store = StrapiPrivacyStore(_settings())

    first, created = await store.create_or_get_deletion_request(
        brand_id="brand-a",
        brand_slug="brand-a-slug",
        subject_reference=reference,
        idempotency_key=idempotency_key,
    )
    second, reused = await store.create_or_get_deletion_request(
        brand_id="brand-a",
        brand_slug="brand-a-slug",
        subject_reference=reference,
        idempotency_key=idempotency_key,
    )

    assert created is True
    assert reused is False
    assert first["request_id"] == second["request_id"]
    assert first["status"] == "pending_contract"
    persisted = next(iter(system_db[STRAPI_PRIVACY_REQUESTS_COLLECTION].documents.values()))
    assert "subject-a" not in repr(persisted)
    assert "conversation" not in persisted
    assert persisted["subject_reference"] == reference


@pytest.mark.asyncio
async def test_lease_reclaim_fencing_and_retry_are_durable(system_db):
    key = "h" * 32
    reference = subject_reference(subject_id="subject-a", brand_id="brand-a", secret=key)
    idempotency_key = idempotency_reference(subject_id="subject-a", brand_id="brand-a", secret=key)
    settings = _settings(STRAPI_PRIVACY_MODE="active")
    store = StrapiPrivacyStore(settings)
    request, _ = await store.create_or_get_deletion_request(
        brand_id="brand-a",
        brand_slug="brand-a-slug",
        subject_reference=reference,
        idempotency_key=idempotency_key,
    )

    first = await store.claim_next(worker_id="worker-one")
    assert first and first["request_id"] == request["request_id"]
    assert await store.claim_next(worker_id="worker-two") is None

    persisted = system_db[STRAPI_PRIVACY_REQUESTS_COLLECTION].documents[request["request_id"]]
    persisted["lease_expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    second = await store.claim_next(worker_id="worker-two")
    assert second and second["lease_token"] != first["lease_token"]

    receipt = {
        "schema_version": "strapi-privacy-receipt-v1",
        "receipt_id": "remote-1",
        "completed_at": "2026-07-20T00:00:00Z",
        "verified": True,
        "signature_fingerprint": "a" * 64,
    }
    assert not await store.complete(first, receipt=receipt)
    assert await store.retry_or_fail(second, error_code="network", error_type="TimeoutError")
    assert persisted["status"] == "queued"
    assert persisted["phase"] == "retry_scheduled"
    assert "lease_token" not in persisted
