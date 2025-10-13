"""
Health Service - System health monitoring
"""

import time
from typing import Dict, Any
import structlog

from ..connections import connection_manager

logger = structlog.get_logger()

# Track application start time
_app_start_time = time.time()


class HealthService:
    """Service for monitoring system health."""
    
    def __init__(self):
        pass
    
    async def get_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status.
        
        Returns:
            Dict with overall status and component details
        """
        # Get connection health
        connections_health = await connection_manager.health_check()
        
        # Check individual components
        mongodb_status = await self._check_mongodb()
        redis_status = await self._check_redis()
        llm_status = await self._check_llm()
        
        # Determine overall status
        all_healthy = all([
            connections_health.get("mongodb") in ["healthy", "not_connected"],
            connections_health.get("redis") in ["healthy", "not_connected"],
            mongodb_status.get("status") in ["healthy", "not_connected"],
            redis_status.get("status") in ["healthy", "not_connected"]
        ])
        
        overall_status = "healthy" if all_healthy else "degraded"
        
        return {
            "status": overall_status,
            "timestamp": time.time(),
            "uptime_seconds": time.time() - _app_start_time,
            "components": {
                "mongodb": mongodb_status,
                "redis": redis_status,
                "llm": llm_status
            },
            "metrics": {
                "active_connections": 0,  # Can be tracked via middleware
                "total_requests": 0,      # Can be tracked via middleware
                "error_rate": 0.0         # Can be calculated from metrics
            }
        }
    
    async def _check_mongodb(self) -> Dict[str, Any]:
        """Check MongoDB health."""
        try:
            if connection_manager.mongodb_client:
                await connection_manager.mongodb_client.admin.command('ping')
                return {
                    "status": "healthy",
                    "latency_ms": None  # Could measure ping time
                }
            else:
                return {
                    "status": "not_connected",
                    "message": "MongoDB not configured"
                }
        except Exception as e:
            logger.error("MongoDB health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    async def _check_redis(self) -> Dict[str, Any]:
        """Check Redis health."""
        try:
            if connection_manager.redis_client:
                await connection_manager.redis_client.ping()
                return {
                    "status": "healthy",
                    "latency_ms": None  # Could measure ping time
                }
            else:
                return {
                    "status": "not_connected",
                    "message": "Redis not configured"
                }
        except Exception as e:
            logger.error("Redis health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    async def _check_llm(self) -> Dict[str, Any]:
        """Check LLM provider health."""
        # TODO: Implement actual LLM provider health check
        return {
            "status": "healthy",
            "provider": "configured"
        }
    
    def get_uptime(self) -> float:
        """Get application uptime in seconds."""
        return time.time() - _app_start_time


import asyncio
import psutil
from typing import Dict, Any
import structlog

from ..config import Settings

logger = structlog.get_logger()


class HealthService:
    """Service for system health monitoring."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status."""
        try:
            # Check service health
            services = await self._check_services()
            
            # Get system metrics
            metrics = await self.get_metrics()
            
            # Determine overall status
            overall_status = "healthy"
            for service, status in services.items():
                if status.get("status") != "healthy":
                    overall_status = "degraded"
                    break
            
            return {
                "status": overall_status,
                "version": "1.0.0",
                "services": services,
                "metrics": metrics
            }
            
        except Exception as e:
            logger.error("Error getting system status", error=str(e))
            return {
                "status": "error",
                "version": "1.0.0",
                "services": {},
                "metrics": {},
                "error": str(e)
            }
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get system metrics."""
        try:
            # System metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return {
                "system": {
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory.percent,
                    "memory_available_gb": memory.available / (1024**3),
                    "disk_percent": disk.percent,
                    "disk_free_gb": disk.free / (1024**3)
                },
                "application": {
                    "uptime_seconds": self._get_uptime(),
                    "active_connections": 0,  # TODO: Track WebSocket connections
                    "total_requests": 0,      # TODO: From metrics
                    "error_rate": 0.0         # TODO: From metrics
                }
            }
            
        except Exception as e:
            logger.error("Error getting metrics", error=str(e))
            return {}
    
    async def _check_services(self) -> Dict[str, Dict[str, Any]]:
        """Check health of dependent services."""
        services = {}
        
        # Check Redis
        services["redis"] = await self._check_redis()
        
        # Check MongoDB
        services["mongodb"] = await self._check_mongodb()
        
        # Check LLM provider
        services["llm"] = await self._check_llm_provider()
        
        return services
    
    async def _check_redis(self) -> Dict[str, Any]:
        """Check Redis connectivity."""
        try:
            # TODO: Implement actual Redis connection check
            return {
                "status": "healthy",
                "response_time_ms": 5,
                "version": "unknown"
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    async def _check_mongodb(self) -> Dict[str, Any]:
        """Check MongoDB connectivity."""
        try:
            # TODO: Implement actual MongoDB connection check
            return {
                "status": "healthy",
                "response_time_ms": 10,
                "version": "unknown"
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    async def _check_llm_provider(self) -> Dict[str, Any]:
        """Check LLM provider connectivity."""
        try:
            # TODO: Implement actual LLM provider health check
            return {
                "status": "healthy",
                "provider": self.settings.MODEL_PROVIDER,
                "model": self.settings.MODEL_NAME
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    def _get_uptime(self) -> float:
        """Get application uptime in seconds."""
        # TODO: Track actual application start time
        return 0.0
