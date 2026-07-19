"""Schedule due Shopify snapshots through the same durable queue as webhooks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

import structlog

from app.config import Settings
from app.connections import connection_manager
from app.services import catalog_service
from app.services.catalog_sync_store import CatalogSyncStore, CatalogSyncStoreUnavailableError

logger = structlog.get_logger(__name__)

_FREQUENCIES = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_due(config: dict[str, Any], now: datetime) -> bool:
    frequency = str(config.get("sync_frequency") or "manual").strip().lower()
    interval = _FREQUENCIES.get(frequency)
    if interval is None:
        return False
    last_completed = _parse_timestamp(config.get("last_synced_at") or config.get("last_sync_completed_at"))
    return last_completed is None or now - last_completed >= interval


async def schedule_due_shopify_syncs(store: CatalogSyncStore, settings: Settings) -> int:
    """Queue due enabled configs; active-key uniqueness makes this replica-safe."""
    db = connection_manager.get_system_db()
    now = datetime.now(timezone.utc)
    queued = 0
    cursor = db.brands.find(
        {
            "catalog_sync.source_type": "shopify",
            "catalog_sync.auto_sync": True,
            "catalog_sync.enabled": {"$ne": False},
        }
    )
    async for brand in cursor:
        brand_id = str(brand.get("id") or "")
        brand_slug = str(brand.get("slug") or brand_id)
        config = dict(brand.get("catalog_sync") or {})
        if not brand_id or not _is_due(config, now):
            continue
        encrypted_token = str(config.get("access_token_encrypted") or "")
        if not encrypted_token:
            logger.warning("catalog_auto_sync_skipped_missing_credential", brand_id=brand_id)
            continue
        try:
            source_url = catalog_service.normalize_authenticated_shopify_store_url(config.get("source_url"))
            job, deduplicated = await store.enqueue_sync(
                job_id=str(uuid.uuid4()),
                brand_id=brand_id,
                brand_slug=brand_slug,
                source_url=source_url,
                access_token_encrypted=encrypted_token,
                fallback_currency=config.get("fallback_currency"),
                trigger="scheduled_sync",
            )
            if not deduplicated:
                try:
                    await catalog_service.create_job(str(job["job_id"]), "shopify", brand_id=brand_id, total=0)
                except Exception:
                    await store.cancel_queued(str(job["job_id"]), reason="catalog_progress_store_unavailable")
                    raise
                queued += 1
        except (ValueError, CatalogSyncStoreUnavailableError) as exc:
            logger.warning(
                "catalog_auto_sync_schedule_failed",
                brand_id=brand_id,
                error_type=type(exc).__name__,
            )
    return queued
