"""Offline mode-gating and worker transition checks for Strapi privacy."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.workers.strapi_privacy_worker import run_once


class _NoNetworkClient:
    def __init__(self):
        self.calls = 0

    async def request_deletion(self, _request):
        self.calls += 1
        return {
            "schema_version": "strapi-privacy-receipt-v1",
            "receipt_id": "receipt-1",
            "completed_at": "2026-07-20T00:00:00Z",
            "verified": True,
            "signature_fingerprint": "a" * 64,
        }


class _Store:
    def __init__(self, request=None):
        self.request = request
        self.completed = []
        self.retries = []

    async def claim_next(self, *, worker_id):
        request, self.request = self.request, None
        return request

    async def complete(self, request, *, receipt):
        self.completed.append((request, receipt))
        return True

    async def retry_or_fail(self, request, *, error_code, error_type):
        self.retries.append((request, error_code, error_type))
        return True

    async def renew_lease(self, _request):
        return True


@pytest.mark.asyncio
async def test_contract_pending_mode_makes_no_network_attempt_or_claim():
    settings = SimpleNamespace(
        STRAPI_PRIVACY_MODE="contract_pending",
        STRAPI_PRIVACY_LEASE_SECONDS=30,
    )
    client = _NoNetworkClient()
    store = _Store(request={"request_id": "must-not-be-claimed"})

    assert await run_once(store, settings, identifier="worker", client=client) is False
    assert client.calls == 0
    assert store.request["request_id"] == "must-not-be-claimed"


@pytest.mark.asyncio
async def test_active_worker_marks_completed_only_from_verified_client_receipt():
    settings = SimpleNamespace(
        STRAPI_PRIVACY_MODE="active",
        STRAPI_PRIVACY_LEASE_SECONDS=30,
    )
    request = {"request_id": "strapi_privacy_" + "a" * 32, "lease_token": "lease-1"}
    client = _NoNetworkClient()
    store = _Store(request=request)

    assert await run_once(store, settings, identifier="worker", client=client) is True
    assert client.calls == 1
    assert store.completed[0][1]["verified"] is True
    assert store.retries == []
