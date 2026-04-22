"""
Connection Manager for MongoDB and Redis
Supports brand-isolated databases with caching
"""

import os
from typing import Optional, Dict
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import redis.asyncio as aioredis
import structlog

from .config import Settings

logger = structlog.get_logger()
settings = Settings()


class ConnectionManager:
    """Manages database and cache connections with brand isolation."""
    
    def __init__(self):
        self.mongodb_client: Optional[AsyncIOMotorClient] = None
        self.system_db: Optional[AsyncIOMotorDatabase] = None
        self.brand_db_cache: Dict[str, AsyncIOMotorDatabase] = {}
        self.redis_client: Optional[aioredis.Redis] = None
        logger.info("Connection manager initialized")
    
    async def connect_mongodb(self) -> None:
        """Initialize MongoDB connection and system database."""
        try:
            mongodb_uri = os.getenv("MONGODB_URI")
            if not mongodb_uri:
                logger.warning("MONGODB_URI not set, MongoDB features will be unavailable")
                return
            
            system_db_name = os.getenv("MONGO_SYSTEM_DB", "system")
            
            self.mongodb_client = AsyncIOMotorClient(
                mongodb_uri,
                maxPoolSize=50,
                minPoolSize=1,
                serverSelectionTimeoutMS=5000,
                heartbeatFrequencyMS=30000,
            )
            
            # Test connection
            await self.mongodb_client.admin.command('ping')
            
            # Initialize system database (for brands, users, etc.)
            self.system_db = self.mongodb_client[system_db_name]
            
            logger.info(
                "MongoDB connected successfully",
                system_database=system_db_name,
                host=mongodb_uri.split('@')[-1].split('/')[0] if '@' in mongodb_uri else "localhost"
            )
            
        except Exception as e:
            logger.error("MongoDB connection failed", error=str(e))
            self.mongodb_client = None
            self.system_db = None
            self.brand_db_cache.clear()
            if settings.REQUIRE_MONGODB:
                raise RuntimeError("MongoDB connection is required") from e
    
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
            if settings.REQUIRE_REDIS:
                raise RuntimeError("Redis connection is required") from e
    
    async def disconnect_mongodb(self) -> None:
        """Close MongoDB connection and clear cache."""
        if self.mongodb_client:
            self.mongodb_client.close()
            self.system_db = None
            self.brand_db_cache.clear()
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
    
    def get_system_db(self) -> AsyncIOMotorDatabase:
        """Get system database instance for brands, users, etc."""
        if self.system_db is None:
            raise RuntimeError("MongoDB not connected")
        return self.system_db
    
    def get_brand_db(self, brand_slug: str) -> AsyncIOMotorDatabase:
        """Get brand-specific database instance with caching."""
        if self.mongodb_client is None:
            raise RuntimeError("MongoDB not connected")
        
        # Check cache first
        if brand_slug in self.brand_db_cache:
            return self.brand_db_cache[brand_slug]
        
        # Create new database connection
        brand_db = self.mongodb_client[brand_slug]
        self.brand_db_cache[brand_slug] = brand_db
        
        logger.debug("Brand database cached", brand=brand_slug)
        return brand_db
    
    async def get_brand_db_by_agent_id(self, agent_id: str) -> AsyncIOMotorDatabase:
        """Get brand database by looking up agent's brand."""
        system_db = self.get_system_db()
        
        # Find agent in system database (using "id" field, not "_id")
        agent = await system_db.agents.find_one({"id": agent_id})
        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")
        
        brand_slug = agent.get("brand_slug")
        if not brand_slug:
            raise ValueError(f"Agent {agent_id} has no brand_slug")
        
        return self.get_brand_db(brand_slug)
    
    def get_mongodb_db(self):
        """Legacy method - deprecated. Use get_system_db() or get_brand_db() instead."""
        logger.warning("get_mongodb_db() is deprecated. Use get_system_db() or get_brand_db() instead.")
        return self.get_system_db()
    
    def get_redis_client(self):
        """Get Redis client instance."""
        if self.redis_client is None:
            raise RuntimeError("Redis not connected")
        return self.redis_client

    async def get_redis(self):
        """Compatibility helper for callers that expect an async Redis getter."""
        return self.get_redis_client()
    
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
    """Legacy dependency - deprecated. Use get_system_db or get_brand_db instead."""
    return connection_manager.get_mongodb_db()


async def get_system_db():
    """Dependency to get system database."""
    return connection_manager.get_system_db()


def get_brand_db(brand_slug: str):
    """Dependency factory to get brand-specific database."""
    return connection_manager.get_brand_db(brand_slug)


async def get_brand_db_by_agent(agent_id: str):
    """Dependency to get brand database by agent ID."""
    return await connection_manager.get_brand_db_by_agent_id(agent_id)


async def get_redis():
    """Dependency to get Redis client."""
    return connection_manager.get_redis_client()
