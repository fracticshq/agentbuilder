"""Offline signed-request and signed-receipt tests for Strapi privacy."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.strapi_privacy_client import (
    STRAPI_PRIVACY_RECEIPT_SCHEMA,
    StrapiPrivacyClient,
    StrapiPrivacyRequestError,
    canonical_json,
)


def _settings(public_key: Ed25519PrivateKey, **overrides):
    raw_public_key = public_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    values = {
        "STRAPI_PRIVACY_URL": "https://strapi.example.test",
        "STRAPI_PRIVACY_REQUEST_SIGNING_KEY": "r" * 32,
        "STRAPI_PRIVACY_REQUEST_KEY_ID": "privacy-key-1",
        "STRAPI_PRIVACY_SUBJECT_HMAC_KEY": "s" * 32,
        "STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY": base64.b64encode(raw_public_key).decode("ascii"),
        "STRAPI_PRIVACY_TIMEOUT_SECONDS": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _request():
    return {
        "request_id": "strapi_privacy_" + "a" * 32,
        "idempotency_key": "spid_" + "b" * 64,
        "brand_id": "brand-a",
        "subject_reference": "c" * 64,
    }


def _receipt(private_key: Ed25519PrivateKey, request: dict, **overrides):
    values = {
        "schema_version": STRAPI_PRIVACY_RECEIPT_SCHEMA,
        "receipt_id": "receipt-1",
        "request_id": request["request_id"],
        "idempotency_key": request["idempotency_key"],
        "tenant_id": request["brand_id"],
        "subject_reference": request["subject_reference"],
        "status": "completed",
        "deletion_verified": True,
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    values.update(overrides)
    values["signature"] = base64.b64encode(private_key.sign(canonical_json(values))).decode("ascii")
    return values


@pytest.mark.asyncio
async def test_client_sends_canonical_signed_opaque_request_and_accepts_verified_receipt():
    private_key = Ed25519PrivateKey.generate()
    request = _request()
    captured = {}

    async def handler(incoming: httpx.Request):
        captured["headers"] = dict(incoming.headers)
        captured["body"] = json.loads(incoming.content)
        return httpx.Response(200, json=_receipt(private_key, request))

    client = StrapiPrivacyClient(_settings(private_key), transport=httpx.MockTransport(handler))
    verified = await client.request_deletion(request)

    assert verified["verified"] is True
    assert verified["receipt_id"] == "receipt-1"
    assert captured["body"]["subject_reference"] == request["subject_reference"]
    assert "authorization" not in captured["headers"]
    assert captured["headers"]["x-strapi-privacy-signature"]
    assert "subject-a" not in json.dumps(captured["body"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "receipt_factory",
    [
        lambda private_key, request: {},
        lambda private_key, request: _receipt(private_key, request, request_id="wrong-request"),
        lambda private_key, request: {**_receipt(private_key, request), "signature": base64.b64encode(b"bad").decode("ascii")},
    ],
)
async def test_client_rejects_missing_mismatched_or_unsigned_receipts(receipt_factory):
    private_key = Ed25519PrivateKey.generate()
    request = _request()

    async def handler(_incoming: httpx.Request):
        return httpx.Response(200, json=receipt_factory(private_key, request))

    client = StrapiPrivacyClient(_settings(private_key), transport=httpx.MockTransport(handler))
    with pytest.raises(StrapiPrivacyRequestError):
        await client.request_deletion(request)
