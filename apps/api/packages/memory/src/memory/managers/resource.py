"""
Resource Memory Manager - Tools, APIs, capabilities

Features:
- Tool registry
- API endpoint management
- Capability tracking
- Tool invocation history
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
import structlog

from memory.config import MemoryConfig

logger = structlog.get_logger()


class ResourceMemory:
    """
    Resource memory manager for tools and APIs.
    
    Stores:
    - Tool definitions and schemas
    - API endpoints and authentication
    - Capability descriptions
    - Usage statistics
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize resource memory.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.collection = db[MemoryConfig.RESOURCE_MEMORY_COLLECTION]
        
        logger.info("Resource memory initialized")
    
    async def _ensure_indexes(self):
        """Create indexes for resource memory."""
        try:
            await self.collection.create_index("resource_id", unique=True)
            await self.collection.create_index("resource_type")  # tool, api, capability
            await self.collection.create_index("agent_id")
            await self.collection.create_index([
                ("enabled", 1),
                ("resource_type", 1)
            ])
            
            logger.debug("Resource memory indexes created")
            
        except Exception as e:
            logger.warning("Failed to create resource indexes", error=str(e))
    
    async def get_tool(self, tool_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific tool by ID.
        
        Args:
            tool_id: Resource ID
        
        Returns:
            Tool document or None
        """
        return await self.collection.find_one({
            "resource_id": tool_id,
            "resource_type": "tool"
        })
    
    async def get_available_tools(
        self,
        agent_id: Optional[str] = None,
        enabled_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get all available tools.
        
        Args:
            agent_id: Filter by agent (None = shared tools)
            enabled_only: Only return enabled tools
        
        Returns:
            List of tool documents
        """
        query: Dict[str, Any] = {"resource_type": "tool"}
        
        if enabled_only:
            query["enabled"] = True
        
        if agent_id:
            query["$or"] = [
                {"agent_id": agent_id},
                {"agent_id": None}  # Shared tools
            ]
        else:
            query["agent_id"] = None  # Only shared tools
        
        cursor = self.collection.find(query)
        tools = []
        
        async for doc in cursor:
            doc.pop("_id", None)
            tools.append(doc)
        
        return tools
    
    async def register_tool(
        self,
        resource_id: str,
        name: str,
        description: str,
        schema: Dict[str, Any],
        agent_id: Optional[str] = None,
        enabled: bool = True
    ) -> Dict[str, Any]:
        """
        Register a new tool.
        
        Args:
            resource_id: Unique tool identifier
            name: Tool name
            description: Tool description
            schema: OpenAI function calling schema
            agent_id: Agent this tool belongs to (None = shared)
            enabled: Whether tool is active
        
        Returns:
            Created tool document
        """
        tool = {
            "resource_id": resource_id,
            "resource_type": "tool",
            "name": name,
            "description": description,
            "schema": schema,
            "agent_id": agent_id,
            "enabled": enabled,
            "created_at": datetime.now(timezone.utc),
            "usage_count": 0,
            "last_used": None
        }
        
        await self.collection.update_one(
            {"resource_id": resource_id},
            {"$set": tool},
            upsert=True
        )
        
        logger.info("Tool registered", resource_id=resource_id, name=name)
        
        return tool
    
    async def record_tool_usage(
        self,
        resource_id: str,
        execution_time_ms: float,
        success: bool,
        error: Optional[str] = None
    ):
        """
        Record tool usage statistics.
        
        Args:
            resource_id: Tool ID
            execution_time_ms: Execution time in milliseconds
            success: Whether execution succeeded
            error: Error message if failed
        """
        update = {
            "$inc": {"usage_count": 1},
            "$set": {"last_used": datetime.now(timezone.utc)}
        }
        
        await self.collection.update_one(
            {"resource_id": resource_id},
            update
        )
        
        logger.debug("Tool usage recorded",
                    resource_id=resource_id,
                    execution_time_ms=execution_time_ms,
                    success=success)
