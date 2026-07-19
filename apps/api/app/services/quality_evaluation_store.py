"""Tenant-bound persistence for redacted staging-quality evidence only."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.connections import connection_manager


QUALITY_EVALUATION_RUNS_COLLECTION = "quality_evaluation_runs"


class QualityEvaluationStoreError(RuntimeError):
    """The isolated staging evaluation store could not complete an operation."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class QualityEvaluationStore:
    """Store records only in the immutable brand database selected by server state."""

    def __init__(self, *, result_ttl_seconds: int):
        self.result_ttl_seconds = int(result_ttl_seconds)

    @staticmethod
    def _collection(brand_slug: str):
        return connection_manager.get_brand_db(brand_slug)[QUALITY_EVALUATION_RUNS_COLLECTION]

    async def ensure_indexes(self, *, brand_slug: str) -> None:
        collection = self._collection(brand_slug)
        try:
            await collection.create_index("id", unique=True, name="quality_evaluation_run_id_idx")
            await collection.create_index(
                [("brand_id", 1), ("created_at", -1)],
                name="quality_evaluation_brand_created_idx",
            )
            await collection.create_index(
                [("brand_id", 1), ("agent_id", 1), ("created_at", -1)],
                name="quality_evaluation_brand_agent_created_idx",
            )
            await collection.create_index(
                "expires_at",
                expireAfterSeconds=0,
                name="quality_evaluation_expiry_idx",
            )
        except Exception as exc:
            raise QualityEvaluationStoreError("Evaluation-result indexes are unavailable") from exc

    async def create_run(
        self,
        *,
        brand_id: str,
        brand_slug: str,
        agent_id: str,
        target_profile: dict[str, str],
        report: dict[str, Any],
        ingested_by_key_id: str,
    ) -> dict[str, Any]:
        now = _utc_now()
        document = {
            "id": str(uuid.uuid4()),
            "schema_version": "staging-quality-run/v1",
            # Immutable ownership is set only from resolved server records.
            "brand_id": brand_id,
            "brand_slug": brand_slug,
            "agent_id": agent_id,
            "target_profile": dict(target_profile),
            "report": dict(report),
            "ingested_by_key_id": ingested_by_key_id,
            "created_at": now,
            "expires_at": now + timedelta(seconds=self.result_ttl_seconds),
            "reviews": [],
        }
        await self.ensure_indexes(brand_slug=brand_slug)
        try:
            await self._collection(brand_slug).insert_one(document)
        except Exception as exc:
            raise QualityEvaluationStoreError("Staging evaluation result could not be persisted") from exc
        return self.public_run(document, include_reviews=True)

    async def list_runs(
        self,
        *,
        brand_id: str,
        brand_slug: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            cursor = self._collection(brand_slug).find({"brand_id": brand_id}).sort("created_at", -1)
            rows = await cursor.to_list(length=max(1, min(int(limit), 100)))
        except Exception as exc:
            raise QualityEvaluationStoreError("Staging evaluation results are unavailable") from exc
        return [self.public_run(row, include_reviews=False) for row in rows]

    async def get_run(self, *, brand_id: str, brand_slug: str, run_id: str) -> dict[str, Any] | None:
        try:
            row = await self._collection(brand_slug).find_one(
                {"id": run_id, "brand_id": brand_id, "brand_slug": brand_slug}
            )
        except Exception as exc:
            raise QualityEvaluationStoreError("Staging evaluation result is unavailable") from exc
        return self.public_run(row, include_reviews=True) if row else None

    async def has_human_review(
        self,
        *,
        brand_id: str,
        brand_slug: str,
        run_id: str,
        case_id: str,
    ) -> bool:
        try:
            row = await self._collection(brand_slug).find_one(
                {
                    "id": run_id,
                    "brand_id": brand_id,
                    "brand_slug": brand_slug,
                    "reviews": {"$elemMatch": {"case_id": case_id, "reviewer_type": "human"}},
                },
                {"_id": 1},
            )
        except Exception as exc:
            raise QualityEvaluationStoreError("Staging evaluation review state is unavailable") from exc
        return bool(row)

    async def append_review(
        self,
        *,
        brand_id: str,
        brand_slug: str,
        run_id: str,
        review: dict[str, Any],
        submitted_by: str,
    ) -> dict[str, Any] | None:
        stored_review = {
            **review,
            "submitted_by": submitted_by,
            "submitted_at": _utc_now(),
        }
        try:
            result = await self._collection(brand_slug).update_one(
                {"id": run_id, "brand_id": brand_id, "brand_slug": brand_slug},
                {"$push": {"reviews": stored_review}},
            )
            if result.matched_count == 0:
                return None
            row = await self._collection(brand_slug).find_one(
                {"id": run_id, "brand_id": brand_id, "brand_slug": brand_slug}
            )
        except Exception as exc:
            raise QualityEvaluationStoreError("Staging evaluation review could not be stored") from exc
        return self.public_run(row, include_reviews=True) if row else None

    @staticmethod
    def public_run(document: dict[str, Any], *, include_reviews: bool) -> dict[str, Any]:
        result = {
            "id": document.get("id"),
            "schema_version": document.get("schema_version"),
            "brand_id": document.get("brand_id"),
            "agent_id": document.get("agent_id"),
            "target_profile": document.get("target_profile") or {},
            "report": document.get("report") or {},
            "created_at": document.get("created_at"),
            "expires_at": document.get("expires_at"),
        }
        if include_reviews:
            result["reviews"] = document.get("reviews") or []
        else:
            result["review_count"] = len(document.get("reviews") or [])
        return result
