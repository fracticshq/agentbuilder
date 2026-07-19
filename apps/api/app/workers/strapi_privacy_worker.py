"""Lease-fenced processor for the dedicated Strapi privacy outbox."""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from typing import Any

import structlog

from app.config import Settings
from app.connections import connection_manager
from app.services.strapi_privacy_client import StrapiPrivacyClient, StrapiPrivacyRequestError
from app.services.strapi_privacy_store import StrapiPrivacyStore, StrapiPrivacyStoreError

logger = structlog.get_logger(__name__)


def worker_id() -> str:
    return os.getenv("STRAPI_PRIVACY_WORKER_ID") or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"


async def _maintain_lease(
    store: StrapiPrivacyStore,
    request: dict[str, Any],
    settings: Settings,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    interval = max(5.0, min(30.0, float(settings.STRAPI_PRIVACY_LEASE_SECONDS) / 3))
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        try:
            if not await store.renew_lease(request):
                lease_lost.set()
                logger.warning("strapi_privacy_lease_lost", request_id=request.get("request_id"))
                return
        except StrapiPrivacyStoreError:
            lease_lost.set()
            logger.warning("strapi_privacy_lease_renewal_unavailable", request_id=request.get("request_id"))
            return


async def run_once(
    store: StrapiPrivacyStore,
    settings: Settings,
    *,
    identifier: str,
    client: StrapiPrivacyClient | None = None,
) -> bool:
    """Process one request only when the explicit mode is active.

    ``contract_pending`` and ``disabled`` return before constructing a client
    or claiming a request, guaranteeing no outbound traffic in the default
    deployment mode.
    """
    if settings.STRAPI_PRIVACY_MODE != "active":
        return False
    client = client or StrapiPrivacyClient(settings)
    request = await store.claim_next(worker_id=identifier)
    if not request:
        return False
    stop_heartbeat = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat = asyncio.create_task(_maintain_lease(store, request, settings, stop_heartbeat, lease_lost))
    try:
        receipt = await client.request_deletion(request)
        if lease_lost.is_set():
            raise StrapiPrivacyRequestError("Strapi privacy lease was lost")
        if not await store.complete(request, receipt=receipt):
            logger.warning("strapi_privacy_completion_fenced", request_id=request.get("request_id"))
        else:
            logger.info("strapi_privacy_request_completed", request_id=request.get("request_id"))
    except Exception as exc:
        await store.retry_or_fail(
            request,
            error_code="strapi_privacy_request_failed",
            error_type=type(exc).__name__,
        )
        logger.warning(
            "strapi_privacy_request_pending",
            request_id=request.get("request_id"),
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
    # Constructing Settings in active mode validates the independent endpoint,
    # signing key and Ed25519 pin before any connection or outbound request.
    await connection_manager.connect_mongodb()
    if connection_manager.system_db is None:
        raise RuntimeError("MongoDB is required for the Strapi privacy worker")
    store = StrapiPrivacyStore(settings)
    client = StrapiPrivacyClient(settings) if settings.STRAPI_PRIVACY_MODE == "active" else None
    logger.info("strapi_privacy_worker_started", worker_id=identifier, mode=settings.STRAPI_PRIVACY_MODE)
    try:
        while True:
            try:
                processed = await run_once(store, settings, identifier=identifier, client=client)
            except StrapiPrivacyStoreError:
                logger.warning("strapi_privacy_store_unavailable")
                processed = False
            except Exception as exc:
                logger.error("strapi_privacy_worker_iteration_failed", error_type=type(exc).__name__)
                processed = False
            if not processed:
                await asyncio.sleep(max(0.1, float(settings.STRAPI_PRIVACY_WORKER_POLL_SECONDS)))
    finally:
        await connection_manager.disconnect_mongodb()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
