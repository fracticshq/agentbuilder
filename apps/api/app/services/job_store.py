"""
Redis-backed job store for background task tracking.

Replaces in-process dict so job status survives across multiple API instances.
Falls back to in-memory if Redis is unavailable (dev/test convenience).

TTL: 24 hours — jobs older than that are purged automatically.
"""

import json
from typing import Optional, Dict, Any
from datetime import datetime
import structlog

from ..connections import connection_manager

logger = structlog.get_logger()

JOB_TTL_SECONDS = 86400  # 24 hours
KEY_PREFIX = "job:"


class JobStore:
    """Thread-safe job state store backed by Redis with in-memory fallback."""

    def __init__(self):
        self._fallback: Dict[str, Dict[str, Any]] = {}

    def _key(self, job_id: str) -> str:
        return f"{KEY_PREFIX}{job_id}"

    async def set(self, job_id: str, data: Dict[str, Any]) -> None:
        redis = connection_manager.redis_client
        if redis:
            try:
                await redis.set(self._key(job_id), json.dumps(data, default=str), ex=JOB_TTL_SECONDS)
                return
            except Exception as e:
                logger.warning("job_store_redis_write_failed", job_id=job_id, error=str(e))
        self._fallback[job_id] = data

    async def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        redis = connection_manager.redis_client
        if redis:
            try:
                raw = await redis.get(self._key(job_id))
                if raw:
                    return json.loads(raw)
                return None
            except Exception as e:
                logger.warning("job_store_redis_read_failed", job_id=job_id, error=str(e))
        return self._fallback.get(job_id)

    async def update(self, job_id: str, updates: Dict[str, Any]) -> None:
        current = await self.get(job_id) or {}
        current.update(updates)
        await self.set(job_id, current)

    async def delete(self, job_id: str) -> None:
        redis = connection_manager.redis_client
        if redis:
            try:
                await redis.delete(self._key(job_id))
                return
            except Exception as e:
                logger.warning("job_store_redis_delete_failed", job_id=job_id, error=str(e))
        self._fallback.pop(job_id, None)
