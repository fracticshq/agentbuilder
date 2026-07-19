"""Tenant-bound consent, portability, deletion, and retention primitives.

This module deliberately operates on the live storage layout rather than the
legacy ``MemoryManager.delete_user_data`` helper.  Widget subjects are bound to
an immutable conversation scope, so every export or erasure can be routed to
the creation-time brand database without trusting a client-provided tenant.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from ..config import Settings
from ..connections import connection_manager
from ..websocket_manager import ws_manager
from .strapi_privacy_store import (
    StrapiPrivacyStore,
    StrapiPrivacyStoreError,
    idempotency_reference,
    subject_reference,
)

logger = structlog.get_logger(__name__)

PRIVACY_POLICIES_COLLECTION = "privacy_policies"
PRIVACY_DELETION_RECEIPTS_COLLECTION = "privacy_deletion_receipts"
CONVERSATION_SCOPES_COLLECTION = "widget_conversation_scopes"

_BRAND_COLLECTIONS = {
    "conversations": "conversations",
    "summaries": "short_term_summaries",
    "episodic_facts": "episodic_memory",
    "activity_events": "activity_events",
    "observability_events": "observability_events",
    # Aggregate-only synthetic staging evidence still has a bounded retention
    # period. It is never exported as subject data because it contains no
    # subject identifiers.
    "quality_evaluation_runs": "quality_evaluation_runs",
}


class PrivacyLifecycleError(RuntimeError):
    """A privacy lifecycle operation could not be completed safely."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PrivacyLifecycleService:
    """Implements subject-data operations across known first-party stores."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.strapi_privacy_store = StrapiPrivacyStore(settings)

    def _system_db(self):
        try:
            return connection_manager.get_system_db()
        except (RuntimeError, AttributeError, KeyError, TypeError) as exc:
            raise PrivacyLifecycleError("Privacy storage is unavailable") from exc

    @staticmethod
    def _conversation_query(subject_id: str, conversation_ids: list[str]) -> dict[str, Any]:
        clauses: list[dict[str, Any]] = [{"metadata.user_id": subject_id}]
        if conversation_ids:
            clauses.append({"conversation_id": {"$in": conversation_ids}})
        return {"$or": clauses}

    @staticmethod
    def _activity_query(subject_id: str, conversation_ids: list[str]) -> dict[str, Any]:
        clauses: list[dict[str, Any]] = [{"actor_id": subject_id, "actor_type": "user"}]
        if conversation_ids:
            clauses.append({"conversation_id": {"$in": conversation_ids}})
        return {"$or": clauses}

    async def _subject_conversation_ids(self, brand_id: str, subject_id: str) -> list[str]:
        try:
            cursor = self._system_db()[CONVERSATION_SCOPES_COLLECTION].find(
                {"brand_id": brand_id, "user_id": subject_id},
                {"_id": 1},
            )
            rows = await cursor.to_list(length=self.settings.PRIVACY_EXPORT_MAX_RECORDS)
        except Exception as exc:
            raise PrivacyLifecycleError("Privacy storage is unavailable") from exc
        return [str(row.get("_id")) for row in rows if row.get("_id")]

    async def set_retention_policy(
        self,
        *,
        brand_id: str,
        brand_slug: str,
        retention_days: int,
        updated_by: str | None,
    ) -> dict[str, Any]:
        retention_days = int(retention_days)
        if not 1 <= retention_days <= 3650:
            raise ValueError("retention_days must be between 1 and 3650")
        now = _utc_now()
        policy = {
            "brand_id": brand_id,
            "brand_slug": brand_slug,
            "retention_days": retention_days,
            "updated_at": now,
            "updated_by": updated_by or None,
            "schema_version": "v1",
        }
        try:
            await self._system_db()[PRIVACY_POLICIES_COLLECTION].update_one(
                {"brand_id": brand_id},
                {"$set": policy, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        except Exception as exc:
            raise PrivacyLifecycleError("Privacy policy storage is unavailable") from exc
        return policy

    async def get_retention_policy(self, *, brand_id: str, brand_slug: str) -> dict[str, Any]:
        try:
            policy = await self._system_db()[PRIVACY_POLICIES_COLLECTION].find_one(
                {"brand_id": brand_id},
                {"_id": 0},
            )
        except Exception as exc:
            raise PrivacyLifecycleError("Privacy policy storage is unavailable") from exc
        if isinstance(policy, dict):
            return policy
        return {
            "brand_id": brand_id,
            "brand_slug": brand_slug,
            "retention_days": self.settings.PRIVACY_DEFAULT_RETENTION_DAYS,
            "schema_version": "v1",
            "source": "default",
        }

    async def apply_retention_policy(
        self,
        *,
        brand_id: str,
        brand_slug: str,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        if retention_days is None:
            policy = await self.get_retention_policy(brand_id=brand_id, brand_slug=brand_slug)
            retention_days = int(policy["retention_days"])
        retention_days = int(retention_days)
        cutoff = _utc_now() - timedelta(days=retention_days)
        try:
            db = connection_manager.get_brand_db(brand_slug)
            deleted = {
                "conversations": (await db[_BRAND_COLLECTIONS["conversations"]].delete_many({"timestamp": {"$lt": cutoff}})).deleted_count,
                "summaries": (await db[_BRAND_COLLECTIONS["summaries"]].delete_many({"created_at": {"$lt": cutoff}})).deleted_count,
                "episodic_facts": (await db[_BRAND_COLLECTIONS["episodic_facts"]].delete_many({"created_at": {"$lt": cutoff}})).deleted_count,
                "activity_events": (await db[_BRAND_COLLECTIONS["activity_events"]].delete_many({"timestamp": {"$lt": cutoff}})).deleted_count,
                "observability_events": (await db[_BRAND_COLLECTIONS["observability_events"]].delete_many({"timestamp": {"$lt": cutoff}})).deleted_count,
                "quality_evaluation_runs": (await db[_BRAND_COLLECTIONS["quality_evaluation_runs"]].delete_many({"created_at": {"$lt": cutoff}})).deleted_count,
            }
        except Exception as exc:
            raise PrivacyLifecycleError("Retention cleanup failed") from exc
        return {
            "brand_id": brand_id,
            "brand_slug": brand_slug,
            "retention_days": retention_days,
            "cutoff": cutoff,
            "deleted": deleted,
            "completed_at": _utc_now(),
        }

    async def export_subject(
        self,
        *,
        brand_id: str,
        brand_slug: str,
        subject_id: str,
    ) -> dict[str, Any]:
        conversation_ids = await self._subject_conversation_ids(brand_id, subject_id)
        try:
            db = connection_manager.get_brand_db(brand_slug)
            conversations = await db[_BRAND_COLLECTIONS["conversations"]].find(
                self._conversation_query(subject_id, conversation_ids), {"_id": 0}
            ).sort("timestamp", 1).to_list(length=self.settings.PRIVACY_EXPORT_MAX_RECORDS)
            summaries = await db[_BRAND_COLLECTIONS["summaries"]].find(
                {"conversation_id": {"$in": conversation_ids}} if conversation_ids else {"_id": {"$exists": False}},
                {"_id": 0},
            ).sort("created_at", 1).to_list(length=self.settings.PRIVACY_EXPORT_MAX_RECORDS)
            episodic_facts = await db[_BRAND_COLLECTIONS["episodic_facts"]].find(
                {"user_id": subject_id}, {"_id": 0}
            ).sort("created_at", 1).to_list(length=self.settings.PRIVACY_EXPORT_MAX_RECORDS)
            activity_events = await db[_BRAND_COLLECTIONS["activity_events"]].find(
                self._activity_query(subject_id, conversation_ids), {"_id": 0}
            ).sort("timestamp", 1).to_list(length=self.settings.PRIVACY_EXPORT_MAX_RECORDS)
            observability_events = await db[_BRAND_COLLECTIONS["observability_events"]].find(
                {"conversation_id": {"$in": conversation_ids}} if conversation_ids else {"_id": {"$exists": False}},
                {"_id": 0},
            ).sort("timestamp", 1).to_list(length=self.settings.PRIVACY_EXPORT_MAX_RECORDS)
        except Exception as exc:
            raise PrivacyLifecycleError("Subject export failed") from exc
        return {
            "schema_version": "v1",
            "generated_at": _utc_now(),
            "subject": {"id": subject_id, "conversation_ids": conversation_ids},
            "data": {
                "conversations": conversations,
                "summaries": summaries,
                "episodic_facts": episodic_facts,
                "activity_events": activity_events,
                "observability_events": observability_events,
            },
            "external_processors": self._external_processors(),
        }

    async def delete_long_term_memory(
        self,
        *,
        brand_slug: str,
        subject_id: str,
    ) -> dict[str, Any]:
        """Withdraw consent without deleting the active short-term chat."""
        try:
            db = connection_manager.get_brand_db(brand_slug)
            result = await db[_BRAND_COLLECTIONS["episodic_facts"]].delete_many(
                {"user_id": subject_id}
            )
            verified = await db[_BRAND_COLLECTIONS["episodic_facts"]].count_documents(
                {"user_id": subject_id}
            ) == 0
        except Exception as exc:
            raise PrivacyLifecycleError("Long-term memory deletion failed") from exc
        return {"deleted": result.deleted_count, "verified": verified}

    def _external_processors(self, request: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Report Strapi from the explicit privacy mode, never STRAPI_URL.

        The dashboard conversation mirror does not implement this protocol;
        its URL/token are intentionally irrelevant to privacy completion.
        """
        mode = str(getattr(self.settings, "STRAPI_PRIVACY_MODE", "contract_pending") or "contract_pending").lower()
        if request:
            return [{
                "name": "strapi",
                "status": request.get("status", "pending_contract"),
                "request_id": request.get("request_id"),
                "receipt_verified": bool(request.get("receipt_verified")),
            }]
        if mode == "disabled":
            return [{"name": "strapi", "status": "disabled"}]
        if mode == "active":
            return [{"name": "strapi", "status": "active_contract"}]
        return [{"name": "strapi", "status": "pending_contract"}]

    def _strapi_privacy_references(self, *, brand_id: str, subject_id: str) -> tuple[str, str]:
        """Derive only opaque external references before erasing local data."""
        secret = str(getattr(self.settings, "STRAPI_PRIVACY_SUBJECT_HMAC_KEY", "") or "")
        try:
            return (
                subject_reference(subject_id=subject_id, brand_id=brand_id, secret=secret),
                idempotency_reference(subject_id=subject_id, brand_id=brand_id, secret=secret),
            )
        except ValueError as exc:
            raise PrivacyLifecycleError("Strapi privacy subject reference is not configured") from exc

    async def _create_or_reuse_strapi_deletion_request(
        self,
        *,
        brand_id: str,
        brand_slug: str,
        subject_reference_value: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            request, _ = await self.strapi_privacy_store.create_or_get_deletion_request(
                brand_id=brand_id,
                brand_slug=brand_slug,
                subject_reference=subject_reference_value,
                idempotency_key=idempotency_key,
            )
            return request
        except (StrapiPrivacyStoreError, ValueError) as exc:
            raise PrivacyLifecycleError("Strapi privacy deletion request could not be recorded") from exc

    async def delete_subject(
        self,
        *,
        brand_id: str,
        brand_slug: str,
        subject_id: str,
        requested_by: str | None = None,
    ) -> dict[str, Any]:
        # Validate the separate privacy HMAC before first-party deletion. A
        # deletion caller must never receive a local-completion receipt without
        # the durable external operation that makes its state auditable.
        strapi_subject_reference, strapi_idempotency_key = self._strapi_privacy_references(
            brand_id=brand_id,
            subject_id=subject_id,
        )
        conversation_ids = await self._subject_conversation_ids(brand_id, subject_id)
        conversations_query = self._conversation_query(subject_id, conversation_ids)
        activity_query = self._activity_query(subject_id, conversation_ids)
        summaries_query = {"conversation_id": {"$in": conversation_ids}} if conversation_ids else {"_id": {"$exists": False}}
        observability_query = {"conversation_id": {"$in": conversation_ids}} if conversation_ids else {"_id": {"$exists": False}}

        try:
            db = connection_manager.get_brand_db(brand_slug)
            deleted = {
                "conversations": (await db[_BRAND_COLLECTIONS["conversations"]].delete_many(conversations_query)).deleted_count,
                "summaries": (await db[_BRAND_COLLECTIONS["summaries"]].delete_many(summaries_query)).deleted_count,
                "episodic_facts": (await db[_BRAND_COLLECTIONS["episodic_facts"]].delete_many({"user_id": subject_id})).deleted_count,
                "activity_events": (await db[_BRAND_COLLECTIONS["activity_events"]].delete_many(activity_query)).deleted_count,
                "observability_events": (await db[_BRAND_COLLECTIONS["observability_events"]].delete_many(observability_query)).deleted_count,
            }
            verification = {
                "conversations": await db[_BRAND_COLLECTIONS["conversations"]].count_documents(conversations_query) == 0,
                "summaries": await db[_BRAND_COLLECTIONS["summaries"]].count_documents(summaries_query) == 0,
                "episodic_facts": await db[_BRAND_COLLECTIONS["episodic_facts"]].count_documents({"user_id": subject_id}) == 0,
                "activity_events": await db[_BRAND_COLLECTIONS["activity_events"]].count_documents(activity_query) == 0,
                "observability_events": await db[_BRAND_COLLECTIONS["observability_events"]].count_documents(observability_query) == 0,
            }
            now = _utc_now()
            tombstones = await self._system_db()[CONVERSATION_SCOPES_COLLECTION].update_many(
                {"brand_id": brand_id, "user_id": subject_id},
                {
                    "$set": {
                        "privacy.status": "erased",
                        "privacy.erased_at": now,
                        "privacy.updated_at": now,
                    },
                    "$unset": {"user_id": ""},
                },
            )
        except Exception as exc:
            raise PrivacyLifecycleError("Subject deletion failed") from exc

        for conversation_id in conversation_ids:
            await ws_manager.purge_conversation_state(conversation_id)

        locally_verified = all(verification.values())
        # The durable request is written after first-party verification but
        # before any deletion receipt is reported. contract_pending and
        # disabled modes still create this audit record; neither performs I/O.
        external_request = await self._create_or_reuse_strapi_deletion_request(
            brand_id=brand_id,
            brand_slug=brand_slug,
            subject_reference_value=strapi_subject_reference,
            idempotency_key=strapi_idempotency_key,
        )
        external_processors = self._external_processors(external_request)
        externally_verified = (
            external_request.get("status") == "completed"
            and external_request.get("receipt_verified") is True
        )
        status = "completed" if locally_verified and externally_verified else "pending"
        request_id = f"privacy_{uuid.uuid4().hex}"
        receipt = {
            "id": request_id,
            "schema_version": "v1",
            "brand_id": brand_id,
            "brand_slug": brand_slug,
            "subject_reference": strapi_subject_reference,
            "requested_by": requested_by,
            "status": status,
            "deleted": deleted,
            "verified": verification,
            "tombstoned_sessions": tombstones.modified_count,
            "external_processors": external_processors,
            "requested_at": _utc_now(),
        }
        if status == "completed":
            receipt["completed_at"] = _utc_now()
        try:
            await self._system_db()[PRIVACY_DELETION_RECEIPTS_COLLECTION].insert_one(receipt)
        except Exception as exc:
            # The data is erased, but the operation cannot truthfully be
            # reported as verified until an auditable receipt was persisted.
            logger.error("privacy_deletion_receipt_write_failed", error_type=type(exc).__name__)
            raise PrivacyLifecycleError("Subject deletion verification could not be recorded") from exc
        return receipt
