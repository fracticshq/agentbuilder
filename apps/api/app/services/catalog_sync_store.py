"""Mongo-authoritative queue for Shopify catalog lifecycle work.

Catalog synchronisation is an external, potentially long-running operation.
This store deliberately keeps its state separate from document-ingestion jobs:
it holds no plaintext Shopify credential, is lease-fenced for multiple workers,
and coalesces a brand's overlapping sync requests instead of allowing concurrent
snapshots to mark each other's products stale.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import structlog
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import Settings
from app.connections import connection_manager

logger = structlog.get_logger(__name__)

CATALOG_SYNC_COLLECTION = "catalog_sync_jobs"
CATALOG_SYNC_KIND = "shopify_catalog_sync"
CATALOG_SYNC_VERSION = 1
TERMINAL_STATUSES = {"completed", "error", "cancelled"}
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class CatalogSyncStoreUnavailableError(RuntimeError):
    """Raised when the Mongo source of truth is unavailable."""


class CatalogSyncStore:
    """Create and claim tenant-scoped Shopify sync jobs."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._indexes_checked = False

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _timestamp(cls, value: datetime | None = None) -> str:
        point = value or cls._now()
        if point.tzinfo is None:
            point = point.replace(tzinfo=timezone.utc)
        return point.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _validate_job_id(job_id: str) -> str:
        if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
            raise ValueError("Invalid catalog sync job identifier")
        return job_id

    def _collection(self):
        try:
            return connection_manager.get_system_db()[CATALOG_SYNC_COLLECTION]
        except (RuntimeError, AttributeError, KeyError, TypeError) as exc:
            raise CatalogSyncStoreUnavailableError("Catalog sync storage is unavailable") from exc

    async def _ensure_indexes(self, collection: Any) -> None:
        if self._indexes_checked:
            return
        self._indexes_checked = True
        try:
            await collection.create_index("expires_at", expireAfterSeconds=0, name="catalog_sync_expiry_idx")
            await collection.create_index(
                [("kind", 1), ("status", 1), ("next_attempt_at", 1)],
                name="catalog_sync_claim_idx",
            )
            await collection.create_index(
                [("kind", 1), ("lease_expires_at", 1)], name="catalog_sync_lease_idx"
            )
            # Exactly one active full snapshot is allowed per brand. A webhook
            # that arrives during a manual sync returns that existing job.
            await collection.create_index(
                "active_key",
                unique=True,
                partialFilterExpression={"active_key": {"$type": "string"}},
                name="catalog_sync_one_active_snapshot_idx",
            )
            await collection.create_index(
                "idempotency_key",
                unique=True,
                partialFilterExpression={"idempotency_key": {"$type": "string"}},
                name="catalog_sync_idempotency_idx",
            )
        except Exception as exc:
            logger.warning("catalog_sync_index_setup_failed", error_type=type(exc).__name__)

    @staticmethod
    def _without_internal_fields(document: Dict[str, Any] | None) -> Optional[Dict[str, Any]]:
        if not document:
            return None
        copy = dict(document)
        copy.pop("_id", None)
        copy.pop("lease_token", None)
        return copy

    async def enqueue_sync(
        self,
        *,
        job_id: str,
        brand_id: str,
        brand_slug: str,
        source_url: str,
        access_token_encrypted: str | None,
        fallback_currency: str | None,
        trigger: str,
        idempotency_key: str | None = None,
        webhook_topic: str | None = None,
        webhook_id: str | None = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """Queue a snapshot or return the already-active/idempotent job.

        The boolean is true if no new unit of work was created.  The encrypted
        token is a snapshot so a later dashboard credential update cannot make
        a queued job silently run with different authority.
        """
        job_id = self._validate_job_id(job_id)
        if not brand_id or not brand_slug or not source_url:
            raise ValueError("Catalog sync job requires immutable brand and source scope")

        collection = self._collection()
        await self._ensure_indexes(collection)
        now = self._now()
        active_key = f"shopify:{brand_id}"
        document: Dict[str, Any] = {
            "_id": job_id,
            "job_id": job_id,
            "queue_version": CATALOG_SYNC_VERSION,
            "kind": CATALOG_SYNC_KIND,
            "action": "sync",
            "status": "queued",
            "phase": "queued",
            "brand_id": brand_id,
            "brand_slug": brand_slug,
            "source_url": source_url,
            "access_token_encrypted": access_token_encrypted or "",
            "fallback_currency": fallback_currency,
            "trigger": trigger,
            "webhook_topic": webhook_topic,
            "webhook_id": webhook_id,
            "idempotency_key": idempotency_key,
            "active_key": active_key,
            "attempt_count": 0,
            "created_at": self._timestamp(now),
            "updated_at": self._timestamp(now),
            "next_attempt_at": now,
            "expires_at": now + timedelta(seconds=max(60, int(self.settings.CATALOG_SYNC_JOB_TTL_SECONDS))),
            "error": None,
        }
        try:
            await collection.insert_one(document)
            return self._without_internal_fields(document) or {}, False
        except DuplicateKeyError:
            existing = None
            if idempotency_key:
                existing = await collection.find_one({"idempotency_key": idempotency_key})
            if existing is None:
                existing = await collection.find_one({"active_key": active_key})
            if existing is None:
                raise CatalogSyncStoreUnavailableError("Could not resolve concurrent catalog sync")
            return self._without_internal_fields(existing) or {}, True
        except Exception as exc:
            logger.warning("catalog_sync_enqueue_failed", brand_id=brand_id, error_type=type(exc).__name__)
            raise CatalogSyncStoreUnavailableError("Catalog sync storage is unavailable") from exc

    async def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        try:
            job_id = self._validate_job_id(job_id)
        except ValueError:
            return None
        try:
            result = await self._collection().find_one({"_id": job_id, "kind": CATALOG_SYNC_KIND})
        except Exception as exc:
            raise CatalogSyncStoreUnavailableError("Catalog sync storage is unavailable") from exc
        return self._without_internal_fields(result)

    async def enqueue_lifecycle_action(
        self,
        *,
        job_id: str,
        brand_id: str,
        brand_slug: str,
        source_url: str,
        action: str,
        trigger: str,
        product_id: str | None = None,
        idempotency_key: str | None = None,
        webhook_topic: str | None = None,
        webhook_id: str | None = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """Queue a product/source deactivation produced by a signed webhook."""
        job_id = self._validate_job_id(job_id)
        if action not in {"deactivate_product", "deactivate_source"}:
            raise ValueError("Invalid Shopify catalog lifecycle action")
        if action == "deactivate_product" and not product_id:
            raise ValueError("Product deactivation requires a Shopify product id")
        collection = self._collection()
        await self._ensure_indexes(collection)
        now = self._now()
        active_key = f"shopify:{brand_id}:{action}:{product_id or 'all'}"
        document: Dict[str, Any] = {
            "_id": job_id,
            "job_id": job_id,
            "queue_version": CATALOG_SYNC_VERSION,
            "kind": CATALOG_SYNC_KIND,
            "action": action,
            "status": "queued",
            "phase": "queued",
            "brand_id": brand_id,
            "brand_slug": brand_slug,
            "source_url": source_url,
            "product_id": product_id,
            "trigger": trigger,
            "webhook_topic": webhook_topic,
            "webhook_id": webhook_id,
            "idempotency_key": idempotency_key,
            "active_key": active_key,
            "attempt_count": 0,
            "created_at": self._timestamp(now),
            "updated_at": self._timestamp(now),
            "next_attempt_at": now,
            "expires_at": now + timedelta(seconds=max(60, int(self.settings.CATALOG_SYNC_JOB_TTL_SECONDS))),
            "error": None,
        }
        try:
            await collection.insert_one(document)
            return self._without_internal_fields(document) or {}, False
        except DuplicateKeyError:
            existing = None
            if idempotency_key:
                existing = await collection.find_one({"idempotency_key": idempotency_key})
            if existing is None:
                existing = await collection.find_one({"active_key": active_key})
            if existing is None:
                raise CatalogSyncStoreUnavailableError("Could not resolve concurrent catalog lifecycle action")
            return self._without_internal_fields(existing) or {}, True
        except Exception as exc:
            logger.warning("catalog_lifecycle_enqueue_failed", brand_id=brand_id, error_type=type(exc).__name__)
            raise CatalogSyncStoreUnavailableError("Catalog sync storage is unavailable") from exc

    async def claim_next(self, *, worker_id: str) -> Optional[Dict[str, Any]]:
        collection = self._collection()
        await self._ensure_indexes(collection)
        now = self._now()
        lease_expires_at = now + timedelta(seconds=max(30, int(self.settings.CATALOG_SYNC_LEASE_SECONDS)))
        lease_token = f"{worker_id}:{uuid.uuid4().hex}"
        query = {
            "kind": CATALOG_SYNC_KIND,
            "$or": [
                {"status": "queued", "next_attempt_at": {"$lte": now}},
                {"status": "running", "lease_expires_at": {"$lte": now}},
            ],
        }
        update = {
            "$set": {
                "status": "running",
                "phase": "executing",
                "lease_token": lease_token,
                "lease_owner": worker_id,
                "lease_expires_at": lease_expires_at,
                "updated_at": self._timestamp(now),
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
            raise CatalogSyncStoreUnavailableError("Catalog sync storage is unavailable") from exc
        if not result:
            return None
        # This object is worker-private. Keep the lease token so terminal state
        # transitions are fenced; public reads always use ``get`` above, which
        # removes it.
        claimed = dict(result)
        claimed.pop("_id", None)
        return claimed

    async def cancel_queued(self, job_id: str, *, reason: str) -> bool:
        """Cancel an unclaimed queue row when its compatibility progress row fails."""
        job_id = self._validate_job_id(job_id)
        try:
            result = await self._collection().update_one(
                {"_id": job_id, "kind": CATALOG_SYNC_KIND, "status": "queued"},
                {
                    "$set": {
                        "status": "cancelled",
                        "phase": "cancelled",
                        "error": reason,
                        "completed_at": self._timestamp(),
                        "updated_at": self._timestamp(),
                    },
                    "$unset": {"active_key": ""},
                },
            )
        except Exception as exc:
            raise CatalogSyncStoreUnavailableError("Catalog sync storage is unavailable") from exc
        return bool(getattr(result, "matched_count", 0))

    async def renew_lease(self, job: Dict[str, Any]) -> bool:
        """Extend a claimed sync lease without changing its execution fence.

        GraphQL cursor traversal can outlive the short initial lease. A worker
        that has been reclaimed cannot renew or complete the job because every
        transition remains bound to the original opaque lease token.
        """
        now = self._now()
        lease_expires_at = now + timedelta(seconds=max(30, int(self.settings.CATALOG_SYNC_LEASE_SECONDS)))
        query = {
            "_id": job.get("job_id"),
            "kind": CATALOG_SYNC_KIND,
            "status": "running",
            "lease_token": job.get("lease_token"),
        }
        try:
            result = await self._collection().update_one(
                query,
                {
                    "$set": {
                        "lease_expires_at": lease_expires_at,
                        "updated_at": self._timestamp(now),
                    }
                },
            )
        except Exception as exc:
            raise CatalogSyncStoreUnavailableError("Catalog sync storage is unavailable") from exc
        return bool(getattr(result, "matched_count", 0))

    async def complete(self, job: Dict[str, Any], updates: Dict[str, Any]) -> bool:
        return await self._transition_terminal(job, "completed", {"phase": "completed", **updates})

    async def fail(self, job: Dict[str, Any], *, error_code: str, error_type: str) -> bool:
        attempts = int(job.get("attempt_count") or 1)
        max_attempts = max(1, int(self.settings.CATALOG_SYNC_MAX_ATTEMPTS))
        now = self._now()
        collection = self._collection()
        query = {"_id": job.get("job_id"), "kind": CATALOG_SYNC_KIND, "lease_token": job.get("lease_token")}
        if attempts < max_attempts:
            update = {
                "$set": {
                    "status": "queued",
                    "phase": "retry_scheduled",
                    "error": error_code,
                    "error_type": error_type,
                    "next_attempt_at": now + timedelta(seconds=max(1, int(self.settings.CATALOG_SYNC_RETRY_DELAY_SECONDS))),
                    "updated_at": self._timestamp(now),
                },
                "$unset": {"lease_token": "", "lease_owner": "", "lease_expires_at": ""},
            }
        else:
            update = {
                "$set": {
                    "status": "error",
                    "phase": "failed",
                    "error": error_code,
                    "error_type": error_type,
                    "completed_at": self._timestamp(now),
                    "updated_at": self._timestamp(now),
                },
                "$unset": {"lease_token": "", "lease_owner": "", "lease_expires_at": "", "active_key": ""},
            }
        try:
            result = await collection.update_one(query, update)
        except Exception as exc:
            raise CatalogSyncStoreUnavailableError("Catalog sync storage is unavailable") from exc
        return bool(getattr(result, "matched_count", 0))

    async def _transition_terminal(self, job: Dict[str, Any], status: str, updates: Dict[str, Any]) -> bool:
        if status not in TERMINAL_STATUSES:
            raise ValueError("Invalid terminal catalog sync status")
        now = self._now()
        query = {"_id": job.get("job_id"), "kind": CATALOG_SYNC_KIND, "lease_token": job.get("lease_token")}
        update = {
            "$set": {
                "status": status,
                "completed_at": self._timestamp(now),
                "updated_at": self._timestamp(now),
                **updates,
            },
            "$unset": {"lease_token": "", "lease_owner": "", "lease_expires_at": "", "active_key": ""},
        }
        try:
            result = await self._collection().update_one(query, update)
        except Exception as exc:
            raise CatalogSyncStoreUnavailableError("Catalog sync storage is unavailable") from exc
        return bool(getattr(result, "matched_count", 0))
