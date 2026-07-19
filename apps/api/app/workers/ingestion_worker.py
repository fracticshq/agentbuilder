"""Standalone restart-safe worker for Mongo-backed document ingestion."""

from __future__ import annotations

import asyncio
import os
import socket
import uuid

import structlog

from app.config import Settings
from app.connections import connection_manager
from app.services.ingestion_service import IngestionService
from app.services.job_store import JobStoreUnavailableError

logger = structlog.get_logger(__name__)


def worker_id() -> str:
    return os.getenv("INGESTION_WORKER_ID") or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"


async def run() -> None:
    settings = Settings()
    identifier = worker_id()
    service = IngestionService(settings)
    await connection_manager.connect_mongodb()
    if connection_manager.system_db is None:
        raise RuntimeError("MongoDB is required for the ingestion worker")
    logger.info("ingestion_worker_started", worker_id=identifier)
    try:
        while True:
            try:
                processed = await service.process_next_durable_job(worker_id=identifier)
            except JobStoreUnavailableError:
                # Nothing is acknowledged locally; an expired Mongo lease is
                # reclaimable by this or another worker when connectivity returns.
                logger.warning("ingestion_worker_store_unavailable")
                processed = False
            except Exception as exc:
                logger.error("ingestion_worker_iteration_failed", error_type=type(exc).__name__)
                processed = False
            if not processed:
                await asyncio.sleep(max(0.1, float(settings.INGESTION_WORKER_POLL_SECONDS)))
    finally:
        await connection_manager.disconnect_mongodb()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
