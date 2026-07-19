"""Encrypted, short-lived source payload storage for durable ingestion jobs.

Jobs retain only opaque payload references.  The original uploaded bytes never
appear in an ingestion job, Redis cache, or log event. Payloads use the same
key derivation hierarchy as runtime settings and are removed on completion or
by a MongoDB TTL index.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Iterable

import structlog
from bson.binary import Binary
from cryptography.fernet import Fernet, InvalidToken

from ..connections import connection_manager
from ..config import Settings
from .runtime_settings_service import RuntimeSettingsService

logger = structlog.get_logger(__name__)

PAYLOADS_COLLECTION = "ingestion_payloads"


class IngestionPayloadStoreError(RuntimeError):
    """A payload cannot be durably stored or recovered."""


class InvalidIngestionPayloadError(IngestionPayloadStoreError):
    """The retained source is malformed, corrupt, expired, or cannot decrypt."""


class IngestionPayloadStore:
    def __init__(self, settings: Settings):
        self._fernet = Fernet(RuntimeSettingsService(settings)._derive_encryption_key())
        self.retention_seconds = max(60, int(settings.INGESTION_PAYLOAD_TTL_SECONDS))
        self._indexes_checked = False

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _collection(self):
        try:
            return connection_manager.get_system_db()[PAYLOADS_COLLECTION]
        except (RuntimeError, AttributeError, KeyError, TypeError) as exc:
            raise IngestionPayloadStoreError("Durable payload storage is unavailable") from exc

    async def _ensure_indexes(self, collection: Any) -> None:
        if self._indexes_checked:
            return
        self._indexes_checked = True
        try:
            await collection.create_index("expires_at", expireAfterSeconds=0, name="ingestion_payloads_expiry_idx")
            await collection.create_index([("job_id", 1), ("file_index", 1)], unique=True, name="ingestion_payload_job_file_idx")
        except Exception as exc:
            logger.warning("ingestion_payload_index_setup_failed", error_type=type(exc).__name__)

    async def persist(self, job_id: str, files: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Encrypt and store every source file before the matching job is queued."""
        collection = self._collection()
        await self._ensure_indexes(collection)
        now = self._utc_now()
        expires_at = now + timedelta(seconds=self.retention_seconds)
        refs: list[dict[str, Any]] = []
        inserted_ids: list[str] = []
        try:
            for file_index, file_data in enumerate(files):
                content = file_data.get("content")
                filename = file_data.get("filename")
                content_type = file_data.get("content_type")
                context = file_data.get("context")
                if not isinstance(content, bytes):
                    raise InvalidIngestionPayloadError("Upload source must be bytes")
                if not isinstance(filename, str) or not filename:
                    raise InvalidIngestionPayloadError("Upload filename is required")
                if not isinstance(content_type, str) or not content_type:
                    raise InvalidIngestionPayloadError("Upload content type is required")
                if context is not None and not isinstance(context, dict):
                    raise InvalidIngestionPayloadError("Upload context must be an object")
                try:
                    context_bytes = json.dumps(context or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
                except (TypeError, ValueError) as exc:
                    raise InvalidIngestionPayloadError("Upload context is invalid") from exc
                payload_id = f"{job_id}:{file_index}"
                encrypted = self._fernet.encrypt(content)
                document = {
                    "_id": payload_id,
                    "job_id": job_id,
                    "file_index": file_index,
                    # Filename/type are metadata only; content is always encrypted.
                    "filename": filename,
                    "content_type": content_type,
                    "content_encrypted": Binary(encrypted),
                    # Structured product/dealer metadata and folder paths are
                    # source-derived too. Keep them encrypted alongside bytes,
                    # never in the job record or Redis cache.
                    "context_encrypted": Binary(self._fernet.encrypt(context_bytes)),
                    "created_at": now,
                    "expires_at": expires_at,
                }
                await collection.insert_one(document)
                inserted_ids.append(payload_id)
                refs.append({"payload_id": payload_id, "file_index": file_index})
        except InvalidIngestionPayloadError:
            await self._delete_ids(collection, inserted_ids)
            raise
        except Exception as exc:
            await self._delete_ids(collection, inserted_ids)
            logger.warning("ingestion_payload_persist_failed", job_id=job_id, error_type=type(exc).__name__)
            raise IngestionPayloadStoreError("Durable payload storage is unavailable") from exc
        return refs

    async def load(self, payload_id: str, *, job_id: str) -> dict[str, Any]:
        """Recover a single encrypted source without ever logging its content."""
        collection = self._collection()
        try:
            document = await collection.find_one({"_id": payload_id, "job_id": job_id})
        except Exception as exc:
            logger.warning("ingestion_payload_load_failed", payload_id=payload_id, error_type=type(exc).__name__)
            raise IngestionPayloadStoreError("Durable payload storage is unavailable") from exc
        if not document:
            raise InvalidIngestionPayloadError("Ingestion source payload is unavailable")
        try:
            encrypted = bytes(document["content_encrypted"])
            content = self._fernet.decrypt(encrypted)
            filename = document["filename"]
            content_type = document["content_type"]
            context_encrypted = document.get("context_encrypted")
            context = {}
            if context_encrypted is not None:
                context = json.loads(self._fernet.decrypt(bytes(context_encrypted)).decode("utf-8"))
            if not isinstance(filename, str) or not isinstance(content_type, str):
                raise ValueError("source metadata invalid")
            if not isinstance(context, dict):
                raise ValueError("source context invalid")
        except (KeyError, TypeError, ValueError, InvalidToken) as exc:
            raise InvalidIngestionPayloadError("Ingestion source payload is invalid") from exc
        return {"content": content, "filename": filename, "content_type": content_type, "context": context}

    async def delete_job_payloads(self, job_id: str) -> None:
        try:
            await self._collection().delete_many({"job_id": job_id})
        except Exception as exc:
            # TTL remains a bounded retention backstop. Do not invalidate a
            # completed publish merely because best-effort cleanup failed.
            logger.warning("ingestion_payload_cleanup_failed", job_id=job_id, error_type=type(exc).__name__)

    async def _delete_ids(self, collection: Any, payload_ids: list[str]) -> None:
        if not payload_ids:
            return
        try:
            await collection.delete_many({"_id": {"$in": payload_ids}})
        except Exception:
            # The TTL index is the final safety net for partial submission.
            return
