"""Standalone, restart-safe worker for Shopify catalog lifecycle jobs."""

from __future__ import annotations

import asyncio
import os
import socket
import time
import uuid
from typing import Any

import structlog

from app.config import Settings
from app.connections import connection_manager
from app.services import catalog_service
from app.services.catalog_sync_store import CatalogSyncStore, CatalogSyncStoreUnavailableError
from app.services.catalog_sync_scheduler import schedule_due_shopify_syncs
from app.services.knowledge_service import KnowledgeService
from app.services.runtime_settings_service import RuntimeSettingsService
from app.monitoring import CATALOG_SYNC_COUNT, CATALOG_SYNC_DURATION

logger = structlog.get_logger(__name__)


def worker_id() -> str:
    return os.getenv("CATALOG_SYNC_WORKER_ID") or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"


def _decrypt_access_token(job: dict[str, Any], settings: Settings) -> str | None:
    encrypted = str(job.get("access_token_encrypted") or "").strip()
    if not encrypted:
        return None
    return RuntimeSettingsService(settings)._decrypt(encrypted)


async def _process_job(job: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Execute one claimed job and return safe state to persist."""
    action = str(job.get("action") or "sync")
    brand_id = str(job["brand_id"])
    source_url = str(job["source_url"])

    if action == "sync":
        access_token = _decrypt_access_token(job, settings)
        # fetch_shopify_products preserves the existing canonical product /
        # variant / currency writer. Its legacy job row is now only progress
        # detail; lease state remains owned by CatalogSyncStore.
        await catalog_service.fetch_shopify_products(
            source_url,
            access_token,
            str(job["job_id"]),
            brand_id,
            job.get("fallback_currency"),
        )
        legacy_job = await catalog_service.get_job(str(job["job_id"]))
        if not legacy_job or legacy_job.get("status") != "completed":
            raise RuntimeError("shopify_sync_failed")
        return {
            "phase": "completed",
            "counts": dict(legacy_job.get("counts") or {}),
            "currency": legacy_job.get("currency"),
            "currency_source": legacy_job.get("currency_source"),
            "knowledge_job_id": legacy_job.get("knowledge_job_id"),
        }

    service = KnowledgeService(settings)
    if action == "deactivate_product":
        count = await service.deactivate_shopify_catalog(
            brand_id,
            source_url=source_url,
            product_id=str(job.get("product_id") or ""),
            reason="shopify_product_deleted",
        )
    elif action == "deactivate_source":
        count = await service.deactivate_shopify_catalog(
            brand_id,
            source_url=source_url,
            reason="shopify_app_uninstalled",
        )
    else:
        raise ValueError("unsupported_catalog_lifecycle_action")
    return {"phase": "completed", "counts": {"products_marked_inactive": count}}


async def _maintain_lease(
    store: CatalogSyncStore,
    job: dict[str, Any],
    settings: Settings,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    """Renew a long-running GraphQL sync fence until the worker finishes."""
    interval = max(5.0, min(30.0, float(settings.CATALOG_SYNC_LEASE_SECONDS) / 3))
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        try:
            if not await store.renew_lease(job):
                lease_lost.set()
                logger.warning("catalog_sync_lease_lost", job_id=job.get("job_id"))
                return
        except CatalogSyncStoreUnavailableError:
            lease_lost.set()
            logger.warning("catalog_sync_lease_renewal_unavailable", job_id=job.get("job_id"))
            return


async def run_once(store: CatalogSyncStore, settings: Settings, *, identifier: str) -> bool:
    job = await store.claim_next(worker_id=identifier)
    if not job:
        return False
    action = str(job.get("action") or "sync")
    started = time.monotonic()
    stop_heartbeat = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat = asyncio.create_task(_maintain_lease(store, job, settings, stop_heartbeat, lease_lost))
    try:
        updates = await _process_job(job, settings)
        if lease_lost.is_set():
            raise RuntimeError("catalog_sync_lease_lost")
        if not await store.complete(job, updates):
            # Another worker reclaimed the lease while this job was running.
            # Its terminal state is authoritative; do not emit a false
            # completion metric or log from this stale worker.
            logger.warning(
                "catalog_sync_terminal_transition_rejected",
                job_id=job.get("job_id"),
                action=action,
                transition="complete",
            )
            return True
        CATALOG_SYNC_COUNT.labels(action=action, status="completed").inc()
        CATALOG_SYNC_DURATION.labels(action=action).observe(time.monotonic() - started)
        logger.info(
            "catalog_sync_job_completed",
            job_id=job.get("job_id"),
            brand_id=job.get("brand_id"),
            action=job.get("action"),
        )
    except Exception as exc:
        if not await store.fail(
            job,
            error_code="catalog_sync_failed",
            error_type=type(exc).__name__,
        ):
            # The lease fence rejected this worker's failure transition.  Do
            # not publish stale failure observability as if it were terminal.
            logger.warning(
                "catalog_sync_terminal_transition_rejected",
                job_id=job.get("job_id"),
                action=action,
                transition="fail",
            )
            return True
        CATALOG_SYNC_COUNT.labels(action=action, status="failed").inc()
        CATALOG_SYNC_DURATION.labels(action=action).observe(time.monotonic() - started)
        logger.error(
            "catalog_sync_job_failed",
            job_id=job.get("job_id"),
            brand_id=job.get("brand_id"),
            action=job.get("action"),
            error_type=type(exc).__name__,
        )
    finally:
        stop_heartbeat.set()
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
    return True


async def run() -> None:
    settings = Settings()
    identifier = worker_id()
    await connection_manager.connect_mongodb()
    if connection_manager.system_db is None:
        raise RuntimeError("MongoDB is required for the catalog sync worker")
    store = CatalogSyncStore(settings)
    logger.info("catalog_sync_worker_started", worker_id=identifier)
    last_schedule_at = 0.0
    try:
        while True:
            try:
                now = time.monotonic()
                if now - last_schedule_at >= max(1.0, float(settings.CATALOG_SYNC_SCHEDULER_POLL_SECONDS)):
                    scheduled = await schedule_due_shopify_syncs(store, settings)
                    if scheduled:
                        logger.info("catalog_sync_jobs_scheduled", count=scheduled)
                    last_schedule_at = now
                processed = await run_once(store, settings, identifier=identifier)
            except CatalogSyncStoreUnavailableError:
                logger.warning("catalog_sync_store_unavailable")
                processed = False
            except Exception as exc:
                logger.error("catalog_sync_worker_iteration_failed", error_type=type(exc).__name__)
                processed = False
            if not processed:
                await asyncio.sleep(max(0.1, float(settings.CATALOG_SYNC_WORKER_POLL_SECONDS)))
    finally:
        await connection_manager.disconnect_mongodb()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
