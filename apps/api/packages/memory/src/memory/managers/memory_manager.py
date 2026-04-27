"""
Unified Memory Manager - Orchestrates all memory layers (Phase 5).

This is the single entry point for the memory system, coordinating:
- Short-term memory (conversation history + auto-summary)
- Episodic memory (user facts + PII vaulting)
- Semantic memory (KB retrieval via retrieval package)
- Graph memory (rules + escalations)

Usage:
    memory = MemoryManager(config, mongo_client)
    await memory.initialize()
    
    # Store a new message
    context = await memory.add_message(
        conversation_id="conv-123",
        agent_id="essco-agent",
        user_id="user-456",
        role="user",
        content="I need a faucet for my kitchen renovation"
    )
    
    # Context contains: messages, summaries, facts, rules, escalations
    print(context.short_term_messages)  # Recent messages
    print(context.episodic_facts)        # User preferences
    print(context.matched_rules)         # Applicable rules
    print(context.escalations)           # Safety triggers
"""

import structlog
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

from memory.types import (
    Message,
    MessageRole,
    MemoryContext,
    EpisodicFact,
    GraphRule,
    EscalationTrigger,
    ConversationSummary,
)
from memory.config import MemoryConfig
from memory.managers.short_term import ShortTermMemory
from memory.managers.episodic import EpisodicMemory
from memory.managers.graph import GraphMemory

logger = structlog.get_logger(__name__)


class MemoryManager:
    """
    Unified orchestrator for all memory layers (Phase 5 Architecture).
    
    Architecture:
    - Short-term: Last N messages + auto-summary (TTL 72h)
    - Episodic: User facts extracted from history (TTL 90d)
    - Semantic: KB retrieval (handled by retrieval package)
    - Graph: Rules + escalations matched on query
    """
    
    def __init__(
        self,
        config: MemoryConfig,
        mongo_client: AsyncIOMotorClient,
        db_name: str = "agent-builder",
    ):
        """
        Initialize memory manager.
        
        Args:
            config: Memory configuration
            mongo_client: MongoDB async client
            db_name: Database name (default: agent-builder)
        """
        self.config = config
        self.mongo_client = mongo_client
        self.db_name = db_name
        
        # Initialize sub-managers
        self.short_term = ShortTermMemory(config, mongo_client, db_name)
        self.episodic = EpisodicMemory(config, mongo_client, db_name)
        self.graph = GraphMemory(mongo_client, db_name)
        
        self.logger = logger.bind(component="memory_manager")
    
    async def initialize(self) -> None:
        """Initialize all memory components."""
        self.logger.info("memory_manager_initializing")
        
        # Initialize MongoDB indexes
        await self.short_term.initialize()
        await self.episodic.initialize()
        await self.graph.initialize()
        
        # Seed default escalation triggers if enabled
        if self.config.ENABLE_GRAPH_RULES:
            await self.graph.seed_default_escalations()
        
        self.logger.info("memory_manager_initialized")
    
    async def add_message(
        self,
        conversation_id: str,
        agent_id: str,
        user_id: str,
        role: MessageRole,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryContext:
        """
        Add a message and orchestrate all memory updates.
        
        This method:
        1. Stores message in short-term memory
        2. Checks if auto-summary is needed (every 4 turns)
        3. Extracts episodic facts (if user message + confidence ≥ 0.70)
        4. Matches graph rules
        5. Checks escalation triggers
        6. Returns full memory context
        
        Args:
            conversation_id: Unique conversation ID
            agent_id: Agent ID (for brand isolation)
            user_id: User ID (for episodic memory)
            role: user|assistant|system
            content: Message text
            metadata: Optional metadata (page_context, etc.)
        
        Returns:
            MemoryContext with all memory layers populated
        """
        start_time = datetime.now(timezone.utc)
        self.logger.info(
            "add_message_start",
            conversation_id=conversation_id,
            agent_id=agent_id,
            role=role,
        )
        
        try:
            # 1. Store in short-term memory
            message = await self.short_term.add_message(
                conversation_id=conversation_id,
                agent_id=agent_id,
                role=role,
                content=content,
                metadata=metadata or {},
            )
            
            # 2. Check auto-summary trigger
            if self.config.ENABLE_AUTO_SUMMARY:
                if await self.short_term.should_summarize(conversation_id):
                    summary = await self.short_term.trigger_summary(
                        conversation_id,
                        agent_id,
                    )
                    self.logger.info(
                        "auto_summary_triggered",
                        conversation_id=conversation_id,
                        summary_length=len(summary.summary_text),
                    )
            
            # 3. Extract episodic facts (user messages only)
            episodic_facts: List[EpisodicFact] = []
            if role == MessageRole.USER and self.config.ENABLE_FACT_EXTRACTION:
                episodic_facts = await self.episodic.extract_and_store_facts(
                    user_id=user_id,
                    agent_id=agent_id,
                    text=content,
                )
                self.logger.info(
                    "episodic_facts_extracted",
                    count=len(episodic_facts),
                    user_id=user_id,
                )
            
            # 4. Match graph rules
            matched_rules: List[GraphRule] = []
            if self.config.ENABLE_GRAPH_RULES:
                matched_rules = await self.graph.match_rules(
                    brand_id=agent_id,
                    text=content,
                    context=metadata or {},
                )
                self.logger.info(
                    "rules_matched",
                    count=len(matched_rules),
                    agent_id=agent_id,
                )
            
            # 5. Check escalation triggers
            escalations: List[EscalationTrigger] = []
            if self.config.ENABLE_GRAPH_RULES:
                escalations = await self.graph.check_escalation(content)
                if escalations:
                    self.logger.warning(
                        "escalation_triggered",
                        count=len(escalations),
                        severity=[e.severity for e in escalations],
                    )
            
            # 6. Build memory context
            context = await self._build_memory_context(
                conversation_id=conversation_id,
                agent_id=agent_id,
                user_id=user_id,
                matched_rules=matched_rules,
                escalations=escalations,
            )
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.logger.info(
                "add_message_complete",
                duration_ms=int(duration * 1000),
                context_size=len(context.short_term_messages),
            )
            
            return context
            
        except Exception as e:
            self.logger.error(
                "add_message_error",
                error=str(e),
                conversation_id=conversation_id,
            )
            raise
    
    async def get_memory_context(
        self,
        conversation_id: str,
        agent_id: str,
        user_id: str,
        current_query: Optional[str] = None,
    ) -> MemoryContext:
        """
        Get full memory context without adding a message.
        
        Useful for retrieving context before generating a response.
        
        Args:
            conversation_id: Conversation ID
            agent_id: Agent ID
            user_id: User ID
            current_query: Optional current query (for rule matching)
        
        Returns:
            MemoryContext with all memory layers
        """
        self.logger.info(
            "get_memory_context",
            conversation_id=conversation_id,
            agent_id=agent_id,
        )
        
        # Match rules if query provided
        matched_rules: List[GraphRule] = []
        escalations: List[EscalationTrigger] = []
        
        if current_query and self.config.ENABLE_GRAPH_RULES:
            matched_rules = await self.graph.match_rules(
                brand_id=agent_id,
                text=current_query,
                context={},
            )
            escalations = await self.graph.check_escalation(current_query)
        
        return await self._build_memory_context(
            conversation_id=conversation_id,
            agent_id=agent_id,
            user_id=user_id,
            matched_rules=matched_rules,
            escalations=escalations,
        )
    
    async def _build_memory_context(
        self,
        conversation_id: str,
        agent_id: str,
        user_id: str,
        matched_rules: List[GraphRule],
        escalations: List[EscalationTrigger],
    ) -> MemoryContext:
        """
        Build unified memory context from all layers.
        
        Args:
            conversation_id: Conversation ID
            agent_id: Agent ID
            user_id: User ID
            matched_rules: Already-matched rules
            escalations: Already-checked escalations
        
        Returns:
            MemoryContext with all layers populated
        """
        # Get short-term memory
        messages = await self.short_term.get_recent_messages(conversation_id)
        summaries = await self.short_term.get_all_summaries(conversation_id)
        
        # Get episodic facts
        episodic_facts = await self.episodic.get_user_facts(user_id, agent_id)
        
        # Build context
        return MemoryContext(
            conversation_id=conversation_id,
            agent_id=agent_id,
            user_id=user_id,
            short_term_messages=messages,
            conversation_summaries=summaries,
            episodic_facts=episodic_facts,
            matched_rules=matched_rules,
            escalations=escalations,
            semantic_chunks=[],  # Populated by retrieval package
            retrieved_at=datetime.now(timezone.utc),
        )
    
    async def delete_user_data(self, user_id: str) -> Dict[str, int]:
        """
        GDPR delete all user data across all memory layers.
        
        Args:
            user_id: User ID to delete
        
        Returns:
            Dict with counts: {episodic: N, conversations: M}
        """
        self.logger.warning("gdpr_delete_initiated", user_id=user_id)
        
        # Delete episodic memory
        episodic_count = await self.episodic.delete_user_data(user_id)
        
        # Delete short-term conversations
        db = self.mongo_client[self.db_name]
        conversations_result = await db.conversations.delete_many({"user_id": user_id})
        summaries_result = await db.conversation_summaries.delete_many({"user_id": user_id})
        
        conversation_count = conversations_result.deleted_count + summaries_result.deleted_count
        
        self.logger.warning(
            "gdpr_delete_complete",
            user_id=user_id,
            episodic_deleted=episodic_count,
            conversations_deleted=conversation_count,
        )
        
        return {
            "episodic": episodic_count,
            "conversations": conversation_count,
        }
    
    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics across all memory layers.
        
        Returns:
            Dict with counts and performance metrics
        """
        db = self.mongo_client[self.db_name]
        
        # Short-term stats
        total_conversations = await db.conversations.count_documents({})
        total_summaries = await db.conversation_summaries.count_documents({})
        
        # Episodic stats
        total_facts = await db.episodic_memory.count_documents({})
        
        # Graph stats
        total_rules = await db.graph_rules.count_documents({})
        total_escalations = await db.escalation_triggers.count_documents({})
        
        return {
            "short_term": {
                "conversations": total_conversations,
                "summaries": total_summaries,
            },
            "episodic": {
                "facts": total_facts,
            },
            "graph": {
                "rules": total_rules,
                "escalations": total_escalations,
            },
            "config": {
                "auto_summary_enabled": self.config.ENABLE_AUTO_SUMMARY,
                "pii_vaulting_enabled": self.config.ENABLE_PII_VAULTING,
                "fact_extraction_enabled": self.config.ENABLE_FACT_EXTRACTION,
                "graph_rules_enabled": self.config.ENABLE_GRAPH_RULES,
            },
        }