"""
Message Service - Core business logic for processing messages
Integrates Phase 5 Memory System with retrieval and LLM generation.
Phase 4: Response validation to prevent hallucinations.
"""

import asyncio
import uuid
from typing import AsyncGenerator, Optional
from datetime import datetime, timezone
import structlog
from motor.motor_asyncio import AsyncIOMotorDatabase

from commons.types.requests import MessageRequest
from commons.types.responses import MessageResponse, StreamingMessageResponse
from memory.config import MemoryConfig
from memory.managers.short_term import ShortTermMemory
from memory.managers.episodic import EpisodicMemory
from memory.managers.graph import GraphMemory
from memory.managers.procedural import ProceduralMemory
from memory.managers.resource import ResourceMemory
from memory.types import MessageRole, MemoryContext as MemoryContextType
from retrieval.pipeline import RetrievalPipeline
from retrieval.types import RetrievalConfig, RetrievalContext
from llm.factory import LLMFactory, create_provider_from_env

# Phase 6: SOTA Agentic Orchestrator (package imports)
from tools.registry import ToolRegistry
from tools.builtin.retrieval_tool import RetrievalTool
from agent_runtime.orchestrator import Orchestrator, AgentResult

from ..config import Settings
from ..connections import connection_manager
from .response_validator import ResponseValidator  # Phase 4

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
    
    def __init__(self, settings: Settings, brand_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.settings = settings
        self.brand_id = brand_id or "default-brand"
        self.agent_id = agent_id
        
        # Database will be set dynamically based on agent/brand
        self.brand_db: Optional[AsyncIOMotorDatabase] = None
        
        # Agent configuration (will be loaded on first message)
        self.agent_config = None
        self.system_prompt = None
        
        # Memory system will be initialized after database is set
        self.memory_config = MemoryConfig()
        self.short_term: Optional[ShortTermMemory] = None
        self.episodic: Optional[EpisodicMemory] = None
        self.graph: Optional[GraphMemory] = None
        self.procedural: Optional[ProceduralMemory] = None
        self.resource: Optional[ResourceMemory] = None
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
        
        # Phase 4: Initialize response validator
        self.response_validator = ResponseValidator(strict_mode=True)
        
        # Phase 6: Initialize SOTA Orchestrator with Critic
        self.tool_registry = ToolRegistry()
        if self.retrieval_pipeline:
            self.tool_registry.register(RetrievalTool(self.retrieval_pipeline))
            
        self.orchestrator = Orchestrator(
            llm=self.llm_provider,
            tools=self.tool_registry,
            critic=self.response_validator  # Enable autonomous self-correction
        )

        
        logger.info("message_service_initialized", brand_id=self.brand_id)
    
    async def _initialize_brand_database(self, agent_id: str):
        """Initialize brand-specific database and memory system."""
        try:
            # Get brand database from connection manager
            # Use get_brand_db_by_agent_id which handles the lookup
            self.brand_db = await connection_manager.get_brand_db_by_agent_id(agent_id)
            
            # Get the brand_slug from the agent
            system_db = connection_manager.get_system_db()
            agent = await system_db.agents.find_one({"id": agent_id})
            if agent and agent.get("brand_slug"):
                brand_slug = agent["brand_slug"]
                
                # Reinitialize retrieval pipeline with correct brand_slug
                retrieval_config = RetrievalConfig(
                    vector_enabled=True,
                    vector_top_k=50,
                    similarity_threshold=0.7,
                    bm25_enabled=True,
                    bm25_top_k=50,
                    rrf_k=60,
                    rerank_enabled=True,
                    rerank_top_k=12,
                    brand_boost_enabled=True,
                    page_boost_enabled=True,
                    dedup_enabled=True
                )
                
                self.retrieval_pipeline = RetrievalPipeline(
                    config=retrieval_config,
                    brand_id=brand_slug  # Use brand_slug instead of default brand_id
                )
                logger.info("retrieval_pipeline_reinitialized", brand_slug=brand_slug)
            
            # Initialize memory system with brand database
            self.short_term = ShortTermMemory(self.brand_db)
            self.episodic = EpisodicMemory(self.brand_db)
            self.graph = GraphMemory(self.brand_db)
            self.procedural = ProceduralMemory(self.brand_db)
            self.resource = ResourceMemory(self.brand_db)
            
            logger.info("brand_database_initialized", 
                       agent_id=agent_id, 
                       brand_id=self.brand_id,
                       memory_layers=["short_term", "episodic", "graph", "procedural", "resource"])
            
        except Exception as e:
            logger.error("brand_database_init_failed", agent_id=agent_id, error=str(e), exc_info=True)
            raise

    async def _ensure_memory_initialized(self):
        """Ensure memory system is initialized."""
        if not self._memory_initialized:
            if self.brand_db is None or self.short_term is None:
                raise RuntimeError("Brand database not initialized. Call _initialize_brand_database first.")
            
            await self.short_term._ensure_indexes()
            await self.episodic._ensure_indexes()
            await self.graph._ensure_indexes()
            
            # Initialize new memory layers
            if self.procedural:
                await self.procedural._ensure_indexes()
            if self.resource:
                await self.resource._ensure_indexes()
            
            # Seed default escalations if method exists (legacy support)
            if hasattr(self.graph, 'seed_default_escalations'):
                await self.graph.seed_default_escalations()
            
            self._memory_initialized = True
            logger.info("memory_indexes_initialized", layers=["short_term", "episodic", "graph", "procedural", "resource"])
    
    async def _load_agent_config(self, agent_id: str):
        """Load agent configuration from system database."""
        try:
            # Initialize brand database first
            await self._initialize_brand_database(agent_id)
            
            # Load from system agents collection
            system_db = connection_manager.get_system_db()
            agents_collection = system_db["agents"]
            agent = await agents_collection.find_one({"id": agent_id})
            
            if agent:
                self.agent_config = agent.get("configuration", {})
                self.system_prompt = agent.get("system_prompt", "")
                self.brand_id = agent.get("brand_slug", self.brand_id)
                logger.info("agent_config_loaded", agent_id=agent_id, brand_id=self.brand_id)
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
            
            # 2. Check for safety rules
            escalations = []
            if self.memory_config.ENABLE_GRAPH_RULES:
                escalations = await self.graph.check_escalation(request.message)
            
            # 3. Build context for the agent (pass safe context)
            memory_context = await self._build_memory_context(
                conversation_id=conversation_id,
                user_id=user_id,
                query=request.message,
                escalations=escalations,
            )
            
            # 4. RUN SOTA ORCHESTRATOR LOOP
            # Instead of linear retrieve->generate, let the agent plan and execute.
            agent_result = await self.orchestrator.run(
                query=request.message,
                context={"memory": memory_context}
            )
            
            response_text = agent_result.answer
            # Note: Validation now happens inside Orchestrator via Critic loop
            # Check agent_result.metadata for validation_passed and validation_issues
            
            # 5. Store assistant response
            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=response_text,
                metadata={
                    "user_id": user_id,
                    "agent_steps": agent_result.metadata.get("steps_executed", 0),
                    "plan_goal": agent_result.metadata.get("plan", {}).get("goal")
                }
            )
            
            # 6. Extract Facts & Auto-Summary (Async)
            if self.memory_config.ENABLE_FACT_EXTRACTION:
                # Fire and forget / background task desirable here
                pass 
                
            # Return response
            return MessageResponse(
                message=response_text,
                conversation_id=conversation_id,
                citations=[], # Citations would need to be extracted from agent metadata in future
                context_used=0, 
            )
            
        except Exception as e:
            logger.error("message_processing_error", error=str(e), exc_info=True)
            raise

    
    async def stream_message(self, request: MessageRequest) -> AsyncGenerator[StreamingMessageResponse, None]:
        """
        Process a message and stream the response with Phase 5 Memory System.
        
        Same flow as process_message but with streaming response generation.
        """
        logger.info("stream_message_called", message=request.message[:50])
        
        # Initialize conversation_id early for error handling
        conversation_id = request.conversation_id or str(uuid.uuid4())
        
        try:
            start_time = datetime.now(timezone.utc)
            
            # Load agent configuration from request
            agent_id = request.agent_id or self.brand_id
            await self._load_agent_config(agent_id)
            logger.info("agent_config_loaded", agent_id=agent_id, has_system_prompt=bool(self.system_prompt))
            
            # Ensure memory initialized
            logger.info("ensuring_memory_initialized")
            await self._ensure_memory_initialized()
            logger.info("memory_initialized")
            
            # Set user_id
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
                    # Send escalation warning as status
                    yield StreamingMessageResponse(
                        type="status",
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
            
            # Phase 4: Validate streaming response
            query_intent = getattr(retrieval_context, 'query_intent', 'general')
            catalog_products = None
            catalog_dealers = None
            
            if query_intent == 'product_search':
                catalog_products = self._extract_product_data(retrieval_context)
            elif query_intent == 'dealer_search':
                catalog_dealers = self._extract_dealer_data(retrieval_context)
            
            validation_result = await self.response_validator.validate_response(
                response=full_response,
                query_intent=query_intent,
                catalog_products=catalog_products,
                catalog_dealers=catalog_dealers,
            )
            
            logger.info(
                "streaming_response_validation",
                conversation_id=conversation_id,
                is_valid=validation_result.is_valid,
                confidence=validation_result.confidence,
                issues_count=len(validation_result.issues),
            )
            
            # If validation failed, send warning to client
            if validation_result.issues:
                critical_count = len([i for i in validation_result.issues if "CRITICAL" in i])
                if critical_count > 0:
                    yield StreamingMessageResponse(
                        type="status",
                        content=f"⚠️ Response validation: {critical_count} issue(s) detected and corrected",
                        conversation_id=conversation_id
                    )
            
            # Store validated response
            response_to_store = validation_result.sanitized_response if validation_result.issues else full_response
            
            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=response_to_store,
                metadata={
                    "user_id": user_id,
                    "validation": {
                        "is_valid": validation_result.is_valid,
                        "confidence": validation_result.confidence,
                        "issues_count": len(validation_result.issues),
                    }
                }
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
            
            # Phase 5: Extract products and dealers for UI cards
            query_intent = getattr(retrieval_context, 'query_intent', None)
            products = []
            dealers = []
            
            if query_intent == 'product_search':
                products = self._extract_product_data(retrieval_context)
            elif query_intent == 'dealer_search':
                dealers = self._extract_dealer_data(retrieval_context)
            
            yield StreamingMessageResponse(
                type="metadata",
                content="",
                conversation_id=conversation_id,
                citations=citations,
                context_used=len(retrieval_context.chunks) if hasattr(retrieval_context, 'chunks') else 0,
                confidence_score=validation_result.confidence,  # Phase 4: Use validation confidence
                products=products if products else None,  # Phase 5: Product cards
                dealers=dealers if dealers else None,     # Phase 5: Dealer cards
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
            
            # Console logging for debugging
            print("\n" + "="*80)
            print("🤖 LLM RESPONSE GENERATED")
            print("="*80)
            print(f"User Query: {message[:100]}...")
            print(f"Response Length: {len(response.content)} chars")
            print(f"\nFull Response:")
            print("-" * 80)
            print(response.content)
            print("-" * 80)
            
            # Log retrieval context info
            chunks_count = len(retrieval_context.chunks) if hasattr(retrieval_context, 'chunks') else 0
            print(f"\nContext Used: {chunks_count} chunks")
            
            # Log memory context info
            if memory_context:
                print(f"Memory Layers:")
                if memory_context.get('recent_messages'):
                    print(f"  - Recent Messages: {len(memory_context['recent_messages'])}")
                if memory_context.get('user_facts'):
                    print(f"  - User Facts: {len(memory_context['user_facts'])}")
                if memory_context.get('matched_rules'):
                    print(f"  - Matched Rules: {len(memory_context['matched_rules'])}")
                if memory_context.get('summaries'):
                    print(f"  - Summaries: {len(memory_context['summaries'])}")
            
            # Log escalations if any
            if escalations:
                print(f"\n⚠️  Safety Escalations: {len(escalations)}")
                for esc in escalations[:3]:  # Show up to 3
                    print(f"  - {esc.severity.upper()}: {', '.join(esc.matched_keywords[:3])}")
            
            print("="*80 + "\n")
            
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
            
            # Console logging header
            print("\n" + "="*80)
            print("🤖 LLM STREAMING RESPONSE")
            print("="*80)
            print(f"User Query: {message[:100]}...")
            
            # Log retrieval context info
            chunks_count = len(retrieval_context.chunks) if hasattr(retrieval_context, 'chunks') else 0
            print(f"Context Used: {chunks_count} chunks")
            
            # Log memory context info
            if memory_context:
                print(f"Memory Layers:")
                if memory_context.get('recent_messages'):
                    print(f"  - Recent Messages: {len(memory_context['recent_messages'])}")
                if memory_context.get('user_facts'):
                    print(f"  - User Facts: {len(memory_context['user_facts'])}")
                if memory_context.get('matched_rules'):
                    print(f"  - Matched Rules: {len(memory_context['matched_rules'])}")
            
            # Log escalations if any
            if escalations:
                print(f"\n⚠️  Safety Escalations: {len(escalations)}")
                for esc in escalations[:3]:
                    print(f"  - {esc.severity.upper()}: {', '.join(esc.matched_keywords[:3])}")
            
            print(f"\nStreaming Response:")
            print("-" * 80)
            
            # Stream response and collect for final display
            full_response = []
            async for chunk in self.llm_provider.stream(prompt):
                full_response.append(chunk.content)
                yield chunk.content
            
            # Log complete response
            complete_response = ''.join(full_response)
            print(complete_response)
            print("-" * 80)
            print(f"Total Length: {len(complete_response)} chars")
            print("="*80 + "\n")
                
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
        
        Phase 3: Adds grounded prompt generation for product/dealer queries
        with structured JSON and hallucination prevention.
        
        Includes:
        - System instructions with brand voice
        - Safety escalation warnings
        - Knowledge base context (semantic memory)
        - Structured product/dealer data (Phase 3)
        - Hallucination prevention rules (Phase 3)
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
        
        # Phase 3: Add hallucination prevention rules based on query intent
        query_intent = getattr(retrieval_context, 'query_intent', None)
        if query_intent in ['product_search', 'dealer_search']:
            prompt_parts.append(self._get_grounding_rules(query_intent))
        
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
        
        # Phase 3: Add structured product/dealer data if available
        if query_intent == 'product_search':
            products_json = self._extract_product_data(retrieval_context)
            if products_json:
                prompt_parts.append("\n🛍️  PRODUCT CATALOG (Structured Data):")
                prompt_parts.append("IMPORTANT: Only mention products listed below. Do NOT invent SKUs, prices, or features.")
                prompt_parts.append("```json")
                import json
                prompt_parts.append(json.dumps(products_json, indent=2, ensure_ascii=False))
                prompt_parts.append("```")
        
        elif query_intent == 'dealer_search':
            dealers_json = self._extract_dealer_data(retrieval_context)
            if dealers_json:
                prompt_parts.append("\n📍 DEALER DIRECTORY (Structured Data):")
                prompt_parts.append("IMPORTANT: Only mention dealers listed below. Do NOT invent locations, phone numbers, or addresses.")
                prompt_parts.append("```json")
                import json
                prompt_parts.append(json.dumps(dealers_json, indent=2, ensure_ascii=False))
                prompt_parts.append("```")
        
        # Add knowledge base context (semantic memory) - text chunks
        if retrieval_context.chunks:
            # Filter out chunks we've already shown in structured format
            text_chunks = [
                chunk for chunk in retrieval_context.chunks
                if not (query_intent in ['product_search', 'dealer_search'] and 
                       chunk.content_type in ['product', 'dealer'])
            ]
            
            if text_chunks:
                prompt_parts.append("\n📚 Knowledge Base Context:")
                prompt_parts.append("Use the following information to answer the user's question accurately:")
                for i, chunk in enumerate(text_chunks[:10]):  # Top 10 chunks
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
    
    def _get_grounding_rules(self, query_intent: str) -> str:
        """
        Phase 3: Get hallucination prevention rules based on query intent.
        
        Args:
            query_intent: Detected query intent (product_search, dealer_search, etc.)
            
        Returns:
            Grounding rules text for the LLM
        """
        if query_intent == "product_search":
            return """
🚨 STRICT GROUNDING RULES FOR PRODUCT QUERIES:
1. ONLY mention products explicitly listed in the PRODUCT CATALOG above
2. NEVER invent or guess SKU codes, prices, or product names
3. If a product is not in the catalog, say "I don't have information about that product"
4. ALWAYS cite the exact SKU when mentioning a product
5. NEVER approximate prices - use exact values from catalog or say "price not available"
6. If asked about features not in the catalog, say "I don't have detailed specifications"
7. Format prices with currency (e.g., ₹4,500 INR)
"""
        elif query_intent == "dealer_search":
            return """
🚨 STRICT GROUNDING RULES FOR DEALER QUERIES:
1. ONLY mention dealers explicitly listed in the DEALER DIRECTORY above
2. NEVER invent phone numbers, addresses, or dealer names
3. If a dealer is not in the directory, say "I don't have dealer information for that location"
4. ALWAYS provide complete contact information (phone, email, address) when available
5. NEVER approximate addresses or phone numbers
6. If asked about dealer hours or services not in the directory, say "Please contact the dealer directly"
"""
        else:
            return ""
    
    def _extract_product_data(self, retrieval_context: RetrievalContext) -> list:
        """
        Phase 3: Extract structured product data from retrieval context.
        
        Args:
            retrieval_context: Retrieval context with chunks
            
        Returns:
            List of product data dictionaries
        """
        products = []
        seen_skus = set()
        
        for chunk in retrieval_context.chunks:
            # Only process product chunks with structured data
            if chunk.content_type == "product" and chunk.product_data:
                sku = chunk.product_data.get("sku")
                
                # Deduplicate by SKU
                if sku and sku not in seen_skus:
                    seen_skus.add(sku)
                    
                    # Extract validated product data
                    product = {
                        "sku": sku,
                        "name": chunk.product_data.get("name", "Unknown Product"),
                        "price": chunk.product_data.get("price"),
                        "currency": chunk.product_data.get("currency", "INR"),
                        "category": chunk.product_data.get("category", "Uncategorized"),
                        "in_stock": chunk.product_data.get("in_stock", True),
                    }
                    
                    # Optional fields
                    if chunk.product_data.get("features"):
                        product["features"] = chunk.product_data["features"]
                    if chunk.product_data.get("image_url"):
                        product["image_url"] = chunk.product_data["image_url"]
                    if chunk.product_data.get("product_url"):
                        product["product_url"] = chunk.product_data["product_url"]
                    
                    products.append(product)
        
        return products
    
    def _extract_dealer_data(self, retrieval_context: RetrievalContext) -> list:
        """
        Phase 3: Extract structured dealer data from retrieval context.
        
        Args:
            retrieval_context: Retrieval context with chunks
            
        Returns:
            List of dealer data dictionaries
        """
        dealers = []
        seen_dealer_ids = set()
        
        for chunk in retrieval_context.chunks:
            # Only process dealer chunks with structured data
            if chunk.content_type == "dealer" and chunk.dealer_data:
                dealer_id = chunk.dealer_data.get("dealer_id")
                
                # Deduplicate by dealer_id
                if dealer_id and dealer_id not in seen_dealer_ids:
                    seen_dealer_ids.add(dealer_id)
                    
                    # Extract validated dealer data
                    dealer = {
                        "dealer_id": dealer_id,
                        "name": chunk.dealer_data.get("name", "Unknown Dealer"),
                        "city": chunk.dealer_data.get("city", "Unknown"),
                        "state": chunk.dealer_data.get("state"),
                    }
                    
                    # Optional contact fields
                    if chunk.dealer_data.get("phone"):
                        dealer["phone"] = chunk.dealer_data["phone"]
                    if chunk.dealer_data.get("email"):
                        dealer["email"] = chunk.dealer_data["email"]
                    if chunk.dealer_data.get("address"):
                        dealer["address"] = chunk.dealer_data["address"]
                    
                    dealers.append(dealer)
        
        return dealers
