"""Dedicated signed client for the future Strapi privacy deletion endpoint.

It intentionally does not share the legacy dashboard sync URL or bearer token.
Every successful response must carry a correlated Ed25519-signed receipt;
network success or an unsigned JSON acknowledgement is never treated as erasure.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

try:
    import httpx
except ImportError:  # pragma: no cover - production requirement, defensive only
    httpx = None  # type: ignore[assignment]

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


STRAPI_PRIVACY_DELETE_PATH = "/api/privacy/deletions"
STRAPI_PRIVACY_REQUEST_SCHEMA = "strapi-privacy-request-v1"
STRAPI_PRIVACY_RECEIPT_SCHEMA = "strapi-privacy-receipt-v1"
_RECEIPT_SIGNED_FIELDS = {
    "schema_version",
    "receipt_id",
    "request_id",
    "idempotency_key",
    "tenant_id",
    "subject_reference",
    "status",
    "deletion_verified",
    "completed_at",
}
_OPAQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUEST_ID_PATTERN = re.compile(r"^strapi_privacy_[a-f0-9]{32}$")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^spid_[a-f0-9]{64}$")
_SUBJECT_REFERENCE_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class StrapiPrivacyConfigurationError(RuntimeError):
    """Active privacy processing is missing a safe, dedicated configuration."""


class StrapiPrivacyRequestError(RuntimeError):
    """The remote processor did not return a verified completion receipt."""


def canonical_json(value: dict[str, Any]) -> bytes:
    """Canonical JSON used for both request and receipt signatures."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _base64_decode(value: str, *, field: str) -> bytes:
    if not isinstance(value, str) or not value.strip():
        raise StrapiPrivacyConfigurationError(f"{field} is required")
    padded = value.strip() + "=" * (-len(value.strip()) % 4)
    try:
        return base64.b64decode(padded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise StrapiPrivacyConfigurationError(f"{field} must be base64") from exc


def load_receipt_public_key(value: str) -> Ed25519PublicKey:
    """Load a pinned Ed25519 receipt key from PEM or base64 raw 32-byte form."""
    if not isinstance(value, str) or not value.strip():
        raise StrapiPrivacyConfigurationError("STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY is required")
    candidate = value.strip()
    try:
        if candidate.startswith("-----BEGIN"):
            key = serialization.load_pem_public_key(candidate.encode("utf-8"))
            if not isinstance(key, Ed25519PublicKey):
                raise StrapiPrivacyConfigurationError("STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY must be Ed25519")
            return key
        raw = _base64_decode(candidate, field="STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY")
        if len(raw) != 32:
            raise StrapiPrivacyConfigurationError("STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY must decode to 32 bytes")
        return Ed25519PublicKey.from_public_bytes(raw)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, StrapiPrivacyConfigurationError):
            raise
        raise StrapiPrivacyConfigurationError("Invalid STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY") from exc


def validate_active_privacy_configuration(settings: Any) -> None:
    """Validate the independent active-mode endpoint, signing key, and pin."""
    url = str(getattr(settings, "STRAPI_PRIVACY_URL", "") or "").strip()
    request_key = str(getattr(settings, "STRAPI_PRIVACY_REQUEST_SIGNING_KEY", "") or "").strip()
    subject_key = str(getattr(settings, "STRAPI_PRIVACY_SUBJECT_HMAC_KEY", "") or "").strip()
    key_id = str(getattr(settings, "STRAPI_PRIVACY_REQUEST_KEY_ID", "") or "").strip()
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise StrapiPrivacyConfigurationError("STRAPI_PRIVACY_URL must be an absolute https URL in active mode")
    if len(request_key) < 32:
        raise StrapiPrivacyConfigurationError("STRAPI_PRIVACY_REQUEST_SIGNING_KEY must contain at least 32 characters")
    if len(subject_key) < 32:
        raise StrapiPrivacyConfigurationError("STRAPI_PRIVACY_SUBJECT_HMAC_KEY must contain at least 32 characters")
    if not _KEY_ID_PATTERN.fullmatch(key_id):
        raise StrapiPrivacyConfigurationError("STRAPI_PRIVACY_REQUEST_KEY_ID must be an opaque identifier in active mode")
    load_receipt_public_key(str(getattr(settings, "STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY", "") or ""))


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise StrapiPrivacyRequestError("Receipt contains duplicate JSON keys")
        output[key] = value
    return output


def _parse_receipt_timestamp(value: Any) -> str:
    if not isinstance(value, str):
        raise StrapiPrivacyRequestError("Receipt completed_at is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StrapiPrivacyRequestError("Receipt completed_at is malformed") from exc
    if parsed.tzinfo is None:
        raise StrapiPrivacyRequestError("Receipt completed_at must include a timezone")
    return parsed.isoformat().replace("+00:00", "Z")


class StrapiPrivacyClient:
    """Perform one signed request and return only a verified receipt summary."""

    def __init__(self, settings: Any, *, transport: Any | None = None):
        if httpx is None:
            raise StrapiPrivacyConfigurationError("httpx is required for active Strapi privacy processing")
        validate_active_privacy_configuration(settings)
        self.base_url = str(settings.STRAPI_PRIVACY_URL).rstrip("/")
        self.request_key = str(settings.STRAPI_PRIVACY_REQUEST_SIGNING_KEY).encode("utf-8")
        self.request_key_id = str(settings.STRAPI_PRIVACY_REQUEST_KEY_ID)
        self.receipt_public_key = load_receipt_public_key(str(settings.STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY))
        self.timeout_seconds = max(1.0, float(getattr(settings, "STRAPI_PRIVACY_TIMEOUT_SECONDS", 10.0)))
        self._transport = transport

    @staticmethod
    def _request_payload(request: dict[str, Any]) -> dict[str, Any]:
        required = ("request_id", "idempotency_key", "brand_id", "subject_reference")
        if any(not request.get(field) for field in required):
            raise StrapiPrivacyRequestError("Outbox request is missing immutable correlation fields")
        if not _REQUEST_ID_PATTERN.fullmatch(str(request["request_id"])):
            raise StrapiPrivacyRequestError("Outbox request_id is malformed")
        if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(str(request["idempotency_key"])):
            raise StrapiPrivacyRequestError("Outbox idempotency_key is malformed")
        if not _SUBJECT_REFERENCE_PATTERN.fullmatch(str(request["subject_reference"])):
            raise StrapiPrivacyRequestError("Outbox subject_reference is malformed")
        return {
            "schema_version": STRAPI_PRIVACY_REQUEST_SCHEMA,
            "request_id": str(request["request_id"]),
            "idempotency_key": str(request["idempotency_key"]),
            "tenant_id": str(request["brand_id"]),
            "subject_reference": str(request["subject_reference"]),
        }

    @staticmethod
    def _request_signature_material(*, timestamp: str, request_id: str, idempotency_key: str, body: bytes) -> bytes:
        body_digest = hashlib.sha256(body).hexdigest()
        return "\n".join(
            (
                STRAPI_PRIVACY_REQUEST_SCHEMA,
                "POST",
                STRAPI_PRIVACY_DELETE_PATH,
                timestamp,
                request_id,
                idempotency_key,
                body_digest,
            )
        ).encode("utf-8")

    def _headers(self, *, payload: dict[str, Any], body: bytes) -> dict[str, str]:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        material = self._request_signature_material(
            timestamp=timestamp,
            request_id=payload["request_id"],
            idempotency_key=payload["idempotency_key"],
            body=body,
        )
        signature = hmac.new(self.request_key, material, hashlib.sha256).hexdigest()
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Strapi-Privacy-Schema": STRAPI_PRIVACY_REQUEST_SCHEMA,
            "X-Strapi-Privacy-Key-Id": self.request_key_id,
            "X-Strapi-Privacy-Request-Id": payload["request_id"],
            "X-Strapi-Privacy-Idempotency-Key": payload["idempotency_key"],
            "X-Strapi-Privacy-Timestamp": timestamp,
            "X-Strapi-Privacy-Signature": signature,
        }

    def _verified_receipt(self, raw: bytes, *, request: dict[str, Any]) -> dict[str, Any]:
        try:
            receipt = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_object_keys)
        except (UnicodeDecodeError, json.JSONDecodeError, StrapiPrivacyRequestError) as exc:
            raise StrapiPrivacyRequestError("Strapi privacy receipt is not valid JSON") from exc
        if not isinstance(receipt, dict):
            raise StrapiPrivacyRequestError("Strapi privacy receipt must be an object")
        if set(receipt) != _RECEIPT_SIGNED_FIELDS | {"signature"}:
            raise StrapiPrivacyRequestError("Strapi privacy receipt has an unexpected shape")
        if receipt.get("schema_version") != STRAPI_PRIVACY_RECEIPT_SCHEMA:
            raise StrapiPrivacyRequestError("Strapi privacy receipt schema is unsupported")
        if receipt.get("request_id") != request.get("request_id"):
            raise StrapiPrivacyRequestError("Strapi privacy receipt request_id does not match")
        if receipt.get("idempotency_key") != request.get("idempotency_key"):
            raise StrapiPrivacyRequestError("Strapi privacy receipt idempotency_key does not match")
        if receipt.get("tenant_id") != request.get("brand_id"):
            raise StrapiPrivacyRequestError("Strapi privacy receipt tenant does not match")
        if receipt.get("subject_reference") != request.get("subject_reference"):
            raise StrapiPrivacyRequestError("Strapi privacy receipt subject reference does not match")
        if receipt.get("status") != "completed" or receipt.get("deletion_verified") is not True:
            raise StrapiPrivacyRequestError("Strapi privacy receipt does not verify deletion")
        if not isinstance(receipt.get("receipt_id"), str) or not _OPAQUE_ID_PATTERN.fullmatch(receipt["receipt_id"]):
            raise StrapiPrivacyRequestError("Strapi privacy receipt_id is malformed")
        completed_at = _parse_receipt_timestamp(receipt.get("completed_at"))
        try:
            signature = _base64_decode(str(receipt.get("signature") or ""), field="receipt signature")
        except StrapiPrivacyConfigurationError as exc:
            raise StrapiPrivacyRequestError("Strapi privacy receipt signature is malformed") from exc
        signed = {field: receipt[field] for field in _RECEIPT_SIGNED_FIELDS}
        try:
            self.receipt_public_key.verify(signature, canonical_json(signed))
        except InvalidSignature as exc:
            raise StrapiPrivacyRequestError("Strapi privacy receipt signature is invalid") from exc
        return {
            "schema_version": STRAPI_PRIVACY_RECEIPT_SCHEMA,
            "receipt_id": receipt["receipt_id"],
            "completed_at": completed_at,
            "verified": True,
            "signature_fingerprint": hashlib.sha256(signature).hexdigest(),
        }

    async def request_deletion(self, request: dict[str, Any]) -> dict[str, Any]:
        """POST a signed, opaque deletion request and require a signed receipt."""
        payload = self._request_payload(request)
        body = canonical_json(payload)
        headers = self._headers(payload=payload, body=body)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self.base_url}{STRAPI_PRIVACY_DELETE_PATH}",
                    content=body,
                    headers=headers,
                )
                response.raise_for_status()
        except Exception as exc:
            if httpx is not None and isinstance(exc, httpx.HTTPError):
                raise StrapiPrivacyRequestError("Strapi privacy request was not acknowledged with a verified receipt") from exc
            raise
        return self._verified_receipt(response.content, request=request)
