"""Durable, tenant-scoped outbox for the Strapi privacy erasure contract.

This queue is deliberately separate from the legacy conversation-mirror
client.  A row has only opaque, tenant-bound subject references: never a raw
subject identifier, conversation id, message, content payload, or credential.
Lease tokens are worker credentials and are removed from all public reads.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import Settings
from app.connections import connection_manager

logger = structlog.get_logger(__name__)

STRAPI_PRIVACY_REQUESTS_COLLECTION = "strapi_privacy_requests"
STRAPI_PRIVACY_REQUEST_KIND = "strapi_subject_delete"
STRAPI_PRIVACY_QUEUE_VERSION = 1
STRAPI_PRIVACY_SUBJECT_REFERENCE_VERSION = "v1"
_SUBJECT_REFERENCE_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_REQUEST_ID_PATTERN = re.compile(r"^strapi_privacy_[a-f0-9]{32}$")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^spid_[a-f0-9]{64}$")


class StrapiPrivacyStoreError(RuntimeError):
    """The durable Strapi privacy outbox could not be safely used."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    point = value or _utc_now()
    if point.tzinfo is None:
        point = point.replace(tzinfo=timezone.utc)
    return point.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hmac_reference(secret: str, purpose: str, brand_id: str, subject_id: str) -> str:
    """Return a domain-separated opaque reference without persisting inputs."""
    if not isinstance(secret, str) or len(secret.strip()) < 32:
        raise ValueError("STRAPI_PRIVACY_SUBJECT_HMAC_KEY must contain at least 32 characters")
    if not brand_id or not subject_id:
        raise ValueError("Strapi privacy references require a tenant and subject")
    # Canonical JSON avoids delimiter-collision ambiguity if an upstream
    # identifier ever contains punctuation or a control character.
    payload = json.dumps(
        ["strapi-privacy", purpose, brand_id, subject_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def subject_reference(*, subject_id: str, brand_id: str, secret: str) -> str:
    """Create the tenant-bound reference sent to the external processor."""
    return _hmac_reference(secret, "subject-reference-" + STRAPI_PRIVACY_SUBJECT_REFERENCE_VERSION, brand_id, subject_id)


def idempotency_reference(*, subject_id: str, brand_id: str, secret: str) -> str:
    """Create a separate immutable idempotency reference for one subject scope."""
    return "spid_" + _hmac_reference(secret, "idempotency-" + STRAPI_PRIVACY_SUBJECT_REFERENCE_VERSION, brand_id, subject_id)


class StrapiPrivacyStore:
    """Create and lease-fence Strapi deletion requests in the system database."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._indexes_checked = False

    def _collection(self):
        try:
            return connection_manager.get_system_db()[STRAPI_PRIVACY_REQUESTS_COLLECTION]
        except (RuntimeError, AttributeError, KeyError, TypeError) as exc:
            raise StrapiPrivacyStoreError("Strapi privacy storage is unavailable") from exc

    async def _ensure_indexes(self, collection: Any) -> None:
        if self._indexes_checked:
            return
        self._indexes_checked = True
        try:
            await collection.create_index(
                [("kind", 1), ("status", 1), ("next_attempt_at", 1)],
                name="strapi_privacy_claim_idx",
            )
            await collection.create_index(
                [("kind", 1), ("lease_expires_at", 1)],
                name="strapi_privacy_lease_idx",
            )
            # This immutable key prevents one subject within one tenant from
            # receiving a new remote deletion identifier on a retry/replay.
            await collection.create_index(
                "operation_key",
                unique=True,
                name="strapi_privacy_operation_idx",
            )
            await collection.create_index(
                "request_id",
                unique=True,
                name="strapi_privacy_request_id_idx",
            )
        except Exception as exc:
            # Index creation races are harmless; Mongo writes below remain the
            # source of truth and fail closed if the collection is unavailable.
            logger.warning("strapi_privacy_index_setup_failed", error_type=type(exc).__name__)

    @staticmethod
    def _without_internal_fields(document: dict[str, Any] | None) -> dict[str, Any] | None:
        if not document:
            return None
        result = dict(document)
        result.pop("_id", None)
        result.pop("lease_token", None)
        result.pop("lease_owner", None)
        result.pop("lease_expires_at", None)
        return result

    @staticmethod
    def _mode(settings: Settings) -> str:
        return str(getattr(settings, "STRAPI_PRIVACY_MODE", "contract_pending") or "contract_pending").strip().lower()

    @staticmethod
    def _initial_status(mode: str) -> tuple[str, str]:
        if mode == "active":
            return "queued", "queued"
        if mode == "disabled":
            return "disabled", "disabled"
        return "pending_contract", "pending_contract"

    async def create_or_get_deletion_request(
        self,
        *,
        brand_id: str,
        brand_slug: str,
        subject_reference: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        """Persist one immutable external deletion operation or return it.

        ``created`` is false for an idempotent reuse.  Callers supply only
        opaque references; this function intentionally has no ``subject_id``
        argument so raw identifiers cannot enter the outbox accidentally.
        """
        if not brand_id or not brand_slug:
            raise ValueError("Strapi privacy deletion requires immutable tenant scope")
        if not _SUBJECT_REFERENCE_PATTERN.fullmatch(str(subject_reference or "")):
            raise ValueError("Invalid Strapi privacy subject reference")
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            raise ValueError("Invalid Strapi privacy idempotency key")

        collection = self._collection()
        await self._ensure_indexes(collection)
        now = _utc_now()
        mode = self._mode(self.settings)
        status, phase = self._initial_status(mode)
        request_id = f"strapi_privacy_{uuid.uuid4().hex}"
        operation_key = f"{brand_id}:{subject_reference}"
        document: dict[str, Any] = {
            "_id": request_id,
            "request_id": request_id,
            "queue_version": STRAPI_PRIVACY_QUEUE_VERSION,
            "kind": STRAPI_PRIVACY_REQUEST_KIND,
            "brand_id": brand_id,
            "brand_slug": brand_slug,
            "subject_reference": subject_reference,
            "idempotency_key": idempotency_key,
            "operation_key": operation_key,
            "mode_at_creation": mode,
            "status": status,
            "phase": phase,
            "attempt_count": 0,
            "next_attempt_at": now,
            "created_at": _timestamp(now),
            "updated_at": _timestamp(now),
            "last_error_code": None,
            "last_error_type": None,
            "receipt_verified": False,
        }
        try:
            await collection.insert_one(document)
            return self._without_internal_fields(document) or {}, True
        except DuplicateKeyError:
            pass
        except Exception as exc:
            raise StrapiPrivacyStoreError("Strapi privacy storage is unavailable") from exc

        try:
            existing = await collection.find_one({"operation_key": operation_key, "kind": STRAPI_PRIVACY_REQUEST_KIND})
        except Exception as exc:
            raise StrapiPrivacyStoreError("Strapi privacy storage is unavailable") from exc
        if not existing:
            raise StrapiPrivacyStoreError("Could not resolve concurrent Strapi privacy operation")
        return self._without_internal_fields(existing) or {}, False

    async def get_by_operation(
        self,
        *,
        brand_id: str,
        subject_reference: str,
    ) -> dict[str, Any] | None:
        if not brand_id or not _SUBJECT_REFERENCE_PATTERN.fullmatch(str(subject_reference or "")):
            return None
        try:
            result = await self._collection().find_one(
                {
                    "kind": STRAPI_PRIVACY_REQUEST_KIND,
                    "operation_key": f"{brand_id}:{subject_reference}",
                }
            )
        except Exception as exc:
            raise StrapiPrivacyStoreError("Strapi privacy storage is unavailable") from exc
        return self._without_internal_fields(result)

    async def claim_next(self, *, worker_id: str) -> dict[str, Any] | None:
        """Lease one active-contract request, reclaiming expired worker leases."""
        if self._mode(self.settings) != "active":
            return None
        collection = self._collection()
        await self._ensure_indexes(collection)
        now = _utc_now()
        lease_seconds = max(15, int(getattr(self.settings, "STRAPI_PRIVACY_LEASE_SECONDS", 120)))
        lease_token = f"{worker_id}:{uuid.uuid4().hex}"
        query = {
            "kind": STRAPI_PRIVACY_REQUEST_KIND,
            "$or": [
                {
                    "status": {"$in": ["queued", "pending_contract"]},
                    "next_attempt_at": {"$lte": now},
                },
                {"status": "running", "lease_expires_at": {"$lte": now}},
            ],
        }
        update = {
            "$set": {
                "status": "running",
                "phase": "sending",
                "lease_token": lease_token,
                "lease_owner": worker_id,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "updated_at": _timestamp(now),
            },
            "$inc": {"attempt_count": 1},
        }
        try:
            result = await collection.find_one_and_update(
                query,
                update,
                sort=[("next_attempt_at", 1), ("created_at", 1)],
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            raise StrapiPrivacyStoreError("Strapi privacy storage is unavailable") from exc
        if not result:
            return None
        claimed = dict(result)
        claimed.pop("_id", None)
        return claimed

    async def renew_lease(self, request: dict[str, Any]) -> bool:
        now = _utc_now()
        lease_seconds = max(15, int(getattr(self.settings, "STRAPI_PRIVACY_LEASE_SECONDS", 120)))
        try:
            result = await self._collection().update_one(
                {
                    "_id": request.get("request_id"),
                    "kind": STRAPI_PRIVACY_REQUEST_KIND,
                    "status": "running",
                    "lease_token": request.get("lease_token"),
                },
                {
                    "$set": {
                        "lease_expires_at": now + timedelta(seconds=lease_seconds),
                        "updated_at": _timestamp(now),
                    }
                },
            )
        except Exception as exc:
            raise StrapiPrivacyStoreError("Strapi privacy storage is unavailable") from exc
        return bool(getattr(result, "matched_count", 0))

    async def complete(self, request: dict[str, Any], *, receipt: dict[str, Any]) -> bool:
        """Persist only a client-validated, correlated remote receipt."""
        required = {"receipt_id", "completed_at", "signature_fingerprint", "schema_version"}
        if not required.issubset(receipt) or receipt.get("verified") is not True:
            raise ValueError("Refusing to persist an unverified Strapi privacy receipt")
        now = _utc_now()
        try:
            result = await self._collection().update_one(
                {
                    "_id": request.get("request_id"),
                    "kind": STRAPI_PRIVACY_REQUEST_KIND,
                    "status": "running",
                    "lease_token": request.get("lease_token"),
                },
                {
                    "$set": {
                        "status": "completed",
                        "phase": "receipt_verified",
                        "receipt_verified": True,
                        "external_receipt": dict(receipt),
                        "completed_at": _timestamp(now),
                        "updated_at": _timestamp(now),
                    },
                    "$unset": {"lease_token": "", "lease_owner": "", "lease_expires_at": ""},
                },
            )
        except Exception as exc:
            raise StrapiPrivacyStoreError("Strapi privacy storage is unavailable") from exc
        return bool(getattr(result, "matched_count", 0))

    async def retry_or_fail(
        self,
        request: dict[str, Any],
        *,
        error_code: str,
        error_type: str,
    ) -> bool:
        """Release a fenced lease and schedule a bounded retry."""
        now = _utc_now()
        attempts = int(request.get("attempt_count") or 1)
        max_attempts = max(1, int(getattr(self.settings, "STRAPI_PRIVACY_MAX_ATTEMPTS", 8)))
        delay = max(1, int(getattr(self.settings, "STRAPI_PRIVACY_RETRY_DELAY_SECONDS", 60)))
        query = {
            "_id": request.get("request_id"),
            "kind": STRAPI_PRIVACY_REQUEST_KIND,
            "status": "running",
            "lease_token": request.get("lease_token"),
        }
        if attempts < max_attempts:
            update = {
                "$set": {
                    "status": "queued",
                    "phase": "retry_scheduled",
                    "next_attempt_at": now + timedelta(seconds=delay),
                    "last_error_code": error_code,
                    "last_error_type": error_type,
                    "updated_at": _timestamp(now),
                },
                "$unset": {"lease_token": "", "lease_owner": "", "lease_expires_at": ""},
            }
        else:
            update = {
                "$set": {
                    "status": "failed",
                    "phase": "retry_exhausted",
                    "last_error_code": error_code,
                    "last_error_type": error_type,
                    "updated_at": _timestamp(now),
                    "failed_at": _timestamp(now),
                },
                "$unset": {"lease_token": "", "lease_owner": "", "lease_expires_at": ""},
            }
        try:
            result = await self._collection().update_one(query, update)
        except Exception as exc:
            raise StrapiPrivacyStoreError("Strapi privacy storage is unavailable") from exc
        return bool(getattr(result, "matched_count", 0))
