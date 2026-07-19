"""Truthful dependency and queue health for operator-facing status endpoints."""

from __future__ import annotations

import time
from typing import Any, Dict

import psutil
import structlog

from app.config import Settings
from app.connections import connection_manager
from app.services.catalog_sync_store import CATALOG_SYNC_COLLECTION, CATALOG_SYNC_KIND

logger = structlog.get_logger(__name__)
_APP_STARTED_AT = time.monotonic()


class HealthService:
    """Report observed dependency state without pretending external systems passed."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def get_system_status(self) -> Dict[str, Any]:
        services = await self._check_services()
        required = {
            "mongodb": bool(self.settings.REQUIRE_MONGODB),
            "redis": bool(self.settings.REQUIRE_REDIS),
        }
        unhealthy_required = any(
            required.get(name, False) and value.get("status") != "healthy"
            for name, value in services.items()
        )
        return {
            "status": "degraded" if unhealthy_required else "healthy",
            "version": "1.0.0",
            "services": services,
            "metrics": await self.get_metrics(),
        }

    async def get_metrics(self) -> Dict[str, Any]:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        metrics: Dict[str, Any] = {
            "system": {
                # interval=None is a non-blocking rolling sample; status APIs
                # must never pause a worker thread for one second.
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_percent": memory.percent,
                "memory_available_gb": round(memory.available / (1024**3), 3),
                "disk_percent": disk.percent,
                "disk_free_gb": round(disk.free / (1024**3), 3),
            },
            "application": {"uptime_seconds": round(time.monotonic() - _APP_STARTED_AT, 3)},
        }
        metrics["catalog_sync"] = await self._catalog_sync_backlog()
        return metrics

    async def _check_services(self) -> Dict[str, Dict[str, Any]]:
        return {
            "mongodb": await self._check_mongodb(),
            "redis": await self._check_redis(),
            # Deliberately not a network probe: a status request must not spend
            # a provider token or make LLM availability look healthy on faith.
            "llm": {
                "status": "configured",
                "provider": self.settings.DEFAULT_LLM_PROVIDER,
                "model": self.settings.AZURE_OPENAI_MODEL if self.settings.DEFAULT_LLM_PROVIDER == "azure_openai" else self.settings.OPENAI_MODEL,
            },
        }

    async def _check_mongodb(self) -> Dict[str, Any]:
        client = connection_manager.mongodb_client
        if client is None:
            return {"status": "not_connected"}
        started = time.monotonic()
        try:
            await client.admin.command("ping")
            return {"status": "healthy", "latency_ms": round((time.monotonic() - started) * 1000, 2)}
        except Exception as exc:
            logger.warning("health_mongodb_failed", error_type=type(exc).__name__)
            return {"status": "unhealthy"}

    async def _check_redis(self) -> Dict[str, Any]:
        client = connection_manager.redis_client
        if client is None:
            return {"status": "not_connected"}
        started = time.monotonic()
        try:
            await client.ping()
            return {"status": "healthy", "latency_ms": round((time.monotonic() - started) * 1000, 2)}
        except Exception as exc:
            logger.warning("health_redis_failed", error_type=type(exc).__name__)
            return {"status": "unhealthy"}

    async def _catalog_sync_backlog(self) -> Dict[str, Any]:
        try:
            collection = connection_manager.get_system_db()[CATALOG_SYNC_COLLECTION]
            queued = await collection.count_documents({"kind": CATALOG_SYNC_KIND, "status": "queued"})
            running = await collection.count_documents({"kind": CATALOG_SYNC_KIND, "status": "running"})
            failed = await collection.count_documents({"kind": CATALOG_SYNC_KIND, "status": "error"})
            return {"status": "available", "queued": queued, "running": running, "failed": failed}
        except Exception as exc:
            logger.warning("health_catalog_sync_backlog_unavailable", error_type=type(exc).__name__)
            return {"status": "unavailable"}
