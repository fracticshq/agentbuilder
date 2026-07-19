"""
Short-Term Memory Manager - Rolling conversation buffer with auto-summarization
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import structlog

from memory.types import Message, ConversationSummary, MessageRole
from memory.config import MemoryConfig

logger = structlog.get_logger()


class ShortTermMemory:
    """
    Short-term memory manager.
    
    Features:
    - Rolling conversation buffer
    - Auto-summarization every N turns
    - TTL: 72 hours
    - Redis storage with MongoDB fallback
    """
    
    def __init__(self, db: AsyncIOMotorDatabase, redis_client = None):
        """
        Initialize short-term memory.
        
        Args:
            db: MongoDB database instance
            redis_client: Optional Redis client for caching
        """
        self.db = db
        self.redis = redis_client
        self.collection = db[MemoryConfig.CONVERSATIONS_COLLECTION]
        self.summaries = db[MemoryConfig.SUMMARIES_COLLECTION]
        
        logger.info("Short-term memory initialized",
                   ttl_hours=MemoryConfig.SHORT_TERM_TTL / 3600,
                   auto_summary_turns=MemoryConfig.AUTO_SUMMARY_TURNS)
    
    async def _ensure_indexes(self):
        """Create indexes for short-term memory."""
        try:
            # Index on conversation_id and timestamp
            await self.collection.create_index([
                ("conversation_id", 1),
                ("timestamp", -1)
            ])
            
            # TTL index for automatic cleanup (72 hours)
            await self.collection.create_index(
                "timestamp",
                expireAfterSeconds=MemoryConfig.SHORT_TERM_TTL
            )
            
            # Summaries indexes
            await self.summaries.create_index([
                ("conversation_id", 1),
                ("created_at", -1)
            ])
            
            await self.summaries.create_index(
                "created_at",
                expireAfterSeconds=MemoryConfig.SHORT_TERM_TTL
            )
            
            logger.debug("Short-term memory indexes created")
            
        except Exception as e:
            logger.warning("Failed to create indexes", error=str(e))
    
    async def add_message(
        self,
        conversation_id: str,
        role: MessageRole,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """
        Add a message to short-term memory.
        
        Args:
            conversation_id: Conversation identifier
            role: Message role (user/assistant/system)
            content: Message content
            metadata: Optional metadata
        
        Returns:
            Created Message
        """
        message = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata or {}
        )
        
        # Store in MongoDB
        message_doc = message.model_dump()
        await self.collection.insert_one(message_doc)
        
        logger.debug("Message added to short-term memory",
                    conversation_id=conversation_id,
                    role=role.value,
                    content_length=len(content))
        
        # Check if summarization needed
        if MemoryConfig.ENABLE_AUTO_SUMMARY:
            await self._check_and_summarize(conversation_id)
        
        return message
    
    async def get_recent_messages(
        self,
        conversation_id: str,
        limit: int = 50
    ) -> List[Message]:
        """
        Get recent messages from conversation.
        
        Args:
            conversation_id: Conversation identifier
            limit: Maximum number of messages to return
        
        Returns:
            List of Message objects
        """
        # Fetch the newest messages first, then restore chronological order.
        # Sorting ascending before applying the limit silently returns the
        # oldest context and causes the agent to forget recent turns.
        cursor = self.collection.find(
            {"conversation_id": conversation_id}
        ).sort("timestamp", -1).limit(limit)
        
        messages = []
        async for doc in cursor:
            try:
                # Remove MongoDB _id field
                doc.pop("_id", None)
                messages.append(Message(**doc))
            except Exception as e:
                logger.warning("Failed to parse message", error=str(e))
        
        messages.reverse()

        logger.debug("Retrieved recent messages",
                    conversation_id=conversation_id,
                    count=len(messages))
        
        return messages
    
    async def get_message_count(self, conversation_id: str) -> int:
        """Get total message count for conversation."""
        count = await self.collection.count_documents(
            {"conversation_id": conversation_id}
        )
        return count
    
    async def get_turn_count(self, conversation_id: str) -> int:
        """
        Get conversation turn count.
        
        A turn = one user message + one assistant response.
        """
        user_count = await self.collection.count_documents({
            "conversation_id": conversation_id,
            "role": MessageRole.USER.value
        })
        return user_count
    
    async def should_summarize(self, conversation_id: str) -> bool:
        """
        Check if conversation should be summarized.
        
        Conditions:
        - Auto-summary enabled
        - Turn count is multiple of AUTO_SUMMARY_TURNS
        - Haven't summarized these turns yet
        """
        if not MemoryConfig.ENABLE_AUTO_SUMMARY:
            return False
        
        turn_count = await self.get_turn_count(conversation_id)
        
        # Should summarize every N turns
        if turn_count % MemoryConfig.AUTO_SUMMARY_TURNS == 0 and turn_count > 0:
            # Check if we already have a summary for this turn range
            last_summary = await self._get_last_summary(conversation_id)
            
            if last_summary is None:
                return True
            
            if last_summary.turn_count < turn_count:
                return True
        
        return False
    
    async def _check_and_summarize(self, conversation_id: str):
        """Check if summarization is needed and trigger if so."""
        if await self.should_summarize(conversation_id):
            logger.info("Triggering auto-summary",
                       conversation_id=conversation_id)
            await self.trigger_summary(conversation_id)
    
    async def trigger_summary(self, conversation_id: str) -> Optional[ConversationSummary]:
        """
        Trigger summarization of recent turns.
        
        This method should:
        1. Get unsummarized messages
        2. Call LLM to summarize
        3. Store summary
        4. Optionally delete old messages (keep only recent)
        
        Args:
            conversation_id: Conversation to summarize
        
        Returns:
            Created ConversationSummary or None
        """
        # Get messages since last summary
        last_summary = await self._get_last_summary(conversation_id)
        
        if last_summary:
            messages = await self._get_messages_since(
                conversation_id,
                last_summary.end_timestamp
            )
        else:
            messages = await self.get_recent_messages(
                conversation_id,
                limit=MemoryConfig.AUTO_SUMMARY_TURNS * 2
            )
        
        if len(messages) < 2:
            logger.debug("Not enough messages to summarize")
            return None
        
        # TODO: Call LLM to generate summary
        # For now, create a simple summary
        summary_text = f"Conversation with {len(messages)} messages"
        
        summary = ConversationSummary(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            summary=summary_text,
            turn_count=await self.get_turn_count(conversation_id),
            start_timestamp=messages[0].timestamp,
            end_timestamp=messages[-1].timestamp
        )
        
        # Store summary
        await self.summaries.insert_one(summary.model_dump())
        
        logger.info("Conversation summary created",
                   conversation_id=conversation_id,
                   message_count=len(messages),
                   turn_count=summary.turn_count)
        
        return summary
    
    async def _get_last_summary(self, conversation_id: str) -> Optional[ConversationSummary]:
        """Get the most recent summary for conversation."""
        doc = await self.summaries.find_one(
            {"conversation_id": conversation_id},
            sort=[("created_at", -1)]
        )
        
        if doc:
            doc.pop("_id", None)
            return ConversationSummary(**doc)
        
        return None
    
    async def _get_messages_since(
        self,
        conversation_id: str,
        since: datetime
    ) -> List[Message]:
        """Get messages since a timestamp."""
        cursor = self.collection.find({
            "conversation_id": conversation_id,
            "timestamp": {"$gt": since}
        }).sort("timestamp", 1)
        
        messages = []
        async for doc in cursor:
            doc.pop("_id", None)
            messages.append(Message(**doc))
        
        return messages
    
    async def get_summaries(self, conversation_id: str) -> List[ConversationSummary]:
        """Get all summaries for a conversation."""
        cursor = self.summaries.find(
            {"conversation_id": conversation_id}
        ).sort("created_at", 1)
        
        summaries = []
        async for doc in cursor:
            doc.pop("_id", None)
            summaries.append(ConversationSummary(**doc))
        
        return summaries
    
    async def get_conversation_context(self, conversation_id: str) -> Dict[str, Any]:
        """
        Get complete conversation context (messages + summaries).
        
        Returns:
            Dictionary with recent_messages and summaries
        """
        messages = await self.get_recent_messages(conversation_id)
        summaries = await self.get_summaries(conversation_id)
        
        return {
            "conversation_id": conversation_id,
            "message_count": len(messages),
            "turn_count": await self.get_turn_count(conversation_id),
            "recent_messages": [m.model_dump() for m in messages],
            "summaries": [s.model_dump() for s in summaries],
            "has_summaries": len(summaries) > 0
        }
    
    async def clear_conversation(self, conversation_id: str):
        """Clear all messages and summaries for a conversation."""
        await self.collection.delete_many({"conversation_id": conversation_id})
        await self.summaries.delete_many({"conversation_id": conversation_id})
        
        logger.info("Conversation cleared", conversation_id=conversation_id)
