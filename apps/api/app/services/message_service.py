"""
Message Service - Core business logic for processing messages
Integrates Phase 5 Memory System with retrieval and LLM generation.
"""

import asyncio
import uuid
from typing import AsyncGenerator, Optional
from datetime import datetime, timezone
import structlog
from motor.motor_asyncio import AsyncIOMotorClient

from commons.types.requests import MessageRequest
from commons.types.responses import MessageResponse, StreamingMessageResponse
from memory.config import MemoryConfig
from memory.managers.short_term import ShortTermMemory
from memory.managers.episodic import EpisodicMemory
from memory.managers.graph import GraphMemory
from memory.types import MessageRole, MemoryContext as MemoryContextType
from retrieval.pipeline import RetrievalPipeline
from retrieval.types import RetrievalConfig, RetrievalContext
from llm.factory import LLMFactory, create_provider_from_env
from ..config import Settings

logger = structlog.get_logger(__name__)


class MessageService:
    """
    Service for processing chat messages with Phase 5 Memory System.
    
    Integrates:
    - Short-term memory (conversation history + auto-summary)
    - Episodic memory (user facts + PII vaulting)
    - Semantic memory (KB retrieval)
    - Graph memory (rules + escalations)
    """
    
    def __init__(self, settings: Settings, brand_id: Optional[str] = None):
        self.settings = settings
        self.brand_id = brand_id or "default-agent"
        
        # Initialize MongoDB connection for memory
        self.mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
        self.db = self.mongo_client[settings.MONGODB_DATABASE]
        
        # Agent configuration (will be loaded on first message)
        self.agent_config = None
        self.system_prompt = None
        
        # Initialize Phase 5 Memory System
        self.memory_config = MemoryConfig()
        self.short_term = ShortTermMemory(self.db)
        self.episodic = EpisodicMemory(self.db)
        self.graph = GraphMemory(self.db)
        self._memory_initialized = False
        
        logger.info(
            "memory_system_initialized",
            brand_id=self.brand_id,
            auto_summary=self.memory_config.ENABLE_AUTO_SUMMARY,
            pii_vaulting=self.memory_config.ENABLE_PII_VAULTING,
            fact_extraction=self.memory_config.ENABLE_FACT_EXTRACTION,
            graph_rules=self.memory_config.ENABLE_GRAPH_RULES,
        )
        
        # Initialize retrieval pipeline with configuration
        retrieval_config = RetrievalConfig(
            vector_enabled=True,
            vector_top_k=50,
            similarity_threshold=0.7,
            bm25_enabled=True,
            bm25_top_k=50,
            rrf_k=60,
            rerank_enabled=True,
            rerank_top_k=12,
            brand_boost_enabled=bool(brand_id),
            page_boost_enabled=True,
            dedup_enabled=True
        )
        
        try:
            self.retrieval_pipeline = RetrievalPipeline(
                config=retrieval_config,
                brand_id=brand_id
            )
            logger.info("retrieval_pipeline_initialized", brand_id=brand_id)
        except Exception as e:
            logger.warning("retrieval_pipeline_init_failed", error=str(e))
            self.retrieval_pipeline = None
        
        # Initialize LLM provider (default to OpenAI for now)
        provider_name = settings.DEFAULT_LLM_PROVIDER or "openai"
        if provider_name == "openai":
            api_key = settings.OPENAI_API_KEY
            model = settings.OPENAI_MODEL
        elif provider_name == "qwen":
            api_key = settings.QWEN_API_KEY
            model = settings.QWEN_MODEL
        else:
            api_key = settings.OPENAI_API_KEY
            model = settings.OPENAI_MODEL
            
        self.llm_provider = create_provider_from_env(
            provider_name=provider_name,
            api_key=api_key,
            model=model
        )
        
        logger.info("message_service_initialized", brand_id=self.brand_id)
    
    async def _ensure_memory_initialized(self):
        """Ensure memory indexes and escalations are initialized (run once)."""
        if not self._memory_initialized:
            await self.short_term._ensure_indexes()
            await self.episodic._ensure_indexes()
            await self.graph._ensure_indexes()
            if self.memory_config.ENABLE_GRAPH_RULES:
                await self.graph.seed_default_escalations()
            self._memory_initialized = True
            logger.info("memory_indexes_initialized")
    
    async def _load_agent_config(self, agent_id: Optional[str] = None):
        """Load agent configuration from database."""
        if self.agent_config is not None:
            return  # Already loaded
        
        try:
            # Try to get agent_id from request or use brand_id
            if not agent_id:
                agent_id = self.brand_id
            
            # Load agent from database
            agents_collection = self.db["agents"]
            agent = await agents_collection.find_one({"id": agent_id})
            
            if agent:
                self.agent_config = agent
                self.system_prompt = agent.get("system_prompt", "")
                logger.info("agent_config_loaded", agent_id=agent_id, has_system_prompt=bool(self.system_prompt))
            else:
                logger.warning("agent_not_found", agent_id=agent_id)
                self.agent_config = {}
                self.system_prompt = ""
        except Exception as e:
            logger.error("agent_config_load_error", error=str(e))
            self.agent_config = {}
            self.system_prompt = ""

    
    async def process_message(self, request: MessageRequest) -> MessageResponse:
        """
        Process a single message with Phase 5 Memory System.
        
        Flow:
        1. Load agent configuration
        2. Ensure memory initialized
        3. Store user message in short-term memory
        4. Check for safety escalations
        5. Retrieve semantic context (KB)
        6. Build full memory context (short-term + episodic + graph)
        7. Generate response with LLM
        8. Store assistant response
        9. Extract and store episodic facts
        10. Check if auto-summary needed
        """
        try:
            start_time = datetime.now(timezone.utc)
            
            # Load agent configuration from request
            agent_id = request.agent_id or self.brand_id
            await self._load_agent_config(agent_id)
            
            # Ensure memory is initialized
            await self._ensure_memory_initialized()
            
            # Generate conversation ID if not provided
            conversation_id = request.conversation_id or str(uuid.uuid4())
            user_id = request.user_id or "anonymous"
            
            logger.info(
                "message_processing_start",
                conversation_id=conversation_id,
                user_id=user_id,
                brand_id=self.brand_id,
            )
            
            # 1. Store user message in short-term memory
            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content=request.message,
                metadata={
                    "user_id": user_id,
                    "page_context": request.page_context or {},
                }
            )
            
            # 2. Check for safety escalations
            escalations = []
            if self.memory_config.ENABLE_GRAPH_RULES:
                escalations = await self.graph.check_escalation(request.message)
                if escalations:
                    logger.warning(
                        "safety_escalation_triggered",
                        conversation_id=conversation_id,
                        severity=[e.severity for e in escalations],
                    )
            
            # 3. Retrieve semantic context from knowledge base
            retrieval_context = await self._retrieve_context(request)
            
            # 4. Build full memory context
            memory_context = await self._build_memory_context(
                conversation_id=conversation_id,
                user_id=user_id,
                query=request.message,
                escalations=escalations,
            )
            
            # 5. Generate response using LLM
            response_text = await self._generate_response(
                message=request.message,
                retrieval_context=retrieval_context,
                memory_context=memory_context,
                escalations=escalations,
            )
            
            # 6. Store assistant response
            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=response_text,
                metadata={"user_id": user_id}
            )
            
            # 7. Extract and store episodic facts (from user message)
            if self.memory_config.ENABLE_FACT_EXTRACTION:
                messages = await self.short_term.get_recent_messages(conversation_id, limit=10)
                facts = await self.episodic.extract_and_store_facts(
                    user_id=user_id,
                    messages=messages,
                    conversation_id=conversation_id
                )
                if facts:
                    logger.info(
                        "episodic_facts_extracted",
                        conversation_id=conversation_id,
                        count=len(facts),
                    )
            
            # 8. Check if auto-summary is needed
            if self.memory_config.ENABLE_AUTO_SUMMARY:
                if await self.short_term.should_summarize(conversation_id):
                    summary = await self.short_term.trigger_summary(conversation_id)
                    logger.info(
                        "auto_summary_generated",
                        conversation_id=conversation_id,
                        summary_length=len(summary.summary_text),
                    )
            
            # Extract citations from retrieval context
            citations = self._extract_citations(retrieval_context)
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "message_processing_complete",
                conversation_id=conversation_id,
                duration_ms=int(duration * 1000),
                escalations_count=len(escalations),
            )
            
            return MessageResponse(
                message=response_text,
                conversation_id=conversation_id,
                citations=citations,
                context_used=len(retrieval_context.chunks) if hasattr(retrieval_context, 'chunks') else 0,
                confidence_score=retrieval_context.confidence if hasattr(retrieval_context, 'confidence') else 0.0
            )
            
        except Exception as e:
            logger.error("message_processing_error", error=str(e), exc_info=True)
            raise
    
    async def stream_message(self, request: MessageRequest) -> AsyncGenerator[StreamingMessageResponse, None]:
        """
        Process a message and stream the response with Phase 5 Memory System.
        
        Same flow as process_message but with streaming response generation.
        """
        try:
            start_time = datetime.now(timezone.utc)
            
            # Ensure memory initialized
            await self._ensure_memory_initialized()
            
            # Generate conversation ID if not provided
            conversation_id = request.conversation_id or str(uuid.uuid4())
            user_id = request.user_id or "anonymous"
            
            # Store user message
            yield StreamingMessageResponse(
                type="status",
                content="Processing message...",
                conversation_id=conversation_id
            )
            
            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content=request.message,
                metadata={
                    "user_id": user_id,
                    "page_context": request.page_context or {},
                }
            )
            
            # Check for safety escalations
            escalations = []
            if self.memory_config.ENABLE_GRAPH_RULES:
                escalations = await self.graph.check_escalation(request.message)
                if escalations:
                    # Send escalation warning
                    yield StreamingMessageResponse(
                        type="warning",
                        content=f"Safety escalation: {escalations[0].severity}",
                        conversation_id=conversation_id
                    )
            
            # Retrieve semantic context
            yield StreamingMessageResponse(
                type="status",
                content="Retrieving context...",
                conversation_id=conversation_id
            )
            
            retrieval_context = await self._retrieve_context(request)
            
            # Build memory context
            yield StreamingMessageResponse(
                type="status",
                content="Loading memory...",
                conversation_id=conversation_id
            )
            
            memory_context = await self._build_memory_context(
                conversation_id=conversation_id,
                user_id=user_id,
                query=request.message,
                escalations=escalations,
            )
            
            # Stream response generation
            yield StreamingMessageResponse(
                type="status",
                content="Generating response...",
                conversation_id=conversation_id
            )
            
            response_chunks = []
            async for chunk in self._stream_response(
                message=request.message,
                retrieval_context=retrieval_context,
                memory_context=memory_context,
                escalations=escalations,
            ):
                response_chunks.append(chunk)
                yield StreamingMessageResponse(
                    type="content",
                    content=chunk,
                    conversation_id=conversation_id
                )
            
            # Combine full response
            full_response = "".join(response_chunks)
            
            # Store assistant response
            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=full_response,
                metadata={"user_id": user_id}
            )
            
            # Extract episodic facts
            if self.memory_config.ENABLE_FACT_EXTRACTION:
                messages = await self.short_term.get_recent_messages(conversation_id, limit=10)
                facts = await self.episodic.extract_and_store_facts(
                    user_id=user_id,
                    messages=messages,
                    conversation_id=conversation_id
                )
            
            # Check auto-summary
            if self.memory_config.ENABLE_AUTO_SUMMARY:
                if await self.short_term.should_summarize(conversation_id):
                    await self.short_term.trigger_summary(conversation_id)
            
            # Send final metadata
            citations = self._extract_citations(retrieval_context)
            yield StreamingMessageResponse(
                type="metadata",
                content="",
                conversation_id=conversation_id,
                citations=citations,
                context_used=len(retrieval_context.chunks) if hasattr(retrieval_context, 'chunks') else 0,
                confidence_score=retrieval_context.confidence if hasattr(retrieval_context, 'confidence') else 0.0
            )
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "message_streaming_complete",
                conversation_id=conversation_id,
                duration_ms=int(duration * 1000),
            )
            
        except Exception as e:
            logger.error("message_streaming_error", error=str(e), exc_info=True)
            yield StreamingMessageResponse(
                type="error",
                content=f"Error: {str(e)}",
                conversation_id=conversation_id or str(uuid.uuid4())
            )
    
    async def _retrieve_context(self, request: MessageRequest) -> RetrievalContext:
        """Retrieve relevant context for the message."""
        try:
            if not self.retrieval_pipeline:
                logger.warning("Retrieval pipeline not available")
                # Return empty context
                from retrieval.types import RetrievalContext
                return RetrievalContext(
                    chunks=[],
                    confidence=0.0,
                    sources=[],
                    query=request.message
                )
            
            # Use retrieval pipeline to get relevant chunks
            context = await self.retrieval_pipeline.retrieve(
                query=request.message,
                page_context=request.page_context,
                user_id=request.user_id,
                filters=request.filters or {},
                max_chunks=12
            )
            return context
            
        except Exception as e:
            logger.error("Error retrieving context", error=str(e), exc_info=True)
            # Return empty context on error
            from retrieval.types import RetrievalContext
            return RetrievalContext(
                chunks=[],
                confidence=0.0,
                sources=[],
                query=request.message,
                retrieval_metadata={"error": str(e)}
            )
    
    async def _build_memory_context(
        self,
        conversation_id: str,
        user_id: str,
        query: str,
        escalations: list,
    ) -> dict:
        """
        Build unified memory context from all layers.
        
        Returns dict with:
        - recent_messages: Last N messages from short-term
        - user_facts: User preferences from episodic memory
        - matched_rules: Graph rules matching the query
        - escalations: Safety escalation triggers
        - summaries: Conversation summaries
        """
        # Get short-term messages
        recent_messages = await self.short_term.get_recent_messages(
            conversation_id, limit=10
        )
        
        # Get user facts from episodic memory
        user_facts = []
        if self.memory_config.ENABLE_FACT_EXTRACTION:
            user_facts = await self.episodic.get_user_facts(user_id, limit=20)
        
        # Get matched graph rules
        matched_rules = []
        if self.memory_config.ENABLE_GRAPH_RULES:
            matched_rules = await self.graph.match_rules(
                brand_id=self.brand_id,
                query=query,
                context={},
            )
        
        # Get conversation summaries
        summaries = []
        try:
            summaries_cursor = self.short_term.summaries.find(
                {"conversation_id": conversation_id}
            ).sort("created_at", -1).limit(3)
            summaries = await summaries_cursor.to_list(length=3)
        except Exception as e:
            logger.warning("failed_to_get_summaries", error=str(e))
        
        return {
            "recent_messages": recent_messages,
            "user_facts": user_facts,
            "matched_rules": matched_rules,
            "escalations": escalations,
            "summaries": summaries,
        }
    
    async def _generate_response(
        self,
        message: str,
        retrieval_context: RetrievalContext,
        memory_context: dict,
        escalations: list,
    ) -> str:
        """Generate response using LLM with full context."""
        try:
            # Build prompt with context and memory
            prompt = self._build_prompt(
                message,
                retrieval_context,
                memory_context,
                escalations,
            )
            
            # Generate response
            response = await self.llm_provider.generate(prompt)
            return response.content
            
        except Exception as e:
            logger.error("llm_generation_error", error=str(e))
            return "I apologize, but I encountered an error while processing your request."
    
    async def _stream_response(
        self,
        message: str,
        retrieval_context: RetrievalContext,
        memory_context: dict,
        escalations: list,
    ) -> AsyncGenerator[str, None]:
        """Stream response generation using LLM with full context."""
        try:
            # Build prompt with context and memory
            prompt = self._build_prompt(
                message,
                retrieval_context,
                memory_context,
                escalations,
            )
            
            # Stream response
            async for chunk in self.llm_provider.stream(prompt):
                yield chunk.content
                
        except Exception as e:
            logger.error("llm_streaming_error", error=str(e))
            yield "I apologize, but I encountered an error while processing your request."
    
    def _build_prompt(
        self,
        message: str,
        retrieval_context: RetrievalContext,
        memory_context: dict,
        escalations: list,
    ) -> str:
        """
        Build comprehensive prompt with all context layers.
        
        Includes:
        - System instructions with brand voice
        - Safety escalation warnings
        - Knowledge base context (semantic memory)
        - Recent conversation (short-term memory)
        - User preferences (episodic memory)
        - Matched rules (graph memory)
        """
        prompt_parts = []
        
        # System instruction - use custom agent prompt if available
        if self.system_prompt:
            prompt_parts.append(self.system_prompt)
        else:
            # Fallback to generic prompt
            prompt_parts.append(
                "You are a helpful AI assistant for customer support. "
                "Use the provided context to answer questions accurately and helpfully. "
                "If you cannot find relevant information in the context, say so clearly. "
                "Always cite your sources when possible."
            )
        
        # Add safety escalation warnings
        if escalations:
            prompt_parts.append("\n⚠️  SAFETY ALERT:")
            for esc in escalations[:2]:  # Top 2 escalations
                prompt_parts.append(
                    f"- {esc.severity.upper()}: {', '.join(esc.trigger_keywords)} detected"
                )
                if esc.action.get("type") == "escalate_emergency":
                    prompt_parts.append(
                        "  → Recommend immediate action: " + esc.action.get("message", "Contact emergency services")
                    )
        
        # Add knowledge base context (semantic memory)
        if retrieval_context.chunks:
            prompt_parts.append("\n📚 Knowledge Base Context:")
            prompt_parts.append("Use the following information to answer the user's question accurately:")
            for i, chunk in enumerate(retrieval_context.chunks[:10]):  # Top 10 chunks
                citation = f"[{i+1}]"
                if chunk.title:
                    citation += f" {chunk.title}"
                # Include more content - up to 500 chars per chunk
                content = chunk.content[:500] if len(chunk.content) > 500 else chunk.content
                prompt_parts.append(f"\n{citation}:\n{content}")
        
        # Add user preferences (episodic memory)
        if memory_context.get("user_facts"):
            facts = memory_context["user_facts"][:5]  # Top 5 facts
            if facts:
                prompt_parts.append("\n👤 User Preferences:")
                for fact in facts:
                    prompt_parts.append(f"- {fact.fact}")
        
        # Add conversation summaries (short-term memory)
        if memory_context.get("summaries"):
            summaries = memory_context["summaries"][:2]  # Latest 2 summaries
            if summaries:
                prompt_parts.append("\n📝 Previous Conversation Summary:")
                for summary in summaries:
                    prompt_parts.append(f"- {summary.get('summary_text', '')}")
        
        # Add recent conversation (short-term memory)
        if memory_context.get("recent_messages"):
            recent = memory_context["recent_messages"][-4:]  # Last 4 messages
            if len(recent) > 1:  # More than just the current user message
                prompt_parts.append("\n💬 Recent Conversation:")
                for msg in recent[:-1]:  # Exclude the current message
                    role = msg.role.value if hasattr(msg.role, 'value') else str(msg.role)
                    prompt_parts.append(f"{role.capitalize()}: {msg.content}")
        
        # Add matched rules (graph memory)
        if memory_context.get("matched_rules"):
            rules = memory_context["matched_rules"][:2]  # Top 2 rules
            if rules:
                prompt_parts.append("\n📋 Relevant Policies:")
                for rule in rules:
                    prompt_parts.append(
                        f"- {rule.name}: {rule.action.get('message', 'See documentation')}"
                    )
        
        # Add current message
        prompt_parts.append(f"\n👤 User: {message}")
        prompt_parts.append("\n🤖 Assistant:")
        
        return "\n".join(prompt_parts)
    
    def _extract_citations(self, context: RetrievalContext) -> list:
        """Extract citations from context."""
        citations = []
        for chunk in context.chunks:
            if chunk.doc_id and chunk.title:
                citations.append({
                    "doc_id": chunk.doc_id,
                    "title": chunk.title,
                    "url": chunk.url,
                    "confidence": chunk.score
                })
        return citations
