"""
Episodic Memory Manager - Store and retrieve user facts with PII vaulting

Features:
- Fact extraction with confidence ≥ 0.70
- PII encryption for sensitive facts
- TTL: 90 days
- GDPR delete support
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase
import structlog

from memory.types import EpisodicFact, Message
from memory.config import MemoryConfig
from memory.processors.entity_extractor import EntityExtractor
from memory.processors.pii_vault import get_pii_vault

logger = structlog.get_logger()


class EpisodicMemory:
    """
    Episodic memory manager.
    
    Features:
    - Store user facts and preferences
    - Confidence threshold: ≥ 0.70
    - PII vaulting (encryption)
    - TTL: 90 days
    - GDPR compliance
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize episodic memory.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.collection = db[MemoryConfig.EPISODIC_COLLECTION]
        self.pii_vault = get_pii_vault() if MemoryConfig.ENABLE_PII_VAULTING else None
        
        logger.info("Episodic memory initialized",
                   ttl_days=MemoryConfig.EPISODIC_TTL / (24 * 3600),
                   confidence_threshold=MemoryConfig.CONFIDENCE_THRESHOLD,
                   pii_vaulting=MemoryConfig.ENABLE_PII_VAULTING)
    
    async def _ensure_indexes(self):
        """Create indexes for episodic memory."""
        try:
            # Index on user_id for fast retrieval
            await self.collection.create_index("user_id")
            
            # Index on conversation_id
            await self.collection.create_index("conversation_id")
            
            # TTL index for automatic cleanup (90 days)
            await self.collection.create_index(
                "expires_at",
                expireAfterSeconds=0  # Document defines its own expiration
            )
            
            # Compound index for user facts by type
            await self.collection.create_index([
                ("user_id", 1),
                ("fact_type", 1),
                ("confidence", -1)
            ])
            
            logger.debug("Episodic memory indexes created")
            
        except Exception as e:
            logger.warning("Failed to create indexes", error=str(e))
    
    async def extract_and_store_facts(
        self,
        messages: List[Message],
        user_id: str,
        conversation_id: str
    ) -> List[EpisodicFact]:
        """
        Extract facts from messages and store them.
        
        Args:
            messages: Recent messages to analyze
            user_id: User identifier
            conversation_id: Conversation identifier
        
        Returns:
            List of stored facts
        """
        if not MemoryConfig.ENABLE_FACT_EXTRACTION:
            logger.debug("Fact extraction disabled")
            return []
        
        # Combine user messages for analysis
        user_messages = [m for m in messages if m.role.value == "user"]
        if not user_messages:
            return []
        
        text = " ".join([m.content for m in user_messages])
        
        # Extract facts
        facts = EntityExtractor.extract_facts(text, user_id, conversation_id)
        
        if not facts:
            logger.debug("No facts extracted", user_id=user_id)
            return []
        
        # Merge similar facts
        facts = EntityExtractor.merge_similar_facts(facts)
        
        # Store facts
        stored_facts = []
        for fact in facts:
            stored = await self.store_fact(fact)
            if stored:
                stored_facts.append(stored)
        
        logger.info("Facts stored",
                   user_id=user_id,
                   conversation_id=conversation_id,
                   count=len(stored_facts))
        
        return stored_facts
    
    async def store_fact(self, fact: EpisodicFact) -> Optional[EpisodicFact]:
        """
        Store a single fact.
        
        Args:
            fact: EpisodicFact to store
        
        Returns:
            Stored fact or None if rejected
        """
        # Validate confidence threshold
        if fact.confidence < MemoryConfig.CONFIDENCE_THRESHOLD:
            logger.debug("Fact rejected - low confidence",
                        fact_type=fact.fact_type,
                        confidence=fact.confidence,
                        threshold=MemoryConfig.CONFIDENCE_THRESHOLD)
            return None
        
        # Check user fact limit
        user_fact_count = await self.collection.count_documents({"user_id": fact.user_id})
        if user_fact_count >= MemoryConfig.MAX_FACTS_PER_USER:
            logger.warning("User fact limit reached",
                          user_id=fact.user_id,
                          limit=MemoryConfig.MAX_FACTS_PER_USER)
            # Delete oldest fact
            await self._delete_oldest_fact(fact.user_id)
        
        # Prepare document
        fact_doc = fact.dict()
        
        # Encrypt PII if needed
        if fact.pii_encrypted and self.pii_vault and self.pii_vault.enabled:
            try:
                # Encrypt the fact value
                pii_field = self.pii_vault.encrypt_field(fact.fact, "fact")
                fact_doc["fact"] = pii_field.dict()
                fact_doc["pii_encrypted"] = True
                logger.debug("Fact PII encrypted", fact_id=fact.id)
            except Exception as e:
                logger.error("Failed to encrypt fact PII", error=str(e))
                # Store unencrypted as fallback (log warning)
                logger.warning("Storing fact without encryption")
        
        # Insert into database
        try:
            await self.collection.insert_one(fact_doc)
            logger.debug("Fact stored",
                        user_id=fact.user_id,
                        fact_type=fact.fact_type,
                        confidence=fact.confidence)
            return fact
        except Exception as e:
            logger.error("Failed to store fact", error=str(e))
            return None
    
    async def get_user_facts(
        self,
        user_id: str,
        fact_types: Optional[List[str]] = None,
        min_confidence: Optional[float] = None
    ) -> List[EpisodicFact]:
        """
        Get all facts for a user.
        
        Args:
            user_id: User identifier
            fact_types: Optional filter by fact types
            min_confidence: Optional minimum confidence threshold
        
        Returns:
            List of EpisodicFact objects
        """
        # Build query
        query = {"user_id": user_id}
        
        if fact_types:
            query["fact_type"] = {"$in": fact_types}
        
        if min_confidence:
            query["confidence"] = {"$gte": min_confidence}
        
        # Retrieve facts
        cursor = self.collection.find(query).sort("confidence", -1)
        
        facts = []
        async for doc in cursor:
            try:
                doc.pop("_id", None)
                
                # Decrypt PII if needed
                if doc.get("pii_encrypted") and isinstance(doc.get("fact"), dict):
                    if self.pii_vault and self.pii_vault.enabled:
                        try:
                            from memory.types import PIIField
                            pii_field = PIIField(**doc["fact"])
                            doc["fact"] = self.pii_vault.decrypt_field(pii_field)
                        except Exception as e:
                            logger.error("Failed to decrypt fact", error=str(e))
                            doc["fact"] = "[ENCRYPTED]"
                
                facts.append(EpisodicFact(**doc))
            except Exception as e:
                logger.warning("Failed to parse fact", error=str(e))
        
        logger.debug("Retrieved user facts",
                    user_id=user_id,
                    count=len(facts))
        
        return facts
    
    async def get_fact_by_id(self, fact_id: str) -> Optional[EpisodicFact]:
        """Get a specific fact by ID."""
        doc = await self.collection.find_one({"id": fact_id})
        
        if doc:
            doc.pop("_id", None)
            
            # Decrypt PII if needed
            if doc.get("pii_encrypted") and isinstance(doc.get("fact"), dict):
                if self.pii_vault and self.pii_vault.enabled:
                    try:
                        from memory.types import PIIField
                        pii_field = PIIField(**doc["fact"])
                        doc["fact"] = self.pii_vault.decrypt_field(pii_field)
                    except Exception as e:
                        logger.error("Failed to decrypt fact", error=str(e))
            
            return EpisodicFact(**doc)
        
        return None
    
    async def delete_fact(self, fact_id: str):
        """Delete a specific fact."""
        result = await self.collection.delete_one({"id": fact_id})
        logger.debug("Fact deleted", fact_id=fact_id, deleted=result.deleted_count)
    
    async def delete_user_data(self, user_id: str) -> int:
        """
        Delete all data for a user (GDPR compliance).
        
        Args:
            user_id: User identifier
        
        Returns:
            Number of facts deleted
        """
        result = await self.collection.delete_many({"user_id": user_id})
        
        logger.info("User data deleted (GDPR)",
                   user_id=user_id,
                   facts_deleted=result.deleted_count)
        
        return result.deleted_count
    
    async def _delete_oldest_fact(self, user_id: str):
        """Delete the oldest fact for a user."""
        oldest = await self.collection.find_one(
            {"user_id": user_id},
            sort=[("created_at", 1)]
        )
        
        if oldest:
            await self.collection.delete_one({"_id": oldest["_id"]})
            logger.debug("Oldest fact deleted", user_id=user_id)
    
    async def get_facts_summary(self, user_id: str) -> Dict[str, Any]:
        """
        Get summary of user's facts.
        
        Args:
            user_id: User identifier
        
        Returns:
            Dictionary with fact statistics
        """
        facts = await self.get_user_facts(user_id)
        
        if not facts:
            return {
                "user_id": user_id,
                "total_facts": 0,
                "fact_types": {},
                "avg_confidence": 0.0,
                "has_pii": False
            }
        
        # Analyze facts
        fact_types = {}
        for fact in facts:
            fact_types[fact.fact_type] = fact_types.get(fact.fact_type, 0) + 1
        
        avg_confidence = sum(f.confidence for f in facts) / len(facts)
        has_pii = any(f.pii_encrypted for f in facts)
        
        return {
            "user_id": user_id,
            "total_facts": len(facts),
            "fact_types": fact_types,
            "avg_confidence": round(avg_confidence, 2),
            "has_pii": has_pii,
            "high_confidence_count": sum(1 for f in facts if f.confidence >= 0.85)
        }
