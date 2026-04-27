"""
Procedural Memory Manager - Workflows, SOPs, task steps

Features:
- Step-by-step workflows
- Standard Operating Procedures (SOPs)
- Task execution sequences
- Conditional branching
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
import structlog

from memory.config import MemoryConfig

logger = structlog.get_logger()


class ProceduralMemory:
    """
    Procedural memory manager for workflows and SOPs.
    
    Stores:
    - Installation workflows
    - Troubleshooting procedures
    - Task sequences
    - Conditional logic
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize procedural memory.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.collection = db[MemoryConfig.PROCEDURAL_MEMORY_COLLECTION]
        
        logger.info("Procedural memory initialized")
    
    async def _ensure_indexes(self):
        """Create indexes for procedural memory."""
        try:
            await self.collection.create_index("instruction_id", unique=True)
            await self.collection.create_index("instruction_type")  # workflow, sop, task
            await self.collection.create_index("agent_id")
            await self.collection.create_index("priority")
            await self.collection.create_index([
                ("enabled", 1),
                ("priority", -1)
            ])
            
            logger.debug("Procedural memory indexes created")
            
        except Exception as e:
            logger.warning("Failed to create procedural indexes", error=str(e))
    
    async def get_workflow(
        self,
        workflow_id: Optional[str] = None,
        name: Optional[str] = None,
        instruction_type: str = "workflow"
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific workflow or SOP.
        
        Args:
            workflow_id: Instruction ID
            name: Workflow name
            instruction_type: Type (workflow, sop, task)
        
        Returns:
            Workflow document or None
        """
        query: Dict[str, Any] = {"instruction_type": instruction_type}
        
        if workflow_id:
            query["instruction_id"] = workflow_id
        elif name:
            query["name"] = name
        else:
            return None
        
        return await self.collection.find_one(query)
    
    async def get_workflows_by_context(
        self,
        context: Dict[str, Any],
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find workflows matching the current context.
        
        Args:
            context: Context data (product_type, query_keywords, etc.)
            limit: Maximum workflows to return
        
        Returns:
            List of matching workflows
        """
        # Simple matching for now - can be enhanced with semantic search
        query: Dict[str, Any] = {
            "enabled": True,
            "instruction_type": {"$in": ["workflow", "sop"]}
        }
        
        cursor = self.collection.find(query).sort("priority", -1).limit(limit)
        workflows = []
        
        async for doc in cursor:
            doc.pop("_id", None)
            workflows.append(doc)
        
        return workflows
    
    async def execute_step(
        self,
        workflow: Dict[str, Any],
        current_step: int,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a specific step in a workflow.
        
        Args:
            workflow: Workflow document
            current_step: Current step number
            context: Execution context
        
        Returns:
            Step execution result with next_step info
        """
        steps = workflow.get("steps", [])
        step_data = next((s for s in steps if s["step_number"] == current_step), None)
        
        if not step_data:
            return {
                "status": "error",
                "message": "Step not found",
                "current_step": current_step
            }
        
        # Check conditions
        conditions = step_data.get("conditions", {})
        if conditions and not self._evaluate_conditions(conditions, context):
            # Skip to next step
            next_step = step_data.get("next_step")
            return {
                "status": "skipped",
                "message": "Conditions not met",
                "current_step": current_step,
                "next_step": next_step
            }
        
        # Return step info for execution
        return {
            "status": "ready",
            "action": step_data.get("action"),
            "current_step": current_step,
            "next_step": step_data.get("next_step"),
            "details": step_data
        }
    
    def _evaluate_conditions(self, conditions: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Evaluate workflow conditions.
        
        Simple key-value matching for now. Can be enhanced with expression evaluation.
        """
        if not conditions:
            return True
        
        # Check "if" condition
        if_condition = conditions.get("if")
        if if_condition:
            # Parse simple conditions like "key == value"
            for key, value in context.items():
                if f"{key} == {value}" in if_condition or f"{key} == '{value}'" in if_condition:
                    return True
        
        return False
