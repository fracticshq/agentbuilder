"""Periodic first-party data-retention worker.

Retention deletion is idempotent and Mongo is authoritative, so this worker can
restart freely and may be scaled only after the deployment scheduler guarantees
one active cleanup run per brand.  It intentionally does not touch external
processors (for example the legacy Strapi mirror) without their verified
deletion contract.
"""

from __future__ import annotations

import asyncio

import structlog

from app.config import Settings
from app.connections import connection_manager
from app.services.privacy_lifecycle_service import PrivacyLifecycleError, PrivacyLifecycleService

logger = structlog.get_logger(__name__)


async def run_once(service: PrivacyLifecycleService) -> int:
    system_db = connection_manager.get_system_db()
    try:
        brands = await system_db.brands.find({}, {"id": 1, "slug": 1}).to_list(length=None)
    except Exception as exc:
        raise PrivacyLifecycleError("Privacy retention could not list brands") from exc

    completed = 0
    for brand in brands:
        brand_id = brand.get("id")
        brand_slug = brand.get("slug")
        if not isinstance(brand_id, str) or not brand_id or not isinstance(brand_slug, str) or not brand_slug:
            logger.warning("privacy_retention_brand_skipped", reason="missing_tenant_scope")
            continue
        try:
            result = await service.apply_retention_policy(
                brand_id=brand_id,
                brand_slug=brand_slug,
            )
            completed += 1
            logger.info(
                "privacy_retention_completed",
                brand_id=brand_id,
                brand_slug=brand_slug,
                deleted=sum(result["deleted"].values()),
            )
        except PrivacyLifecycleError as exc:
            logger.error(
                "privacy_retention_failed",
                brand_id=brand_id,
                brand_slug=brand_slug,
                error_type=type(exc).__name__,
            )
    return completed


async def run() -> None:
    settings = Settings()
    await connection_manager.connect_mongodb()
    if connection_manager.system_db is None:
        raise RuntimeError("MongoDB is required for the privacy retention worker")
    service = PrivacyLifecycleService(settings)
    logger.info("privacy_retention_worker_started")
    try:
        while True:
            try:
                await run_once(service)
            except PrivacyLifecycleError as exc:
                logger.error("privacy_retention_iteration_failed", error_type=type(exc).__name__)
            await asyncio.sleep(max(1.0, float(settings.PRIVACY_RETENTION_POLL_SECONDS)))
    finally:
        await connection_manager.disconnect_mongodb()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
