"""Mongo-authoritative state transitions for ingestion jobs.

Redis is intentionally only a best-effort read cache for old callers.  Every
durable ingestion transition (claim, lease renewal, cancellation and terminal
state) is fenced by MongoDB.  In particular, a Redis value can never cause a
worker to claim a job or a tenant authorization decision to succeed.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import structlog
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..connections import connection_manager

logger = structlog.get_logger(__name__)

JOB_TTL_SECONDS = 86400  # compatibility default for legacy jobs
KEY_PREFIX = "job:"
JOBS_COLLECTION = "ingestion_jobs"
DURABLE_JOB_VERSION = 2
DURABLE_JOB_KIND = "document_ingestion"
DURABLE_REINDEX_KIND = "knowledge_reindex"
DURABLE_JOB_KINDS = (DURABLE_JOB_KIND, DURABLE_REINDEX_KIND)
TERMINAL_STATUSES = {"completed", "error", "cancelled"}
CLAIMABLE_STATUSES = {"queued", "running", "publishing"}
_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TIMESTAMP_FIELDS = {
    "created_at",
    "updated_at",
    "completed_at",
    "cancelled_at",
    "lease_expires_at",
    "next_attempt_at",
    "publish_started_at",
}
_IMMUTABLE_FIELDS = {"agent_id", "brand_id", "brand_slug", "snapshot"}


class JobStoreUnavailableError(RuntimeError):
    """Raised when the MongoDB source of truth cannot be reached."""


class DuplicateDurableJobError(RuntimeError):
    """A concurrent submission already owns a durable idempotency key."""


class JobStore:
    """Persist jobs and perform fenced durable-worker transitions."""

    def __init__(self, *, job_ttl_seconds: int = JOB_TTL_SECONDS):
        self._fallback: Dict[str, Dict[str, Any]] = {}
        self._indexes_checked = False
        self.job_ttl_seconds = max(60, int(job_ttl_seconds))

    def _key(self, job_id: str) -> str:
        return f"{KEY_PREFIX}{job_id}"

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _utc_timestamp(cls, value: datetime | None = None) -> str:
        timestamp = value or cls._utc_now()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @classmethod
    def _normalize_timestamp(cls, value: Any, default: str) -> str:
        if isinstance(value, datetime):
            return cls._utc_timestamp(value)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return default
            return cls._utc_timestamp(parsed)
        return default

    @staticmethod
    def _validate_job_id(job_id: str) -> str:
        if not isinstance(job_id, str) or not _JOB_ID_PATTERN.fullmatch(job_id):
            raise ValueError("Invalid job identifier")
        return job_id

    def _get_collection(self):
        try:
            return connection_manager.get_system_db()[JOBS_COLLECTION]
        except (RuntimeError, AttributeError, KeyError, TypeError):
            return None

    async def _ensure_indexes(self, collection: Any) -> None:
        if self._indexes_checked:
            return
        self._indexes_checked = True
        try:
            await collection.create_index(
                "expires_at", expireAfterSeconds=0, name="ingestion_jobs_expiry_idx"
            )
            await collection.create_index(
                [("queue_version", 1), ("kind", 1), ("status", 1), ("next_attempt_at", 1)],
                name="ingestion_jobs_claim_idx",
            )
            await collection.create_index(
                [("queue_version", 1), ("kind", 1), ("lease_expires_at", 1)],
                name="ingestion_jobs_lease_idx",
            )
            await collection.create_index(
                [("queue_version", 1), ("kind", 1), ("brand_id", 1), ("agent_id", 1), ("idempotency_key", 1)],
                unique=True,
                partialFilterExpression={"idempotency_key": {"$type": "string"}},
                name="ingestion_jobs_idempotency_idx",
            )
        except Exception as exc:
            # A concurrent worker may create the same index. The actual job
            # operation below remains authoritative and reports Mongo failure.
            logger.warning("job_store_index_setup_failed", error_type=type(exc).__name__)

    @classmethod
    def _document_for_cache(cls, job_id: str, document: Dict[str, Any]) -> Dict[str, Any]:
        cached = dict(document)
        cached.pop("_id", None)
        # Leases are worker credentials and must not be persisted in cache.
        cached.pop("lease_token", None)
        cached["job_id"] = job_id
        for field in _TIMESTAMP_FIELDS | {"expires_at"}:
            value = cached.get(field)
            if isinstance(value, datetime):
                cached[field] = cls._utc_timestamp(value)
        return cached

    @classmethod
    def _cache_ttl(cls, document: Dict[str, Any]) -> int:
        expires_at = document.get("expires_at")
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                expires_at = None
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            return max(1, int((expires_at - cls._utc_now()).total_seconds()))
        return JOB_TTL_SECONDS

    async def _cache_set(self, job_id: str, document: Dict[str, Any]) -> bool:
        redis = connection_manager.redis_client
        if redis is None:
            return False
        try:
            cached = self._document_for_cache(job_id, document)
            await redis.set(self._key(job_id), json.dumps(cached, default=str), ex=self._cache_ttl(document))
            return True
        except Exception as exc:
            logger.warning("job_store_redis_write_failed", job_id=job_id, error_type=type(exc).__name__)
            return False

    async def _cache_get(self, job_id: str) -> tuple[Optional[Dict[str, Any]], bool]:
        redis = connection_manager.redis_client
        if redis is None:
            return None, False
        try:
            raw = await redis.get(self._key(job_id))
            if not raw:
                return None, True
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise ValueError("Cached job value is not an object")
            return self._document_for_cache(job_id, document), True
        except Exception as exc:
            logger.warning("job_store_redis_read_failed", job_id=job_id, error_type=type(exc).__name__)
            return None, False

    async def _cache_delete(self, job_id: str) -> bool:
        redis = connection_manager.redis_client
        if redis is None:
            return False
        try:
            await redis.delete(self._key(job_id))
            return True
        except Exception as exc:
            logger.warning("job_store_redis_delete_failed", job_id=job_id, error_type=type(exc).__name__)
            return False

    async def _read_db_document(self, collection: Any, job_id: str) -> Optional[Dict[str, Any]]:
        try:
            document = await collection.find_one({"_id": job_id})
        except Exception as exc:
            logger.warning("job_store_mongodb_read_failed", job_id=job_id, error_type=type(exc).__name__)
            raise JobStoreUnavailableError("Durable job storage is unavailable") from exc
        return self._document_for_cache(job_id, document) if document else None

    async def _cache_document(self, job_id: str, document: Optional[Dict[str, Any]]) -> None:
        if document is None:
            await self._cache_delete(job_id)
            return
        if not await self._cache_set(job_id, document):
            await self._cache_delete(job_id)

    def _write_payload(self, job_id: str, data: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        now = self._utc_timestamp()
        payload = dict(data)
        payload.pop("_id", None)
        payload.pop("job_id", None)
        payload.pop("expires_at", None)
        created_at = self._normalize_timestamp(payload.pop("created_at", None), now)
        for field in _TIMESTAMP_FIELDS - {"created_at", "updated_at"}:
            if field in payload and payload[field] is not None:
                payload[field] = self._normalize_timestamp(payload[field], now)
        payload["job_id"] = job_id
        payload["updated_at"] = now
        return payload, {
            "created_at": created_at,
            "expires_at": self._utc_now() + timedelta(seconds=self.job_ttl_seconds),
        }

    async def set(self, job_id: str, data: Dict[str, Any]) -> None:
        """Legacy-compatible create/merge. Durable workers do not use this."""
        job_id = self._validate_job_id(job_id)
        payload, insert_fields = self._write_payload(job_id, data)
        for field in _IMMUTABLE_FIELDS:
            if field in payload:
                insert_fields[field] = payload.pop(field)
        collection = self._get_collection()
        if collection is not None:
            await self._ensure_indexes(collection)
            try:
                await collection.update_one(
                    {"_id": job_id}, {"$set": payload, "$setOnInsert": insert_fields}, upsert=True
                )
                document = await self._read_db_document(collection, job_id)
            except JobStoreUnavailableError:
                raise
            except Exception as exc:
                logger.warning("job_store_mongodb_write_failed", job_id=job_id, error_type=type(exc).__name__)
                raise JobStoreUnavailableError("Durable job storage is unavailable") from exc
            await self._cache_document(job_id, document)
            self._fallback.pop(job_id, None)
            return
        fallback_document = dict(insert_fields)
        fallback_document.update(payload)
        if not await self._cache_set(job_id, fallback_document):
            self._fallback[job_id] = fallback_document

    async def create_durable_job(
        self,
        job_id: str,
        data: Dict[str, Any],
        *,
        kind: str = DURABLE_JOB_KIND,
    ) -> None:
        """Insert a v2 job after its encrypted payloads have been stored.

        This intentionally requires MongoDB. A process-local/Redis fallback is
        acceptable only for legacy development callers, never for uploads that
        a separate worker must recover after a restart.
        """
        job_id = self._validate_job_id(job_id)
        if kind not in DURABLE_JOB_KINDS:
            raise ValueError("Unsupported durable job kind")
        collection = self._get_collection()
        if collection is None:
            raise JobStoreUnavailableError("Durable job storage is unavailable")
        await self._ensure_indexes(collection)
        now = self._utc_now()
        protected_fields = {"_id", "job_id", "queue_version", "kind", "status", "phase", "lease_token", "lease_expires_at"}
        if protected_fields.intersection(data):
            raise ValueError("Durable job metadata contains protected fields")
        document = {
            "_id": job_id,
            "job_id": job_id,
            "queue_version": DURABLE_JOB_VERSION,
            "kind": kind,
            "status": "queued",
            "phase": "staging",
            "processed_count": 0,
            "attempt_count": 0,
            "created_at": self._utc_timestamp(now),
            "updated_at": self._utc_timestamp(now),
            "next_attempt_at": now,
            "expires_at": now + timedelta(seconds=self.job_ttl_seconds),
            "error": None,
            **dict(data),
        }
        # The caller may not smuggle source bytes into the job document.
        if "content" in document or "files" in document:
            raise ValueError("Durable jobs store payload references, not source content")
        try:
            await collection.insert_one(document)
        except DuplicateKeyError as exc:
            raise DuplicateDurableJobError("A durable job already owns this idempotency key") from exc
        except Exception as exc:
            logger.warning("durable_job_create_failed", job_id=job_id, error_type=type(exc).__name__)
            raise JobStoreUnavailableError("Durable job storage is unavailable") from exc
        await self._cache_document(job_id, document)

    async def find_durable_job_by_idempotency(
        self,
        *,
        agent_id: str | None,
        brand_id: str,
        idempotency_key: str,
        kind: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Find a v2 job by its tenant-scoped idempotency key in Mongo."""
        collection = self._get_collection()
        if collection is None:
            raise JobStoreUnavailableError("Durable job storage is unavailable")
        try:
            document = await collection.find_one(
                {
                    "queue_version": DURABLE_JOB_VERSION,
                    "kind": kind if kind in DURABLE_JOB_KINDS else {"$in": list(DURABLE_JOB_KINDS)},
                    "agent_id": agent_id,
                    "brand_id": brand_id,
                    "idempotency_key": idempotency_key,
                }
            )
        except Exception as exc:
            logger.warning("durable_job_idempotency_read_failed", error_type=type(exc).__name__)
            raise JobStoreUnavailableError("Durable job storage is unavailable") from exc
        if not document:
            return None
        job_id = str(document.get("_id") or "")
        if not job_id:
            raise JobStoreUnavailableError("Durable job storage returned an invalid job")
        cached = self._document_for_cache(job_id, document)
        await self._cache_document(job_id, cached)
        return cached

    async def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Read Mongo first whenever available; Redis is never authoritative."""
        try:
            job_id = self._validate_job_id(job_id)
        except ValueError:
            return None
        collection = self._get_collection()
        if collection is not None:
            document = await self._read_db_document(collection, job_id)
            await self._cache_document(job_id, document)
            if document:
                self._fallback.pop(job_id, None)
            return document
        cached, redis_available = await self._cache_get(job_id)
        if cached is not None:
            return cached
        if redis_available:
            return None
        fallback = self._fallback.get(job_id)
        return self._document_for_cache(job_id, fallback) if fallback else None

    async def update(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """Legacy-compatible update. Fenced methods protect durable jobs."""
        try:
            job_id = self._validate_job_id(job_id)
        except ValueError:
            return False
        payload, _ = self._write_payload(job_id, updates)
        for field in _IMMUTABLE_FIELDS:
            payload.pop(field, None)
        collection = self._get_collection()
        if collection is not None:
            try:
                result = await collection.update_one({"_id": job_id}, {"$set": payload})
            except Exception as exc:
                logger.warning("job_store_mongodb_update_failed", job_id=job_id, error_type=type(exc).__name__)
                raise JobStoreUnavailableError("Durable job storage is unavailable") from exc
            if getattr(result, "matched_count", 1) == 0:
                await self._cache_delete(job_id)
                return False
            document = await self._read_db_document(collection, job_id)
            await self._cache_document(job_id, document)
            self._fallback.pop(job_id, None)
            return document is not None
        cached, redis_available = await self._cache_get(job_id)
        if cached is not None:
            cached.update(payload)
            await self._cache_set(job_id, cached)
            return True
        if redis_available:
            return False
        fallback = self._fallback.get(job_id)
        if fallback is None:
            return False
        fallback.update(payload)
        return True

    async def claim_next(self, *, worker_id: str, lease_seconds: int) -> Optional[Dict[str, Any]]:
        """Atomically claim queued work or reclaim an expired durable lease."""
        collection = self._get_collection()
        if collection is None:
            raise JobStoreUnavailableError("Durable job storage is unavailable")
        await self._ensure_indexes(collection)
        now = self._utc_now()
        lease_token = uuid.uuid4().hex
        lease_expires_at = now + timedelta(seconds=max(5, int(lease_seconds)))
        claim_filter = {
            "queue_version": DURABLE_JOB_VERSION,
            "kind": {"$in": list(DURABLE_JOB_KINDS)},
            "$or": [
                {"status": "queued", "next_attempt_at": {"$lte": now}},
                {"status": {"$in": ["running", "publishing"]}, "lease_expires_at": {"$lte": now}},
            ],
        }
        update = {
            "$set": {
                "status": "running",
                "lease_token": lease_token,
                "lease_expires_at": lease_expires_at,
                "worker_id": worker_id,
                "updated_at": self._utc_timestamp(now),
                "claimed_at": self._utc_timestamp(now),
            },
            "$inc": {"attempt_count": 1, "lease_generation": 1},
        }
        try:
            document = await collection.find_one_and_update(
                claim_filter,
                update,
                sort=[("next_attempt_at", 1), ("created_at", 1)],
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            logger.warning("durable_job_claim_failed", error_type=type(exc).__name__)
            raise JobStoreUnavailableError("Durable job storage is unavailable") from exc
        if not document:
            return None
        cached = self._document_for_cache(document["_id"], document)
        await self._cache_document(document["_id"], cached)
        return cached | {"lease_token": lease_token}

    async def renew_lease(self, job_id: str, lease_token: str, *, lease_seconds: int) -> bool:
        return await self._fenced_update(
            job_id,
            lease_token,
            {"status": {"$in": ["running", "publishing"]}},
            {
                "lease_expires_at": self._utc_now() + timedelta(seconds=max(5, int(lease_seconds))),
                "updated_at": self._utc_timestamp(),
            },
        )

    async def begin_publish(self, job_id: str, lease_token: str) -> bool:
        """Fence the pre-publish boundary against queued/running cancellation."""
        now = self._utc_timestamp()
        return await self._fenced_update(
            job_id,
            lease_token,
            {"status": "running"},
            {"status": "publishing", "phase": "publishing", "publish_started_at": now, "updated_at": now},
        )

    async def mark_progress(self, job_id: str, lease_token: str, processed_count: int) -> bool:
        return await self._fenced_update(
            job_id,
            lease_token,
            {"status": {"$in": ["running", "publishing"]}},
            {"processed_count": max(0, int(processed_count)), "updated_at": self._utc_timestamp()},
        )

    async def complete(self, job_id: str, lease_token: str) -> bool:
        now = self._utc_timestamp()
        return await self._fenced_update(
            job_id,
            lease_token,
            {"status": "publishing"},
            {
                "status": "completed",
                "phase": "completed",
                "completed_at": now,
                "lease_expires_at": None,
                "lease_token": None,
                "error": None,
                "updated_at": now,
            },
        )

    async def retry_or_fail(
        self,
        job_id: str,
        lease_token: str,
        *,
        error: str,
        retryable: bool,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> bool:
        """Fenced retry/terminal transition; stale workers cannot overwrite state."""
        try:
            job_id = self._validate_job_id(job_id)
        except ValueError:
            return False
        collection = self._get_collection()
        if collection is None:
            raise JobStoreUnavailableError("Durable job storage is unavailable")
        try:
            # This raw read is only used to select retry vs terminal behavior;
            # the state change below remains fenced by the same lease token.
            job = await collection.find_one(
                {
                    "_id": job_id,
                    "queue_version": DURABLE_JOB_VERSION,
                    "kind": {"$in": list(DURABLE_JOB_KINDS)},
                    "lease_token": lease_token,
                    "status": {"$in": ["running", "publishing"]},
                },
                {"attempt_count": 1},
            )
        except Exception as exc:
            logger.warning("durable_job_retry_read_failed", job_id=job_id, error_type=type(exc).__name__)
            raise JobStoreUnavailableError("Durable job storage is unavailable") from exc
        if not job:
            return False
        attempts = int(job.get("attempt_count") or 0)
        publishing = job.get("phase") == "publishing"
        # Publish is deliberately an idempotent, recoverable commit phase. A
        # terminal publish failure could leave a subset of deterministic chunks
        # visible, so it must remain claimable until the worker finishes the
        # same upserts. The retry budget applies only before the publish fence.
        terminal = not publishing and (not retryable or attempts >= max(1, int(max_attempts)))
        now = self._utc_now()
        if terminal:
            updates = {
                "status": "error",
                "phase": "failed",
                "error": error,
                "completed_at": self._utc_timestamp(now),
                "lease_token": None,
                "lease_expires_at": None,
                "updated_at": self._utc_timestamp(now),
            }
        else:
            updates = {
                "status": "queued",
                "phase": "publishing" if publishing else "staging",
                "error": None,
                "next_attempt_at": now + timedelta(seconds=max(1, int(retry_delay_seconds))),
                "lease_token": None,
                "lease_expires_at": None,
                "updated_at": self._utc_timestamp(now),
            }
        return await self._fenced_update(
            job_id,
            lease_token,
            {"status": {"$in": ["running", "publishing"]}},
            updates,
        )

    async def cancel(self, job_id: str) -> bool:
        """Cancel only before publishing. Publishing is completed atomically instead.

        Once ``begin_publish`` wins, exposing only a subset of the job would be
        worse than finishing deterministic upserts. This method therefore leaves
        publishing jobs fenced to their worker and reports that cancellation was
        requested without changing a terminal state.
        """
        try:
            job_id = self._validate_job_id(job_id)
        except ValueError:
            return False
        collection = self._get_collection()
        if collection is None:
            # Legacy development-only cancellation.
            job = self._fallback.get(job_id)
            if not job:
                return False
            job.update({"status": "cancelled", "completed_at": self._utc_timestamp()})
            return True
        now = self._utc_timestamp()
        try:
            document = await collection.find_one_and_update(
                {
                    "_id": job_id,
                    "queue_version": DURABLE_JOB_VERSION,
                    "kind": {"$in": list(DURABLE_JOB_KINDS)},
                    "status": {"$in": ["queued", "running"]},
                    "publish_started_at": {"$exists": False},
                },
                {
                    "$set": {
                        "status": "cancelled",
                        "phase": "cancelled",
                        "cancelled_at": now,
                        "completed_at": now,
                        "lease_token": None,
                        "lease_expires_at": None,
                        "updated_at": now,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            logger.warning("durable_job_cancel_failed", job_id=job_id, error_type=type(exc).__name__)
            raise JobStoreUnavailableError("Durable job storage is unavailable") from exc
        if document:
            await self._cache_document(job_id, document)
            return True
        # Preserve historical cancellation behavior for non-durable jobs while
        # refusing to overwrite a terminal/publishing v2 job.
        try:
            legacy = await collection.find_one({"_id": job_id, "queue_version": {"$exists": False}})
            if not legacy or legacy.get("status") in TERMINAL_STATUSES:
                return False
            result = await collection.update_one(
                {"_id": job_id, "queue_version": {"$exists": False}, "status": {"$nin": list(TERMINAL_STATUSES)}},
                {"$set": {"status": "cancelled", "completed_at": now, "updated_at": now}},
            )
            if getattr(result, "matched_count", 0):
                await self._cache_delete(job_id)
                return True
            return False
        except Exception as exc:
            logger.warning("legacy_job_cancel_failed", job_id=job_id, error_type=type(exc).__name__)
            raise JobStoreUnavailableError("Durable job storage is unavailable") from exc

    async def _fenced_update(
        self,
        job_id: str,
        lease_token: str,
        extra_filter: Dict[str, Any],
        updates: Dict[str, Any],
    ) -> bool:
        try:
            job_id = self._validate_job_id(job_id)
        except ValueError:
            return False
        collection = self._get_collection()
        if collection is None:
            raise JobStoreUnavailableError("Durable job storage is unavailable")
        query: Dict[str, Any] = {
            "_id": job_id,
            "queue_version": DURABLE_JOB_VERSION,
            "kind": {"$in": list(DURABLE_JOB_KINDS)},
            "lease_token": lease_token,
        }
        query.update(extra_filter)
        try:
            result = await collection.update_one(query, {"$set": updates})
        except Exception as exc:
            logger.warning("durable_job_fenced_update_failed", job_id=job_id, error_type=type(exc).__name__)
            raise JobStoreUnavailableError("Durable job storage is unavailable") from exc
        if getattr(result, "matched_count", 0) == 0:
            return False
        document = await self._read_db_document(collection, job_id)
        await self._cache_document(job_id, document)
        return document is not None

    async def delete(self, job_id: str) -> bool:
        try:
            job_id = self._validate_job_id(job_id)
        except ValueError:
            return False
        collection = self._get_collection()
        db_error: Exception | None = None
        deleted = False
        if collection is not None:
            try:
                result = await collection.delete_one({"_id": job_id})
                deleted = bool(getattr(result, "deleted_count", 1))
            except Exception as exc:
                db_error = exc
                logger.warning("job_store_mongodb_delete_failed", job_id=job_id, error_type=type(exc).__name__)
        cache_deleted = await self._cache_delete(job_id)
        fallback_deleted = self._fallback.pop(job_id, None) is not None
        if db_error is not None:
            raise JobStoreUnavailableError("Durable job storage is unavailable") from db_error
        return deleted if collection is not None else cache_deleted or fallback_deleted
