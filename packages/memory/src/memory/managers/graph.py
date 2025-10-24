"""
Graph Memory Manager - Rules, policies, and escalation triggers

Features:
- Pattern-based rules (condition → action)
- Safety escalation triggers
- Priority-based rule matching
- Brand-specific rules
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
import structlog

from memory.types import GraphRule, EscalationTrigger
from memory.config import MemoryConfig

logger = structlog.get_logger()


class GraphMemory:
    """
    Graph memory manager.
    
    Stores:
    - Business rules (condition → action)
    - Safety escalation triggers
    - Policy references
    - Decision trees
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize graph memory.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.rules_collection = db[MemoryConfig.GRAPH_RULES_COLLECTION]
        self.escalations_collection = db[MemoryConfig.ESCALATIONS_COLLECTION]
        
        logger.info("Graph memory initialized")
    
    async def _ensure_indexes(self):
        """Create indexes for graph memory."""
        try:
            # Rules indexes
            await self.rules_collection.create_index("brand_id")
            await self.rules_collection.create_index([
                ("brand_id", 1),
                ("enabled", 1),
                ("priority", -1)
            ])
            
            # Escalations indexes
            await self.escalations_collection.create_index("enabled")
            await self.escalations_collection.create_index([
                ("enabled", 1),
                ("severity", 1)
            ])
            
            logger.debug("Graph memory indexes created")
            
        except Exception as e:
            logger.warning("Failed to create indexes", error=str(e))
    
    # =========================================================================
    # Rules Management
    # =========================================================================
    
    async def add_rule(
        self,
        brand_id: str,
        name: str,
        condition: Dict[str, Any],
        action: Dict[str, Any],
        priority: int = 0,
        enabled: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ) -> GraphRule:
        """
        Add a new rule.
        
        Args:
            brand_id: Brand this rule belongs to
            name: Human-readable rule name
            condition: Condition pattern to match
            action: Action to take when matched
            priority: Priority (higher = more important)
            enabled: Whether rule is active
            metadata: Optional metadata
        
        Returns:
            Created GraphRule
        """
        rule = GraphRule(
            id=str(uuid.uuid4()),
            brand_id=brand_id,
            name=name,
            condition=condition,
            action=action,
            priority=priority,
            enabled=enabled,
            metadata=metadata or {}
        )
        
        await self.rules_collection.insert_one(rule.dict())
        
        logger.info("Rule added",
                   brand_id=brand_id,
                   rule_name=name,
                   priority=priority)
        
        return rule
    
    async def get_rules(
        self,
        brand_id: str,
        enabled_only: bool = True
    ) -> List[GraphRule]:
        """
        Get all rules for a brand.
        
        Args:
            brand_id: Brand identifier
            enabled_only: Only return enabled rules
        
        Returns:
            List of GraphRule objects sorted by priority
        """
        query = {"brand_id": brand_id}
        if enabled_only:
            query["enabled"] = True
        
        cursor = self.rules_collection.find(query).sort("priority", -1)
        
        rules = []
        async for doc in cursor:
            doc.pop("_id", None)
            rules.append(GraphRule(**doc))
        
        logger.debug("Retrieved rules",
                    brand_id=brand_id,
                    count=len(rules))
        
        return rules
    
    async def match_rules(
        self,
        brand_id: str,
        context: Dict[str, Any],
        query: Optional[str] = None
    ) -> List[GraphRule]:
        """
        Match rules against a context.
        
        Args:
            brand_id: Brand identifier
            context: Context to match (e.g., user input, page_context)
            query: Optional user query to add to context
        
        Returns:
            List of matched rules sorted by priority
        """
        # Add query to context if provided
        if query:
            context = {**context, "query": query}
        
        rules = await self.get_rules(brand_id, enabled_only=True)
        matched = []
        
        for rule in rules:
            if self._match_condition(rule.condition, context):
                matched.append(rule)
                logger.debug("Rule matched",
                            rule_name=rule.name,
                            priority=rule.priority)
        
        return matched
    
    def _match_condition(
        self,
        condition: Dict[str, Any],
        context: Dict[str, Any]
    ) -> bool:
        """
        Check if a condition matches the context.
        
        Simple pattern matching:
        - condition: {"keywords": ["warranty", "return"]}
        - context: {"user_input": "what about the warranty?"}
        
        Returns:
            True if condition matches
        """
        # Keywords matching
        if "keywords" in condition:
            keywords = condition["keywords"]
            text = str(context).lower()
            
            # Check if any keyword is in context
            for keyword in keywords:
                if keyword.lower() in text:
                    return True
        
        # Exact field matching
        if "field_equals" in condition:
            for field, value in condition["field_equals"].items():
                if context.get(field) == value:
                    return True
        
        # Pattern matching
        if "pattern" in condition:
            import re
            text = str(context)
            if re.search(condition["pattern"], text, re.IGNORECASE):
                return True
        
        return False
    
    async def update_rule(self, rule_id: str, updates: Dict[str, Any]):
        """Update a rule."""
        await self.rules_collection.update_one(
            {"id": rule_id},
            {"$set": updates}
        )
        logger.debug("Rule updated", rule_id=rule_id)
    
    async def delete_rule(self, rule_id: str):
        """Delete a rule."""
        result = await self.rules_collection.delete_one({"id": rule_id})
        logger.debug("Rule deleted", rule_id=rule_id, deleted=result.deleted_count)
    
    # =========================================================================
    # Escalation Triggers
    # =========================================================================
    
    async def add_escalation_trigger(
        self,
        keywords: List[str],
        severity: str,
        action: str,
        message: str,
        enabled: bool = True
    ) -> EscalationTrigger:
        """
        Add a safety escalation trigger.
        
        Args:
            keywords: Keywords that trigger escalation
            severity: Escalation severity (low/medium/high/critical)
            action: Action to take
            message: Message to display
            enabled: Whether trigger is active
        
        Returns:
            Created EscalationTrigger
        """
        trigger = EscalationTrigger(
            id=str(uuid.uuid4()),
            keywords=keywords,
            severity=severity,
            action=action,
            message=message,
            enabled=enabled
        )
        
        await self.escalations_collection.insert_one(trigger.dict())
        
        logger.info("Escalation trigger added",
                   keywords=keywords,
                   severity=severity)
        
        return trigger
    
    async def get_escalation_triggers(
        self,
        enabled_only: bool = True
    ) -> List[EscalationTrigger]:
        """Get all escalation triggers."""
        query = {}
        if enabled_only:
            query["enabled"] = True
        
        cursor = self.escalations_collection.find(query)
        
        triggers = []
        async for doc in cursor:
            doc.pop("_id", None)
            triggers.append(EscalationTrigger(**doc))
        
        return triggers
    
    async def check_escalation(self, text: str) -> List[EscalationTrigger]:
        """
        Check if text triggers any escalations.
        
        Args:
            text: Text to check (user input)
        
        Returns:
            List of triggered escalations
        """
        triggers = await self.get_escalation_triggers(enabled_only=True)
        matched = []
        text_lower = text.lower()
        
        for trigger in triggers:
            # Check if any keyword is in text
            for keyword in trigger.keywords:
                if keyword.lower() in text_lower:
                    matched.append(trigger)
                    logger.warning("Escalation triggered",
                                  severity=trigger.severity,
                                  keyword=keyword,
                                  action=trigger.action)
                    break  # One match per trigger is enough
        
        # Sort by severity
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        matched.sort(key=lambda t: severity_order.get(t.severity, 0), reverse=True)
        
        return matched
    
    async def seed_default_escalations(self):
        """Seed default safety escalation triggers."""
        default_escalations = [
            {
                "keywords": ["gas smell", "smell gas", "gas leak", "gas odor"],
                "severity": "critical",
                "action": "escalate_emergency",
                "message": "⚠️ SAFETY ALERT: If you smell gas, leave immediately and call emergency services (911) or your gas company. Do not use electrical switches or create sparks."
            },
            {
                "keywords": ["visible sparking", "electrical spark", "sparks flying", "wire sparking"],
                "severity": "critical",
                "action": "escalate_emergency",
                "message": "⚠️ ELECTRICAL HAZARD: Turn off power at the breaker immediately. Do not touch electrical components. Call a licensed electrician."
            },
            {
                "keywords": ["water leak", "pipe burst", "flooding", "water everywhere"],
                "severity": "high",
                "action": "escalate_technician",
                "message": "⚠️ URGENT: Turn off the main water supply immediately. Contact a plumber as soon as possible to prevent water damage."
            },
            {
                "keywords": ["no hot water", "water heater broken", "cold water only"],
                "severity": "medium",
                "action": "troubleshoot_guide",
                "message": "Let me help you troubleshoot your water heater. First, check if the pilot light is on (for gas heaters) or if the circuit breaker is tripped (for electric heaters)."
            },
            {
                "keywords": ["warranty claim", "warranty issue", "defect", "product failure"],
                "severity": "low",
                "action": "show_warranty_policy",
                "message": "I'll help you with your warranty claim. Our products come with a comprehensive warranty. Let me get you the details."
            }
        ]
        
        for escalation in default_escalations:
            # Check if already exists
            existing = await self.escalations_collection.find_one({
                "keywords": escalation["keywords"]
            })
            
            if not existing:
                await self.add_escalation_trigger(**escalation)
        
        logger.info("Default escalation triggers seeded")
    
    async def get_rule_stats(self, brand_id: str) -> Dict[str, Any]:
        """Get statistics for brand rules."""
        total = await self.rules_collection.count_documents({"brand_id": brand_id})
        enabled = await self.rules_collection.count_documents({
            "brand_id": brand_id,
            "enabled": True
        })
        
        return {
            "brand_id": brand_id,
            "total_rules": total,
            "enabled_rules": enabled,
            "disabled_rules": total - enabled
        }
