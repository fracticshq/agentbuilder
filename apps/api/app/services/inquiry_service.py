"""
Inquiry persistence (brand-isolated).

Mirrors observability_service.py's pattern: write into the brand's own
MongoDB database (auto-created on first insert, no manual setup needed).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from ..connections import connection_manager

logger = structlog.get_logger(__name__)

COLLECTION_NAME = "inquiries"
_indexed_brand_dbs: set[str] = set()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InquiryService:
    async def _ensure_indexes(self, brand_slug: str) -> None:
        db = connection_manager.get_brand_db(brand_slug)
        db_name = db.name
        if db_name in _indexed_brand_dbs:
            return
        collection = db[COLLECTION_NAME]
        await collection.create_index([("inquiry_id", 1)], unique=True)
        await collection.create_index([("agent_id", 1), ("created_at", -1)])
        await collection.create_index([("conversation_id", 1)])
        _indexed_brand_dbs.add(db_name)
        logger.info("inquiry_indexes_created", brand_slug=brand_slug)

    async def save_inquiry(
        self,
        *,
        brand_slug: str,
        brand_id: str | None,
        agent_id: str | None,
        conversation_id: str | None,
        contact: dict[str, Any],
        requirements: str,
        product_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_indexes(brand_slug)
        db = connection_manager.get_brand_db(brand_slug)

        inquiry_id = str(uuid.uuid4())
        doc = {
            "inquiry_id": inquiry_id,
            "brand_id": brand_id,
            "brand_slug": brand_slug,
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "status": "submitted",
            "product_context": product_context or {},
            "contact": contact,
            "requirements": requirements,
            "delivery": {"method": None, "delivered_at": None, "error": None},
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        await db[COLLECTION_NAME].insert_one(doc)
        # Never log raw contact fields (PII discipline).
        logger.info("inquiry_saved", inquiry_id=inquiry_id, brand_slug=brand_slug, agent_id=agent_id)
        return doc

    async def mark_delivered(self, *, brand_slug: str, inquiry_id: str, method: str) -> None:
        db = connection_manager.get_brand_db(brand_slug)
        await db[COLLECTION_NAME].update_one(
            {"inquiry_id": inquiry_id},
            {
                "$set": {
                    "status": "delivered",
                    "delivery.method": method,
                    "delivery.delivered_at": _utc_now(),
                    "delivery.error": None,
                    "updated_at": _utc_now(),
                }
            },
        )
        logger.info("inquiry_marked_delivered", inquiry_id=inquiry_id, brand_slug=brand_slug)

    async def mark_failed(self, *, brand_slug: str, inquiry_id: str, method: str, error: str) -> None:
        db = connection_manager.get_brand_db(brand_slug)
        await db[COLLECTION_NAME].update_one(
            {"inquiry_id": inquiry_id},
            {
                "$set": {
                    "status": "delivery_failed",
                    "delivery.method": method,
                    "delivery.error": error,
                    "updated_at": _utc_now(),
                }
            },
        )
        logger.warning("inquiry_marked_failed", inquiry_id=inquiry_id, brand_slug=brand_slug, error=error)
