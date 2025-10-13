"""
Connection Manager for MongoDB and Redis
"""

import os
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


class ConnectionManager:
    """Manages database and cache connections."""
    
    def __init__(self):
        self.mongodb_client: Optional[AsyncIOMotorClient] = None
        self.mongodb_db = None
        self.redis_client: Optional[aioredis.Redis] = None
        logger.info("Connection manager initialized")
    
    async def connect_mongodb(self) -> None:
        """Initialize MongoDB connection."""
        try:
            mongodb_uri = os.getenv("MONGODB_URI")
            if not mongodb_uri:
                logger.warning("MONGODB_URI not set, MongoDB features will be unavailable")
                return
            
            db_name = os.getenv("MONGODB_DATABASE", "agent-builder")
            
            self.mongodb_client = AsyncIOMotorClient(
                mongodb_uri,
                maxPoolSize=50,
                minPoolSize=10,
                serverSelectionTimeoutMS=5000
            )
            
            # Test connection
            await self.mongodb_client.admin.command('ping')
            self.mongodb_db = self.mongodb_client[db_name]
            
            logger.info(
                "MongoDB connected successfully",
                database=db_name,
                host=mongodb_uri.split('@')[-1].split('/')[0] if '@' in mongodb_uri else "localhost"
            )
            
        except Exception as e:
            logger.error("MongoDB connection failed", error=str(e))
            self.mongodb_client = None
            self.mongodb_db = None
            # Don't raise - allow app to start without MongoDB
    
    async def connect_redis(self) -> None:
        """Initialize Redis connection."""
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            
            self.redis_client = await aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            
            # Test connection
            await self.redis_client.ping()
            
            logger.info(
                "Redis connected successfully",
                url=redis_url.split('@')[-1] if '@' in redis_url else redis_url
            )
            
        except Exception as e:
            logger.warning("Redis connection failed, caching will be disabled", error=str(e))
            self.redis_client = None
            # Don't raise - allow app to start without Redis
    
    async def disconnect_mongodb(self) -> None:
        """Close MongoDB connection."""
        if self.mongodb_client:
            self.mongodb_client.close()
            logger.info("MongoDB disconnected")
    
    async def disconnect_redis(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis disconnected")
    
    async def close_all(self) -> None:
        """Close all connections."""
        await self.disconnect_mongodb()
        await self.disconnect_redis()
        logger.info("All connections closed")
    
    def get_mongodb_db(self):
        """Get MongoDB database instance."""
        if not self.mongodb_db:
            raise RuntimeError("MongoDB not connected")
        return self.mongodb_db
    
    def get_redis_client(self):
        """Get Redis client instance."""
        if not self.redis_client:
            raise RuntimeError("Redis not connected")
        return self.redis_client
    
    async def health_check(self) -> dict:
        """Check health of all connections."""
        health = {
            "mongodb": "unknown",
            "redis": "unknown"
        }
        
        # Check MongoDB
        if self.mongodb_client:
            try:
                await self.mongodb_client.admin.command('ping')
                health["mongodb"] = "healthy"
            except Exception as e:
                logger.error("MongoDB health check failed", error=str(e))
                health["mongodb"] = "unhealthy"
        else:
            health["mongodb"] = "not_connected"
        
        # Check Redis
        if self.redis_client:
            try:
                await self.redis_client.ping()
                health["redis"] = "healthy"
            except Exception as e:
                logger.error("Redis health check failed", error=str(e))
                health["redis"] = "unhealthy"
        else:
            health["redis"] = "not_connected"
        
        return health


# Global connection manager instance
connection_manager = ConnectionManager()


async def get_mongodb():
    """Dependency to get MongoDB database."""
    return connection_manager.get_mongodb_db()


async def get_redis():
    """Dependency to get Redis client."""
    return connection_manager.get_redis_client()
