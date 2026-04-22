"""
Message Service - Core business logic for processing messages
Integrates Phase 5 Memory System with retrieval and LLM generation.
Phase 4: Response validation to prevent hallucinations.
"""

import os
import asyncio
import json
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
from agent_runtime.orchestrator_shopify import ShopifyOrchestrator

from ..config import Settings
from ..connections import connection_manager
from .response_validator import ResponseValidator  # Phase 4
from .strapi_client import StrapiClient

logger = structlog.get_logger(__name__)


def _sanitize_for_json(data: dict) -> dict:
    """Convert non-JSON-serializable values (ObjectId, datetime, etc.) to strings.

    MongoDB documents often contain ObjectId/_id and datetime fields that Pydantic's
    model_dump_json() cannot serialize. Running the dict through json.dumps/loads with
    default=str coerces those to safe string representations.
    """
    try:
        return json.loads(json.dumps(data, default=str))
    except Exception:
        return {}


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
            
        try:
            self.llm_provider = create_provider_from_env(
                provider_name=provider_name,
                api_key=api_key,
                model=model
            )
        except ValueError as e:
            logger.error("llm_provider_init_failed", error=str(e))
            raise
        
        # Phase 4: Initialize response validator
        self.response_validator = ResponseValidator(strict_mode=True)
        
        # Phase 6: Initialize SOTA Orchestrator with Critic
        self.tool_registry = ToolRegistry()
        if self.retrieval_pipeline:
            self.tool_registry.register(RetrievalTool(self.retrieval_pipeline))
            
        self.orchestrator = Orchestrator(
            llm=self.llm_provider,
            tools=self.tool_registry,
            critic=self.response_validator,  # Enable autonomous self-correction
            system_prompt=None  # Will be loaded dynamically from DB
        )

        # Strapi dashboard sync (fire-and-forget, non-blocking)
        self.strapi = StrapiClient(
            base_url=settings.STRAPI_URL,
            api_token=settings.STRAPI_API_TOKEN,
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
                
                # Update the RetrievalTool to use the new pipeline
                # This is critical - the tool was registered with the old default pipeline
                if self.tool_registry:
                    self.tool_registry.register(RetrievalTool(self.retrieval_pipeline))
                    logger.info("retrieval_tool_updated", brand_slug=brand_slug)
            
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
                config = agent.get("configuration", {})
                self.agent_config = config
                self.system_prompt = agent.get("system_prompt", "")
                self.brand_id = agent.get("brand_slug", self.brand_id)
                
                # Sync system prompt to Orchestrator
                if self.orchestrator:
                    self.orchestrator.system_prompt = self.system_prompt
                
                logger.info("agent_config_loaded", 
                           agent_id=agent_id, 
                           brand_id=self.brand_id,
                           has_system_prompt=bool(self.system_prompt))
                           
                # Initialize remote MCP tools if Shopify is selected
                if config.get("data_source") == "shopify":
                    from tools.mcp_client import McpClient
                    from agent_runtime.orchestrator_shopify import ShopifyOrchestrator
                    
                    # For local development we assume port 3005 for the Shopify MCP Service
                    # In production this would be loaded from settings
                    mcp_endpoint = self.settings.SHOPIFY_MCP_URL if hasattr(self.settings, 'SHOPIFY_MCP_URL') else "http://localhost:3005/mcp"
                    
                    # Extract credentials from Agent Config (nested or top-level), with environment fallbacks
                    # The Wizard UI saves them in a 'shopify' sub-object
                    shopify_conf = config.get("shopify", {})
                    shopify_url = (
                        shopify_conf.get("shop_url") or 
                        config.get("shopify_shop_url") or 
                        self.settings.SHOPIFY_SHOP_URL
                    )
                    shopify_token = (
                        shopify_conf.get("access_token") or
                        config.get("shopify_access_token") or 
                        config.get("shopify_admin_token") or 
                        self.settings.SHOPIFY_STOREFRONT_ADMIN_ACCESS_TOKEN
                    )

                    if not shopify_url or not shopify_token:
                        logger.warning("shopify_credentials_missing", agent_id=agent_id)
                        
                    mcp_headers = {
                        "x-shopify-shop-url": str(shopify_url or ""),
                        "x-shopify-admin-token": str(shopify_token or "")
                    }
                    
                    # Also try to get a customer access token from config or settings
                    customer_token = (
                        shopify_conf.get("customer_access_token") or
                        config.get("shopify_customer_access_token") or 
                        self.settings.SHOPIFY_CUSTOMER_ACCESS_TOKEN
                    )
                    
                    if customer_token:
                        mcp_headers["x-customer-access-token"] = str(customer_token)
                    
                    mcp_client = McpClient(endpoint=mcp_endpoint, headers=mcp_headers)
                    
                    # Connect and discover remote tools using the conversation/user session
                    remote_tools = await mcp_client.discover_tools()
                    for tool in remote_tools:
                        self.tool_registry.register(tool)
                        
                    logger.info("mcp_tools_registered", count=len(remote_tools), brand_id=self.brand_id)

                    # Swap to ShopifyOrchestrator for Shopify-integrated agents
                    self.orchestrator = ShopifyOrchestrator(
                        llm=self.llm_provider,
                        tools=self.tool_registry,
                        critic=self.response_validator,
                        system_prompt=self.system_prompt
                    )
                    logger.info("switched_to_shopify_orchestrator", agent_id=agent_id)
            else:
                logger.warning("agent_not_found", agent_id=agent_id)
                self.agent_config = {}
                self.system_prompt = ""
                
        except Exception as e:
            logger.error("agent_config_load_error", error=str(e))
            self.agent_config = {}
            self.system_prompt = ""
            if self.orchestrator:
                self.orchestrator.system_prompt = ""

    
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
            
            # Retrieve recent history for context (last 6 messages)
            recent_messages = await self.short_term.get_recent_messages(
                conversation_id=conversation_id,
                limit=6
            )
            
            # Build chat history AND extract session state (e.g. cart_id) from
            # previous assistant message metadata so the agent can reuse the cart.
            chat_history = []
            session_state: dict = {}
            for msg in recent_messages:
                role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
                chat_history.append({
                    "role": role,
                    "content": msg.content,
                    "metadata": msg.metadata or {}
                })
                # The most recent assistant message that carried session state wins.
                if role == "assistant":
                    meta = msg.metadata or {}
                    if "cart_id" in meta:
                        session_state["cart_id"] = meta["cart_id"]
                    if "captured_ids" in meta:
                        session_state["captured_ids"] = meta.get("captured_ids", {})
                    if "last_searched" in meta:
                        session_state["last_searched"] = meta.get("last_searched", {})

            context_dict = {"memory": memory_context, "session_state": session_state}
            
            # 4. RUN SOTA ORCHESTRATOR LOOP
            # Instead of linear retrieve->generate, let the agent plan and execute.
            from agent_runtime.orchestrator_shopify import ShopifyOrchestrator
            
            if isinstance(self.orchestrator, ShopifyOrchestrator):
                agent_result = await self.orchestrator.run(
                    query=request.message,
                    chat_history=chat_history,
                    context=context_dict
                )
            else:
                agent_result = await self.orchestrator.run(
                    query=request.message,
                    context={"memory": memory_context}
                )
            
            response_text = agent_result.answer
            # Note: Validation now happens inside Orchestrator via Critic loop
            # Check agent_result.metadata for validation_passed and validation_issues
            
            # Extract cart_id from tool results for persistence across turns
            saved_cart_id = None
            for _, tool_result in agent_result.metadata.get("tool_results", {}).items():
                if hasattr(tool_result, "metadata") and tool_result.metadata:
                    cart = tool_result.metadata.get("cart")
                    if cart and isinstance(cart, dict) and cart.get("cart_id"):
                        saved_cart_id = cart["cart_id"]
                        break
            
            # If we have an existing cart_id from session_state and no new one was created, keep it
            if not saved_cart_id and session_state.get("cart_id"):
                saved_cart_id = session_state["cart_id"]

            # 5. Store assistant response
            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=response_text,
                metadata={
                    "user_id": user_id,
                    "agent_steps": agent_result.metadata.get("steps_executed", 0),
                    "validation_passed": agent_result.metadata.get("validation_passed"),
                    "validation_issues": agent_result.metadata.get("validation_issues", []),
                    "plan": agent_result.metadata.get("plan"),
                    "cart_id": saved_cart_id,
                    "captured_ids": agent_result.metadata.get("captured_ids"),
                    "last_searched": agent_result.metadata.get("last_searched"),
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
                content="Thinking...",
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
            
            # Phase 6: Use SOTA Orchestrator for Planning, Execution, and Critic loop
            yield StreamingMessageResponse(
                type="status",
                content="Planning and searching...",
                conversation_id=conversation_id
            )
            
            # Retrieve recent history for context (last 6 messages)
            recent_messages = await self.short_term.get_recent_messages(
                conversation_id=conversation_id,
                limit=6
            )
            
            # Build chat history AND extract session state (e.g. cart_id) from
            # previous assistant message metadata so the agent can reuse the cart.
            chat_history = []
            session_state: dict = {}
            for msg in recent_messages:
                role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
                chat_history.append({
                    "role": role,
                    "content": msg.content,
                    "metadata": msg.metadata or {}
                })
                # The most recent assistant message that carried session state wins.
                if role == "assistant":
                    meta = msg.metadata or {}
                    if "cart_id" in meta:
                        session_state["cart_id"] = meta["cart_id"]
                    if "checkout_url" in meta:
                        session_state["checkout_url"] = meta["checkout_url"]
                    if "cart_lines" in meta:
                        session_state["cart_lines"] = meta["cart_lines"]
                    if "captured_ids" in meta:
                        session_state["captured_ids"] = meta.get("captured_ids", {})
                    if "last_searched" in meta:
                        session_state["last_searched"] = meta.get("last_searched", {})
            
            from agent_runtime.orchestrator_shopify import ShopifyOrchestrator
            
            if isinstance(self.orchestrator, ShopifyOrchestrator):
                # Define a queue to capture status updates from the orchestrator
                status_queue = asyncio.Queue()
                
                async def on_status(text: str):
                    await status_queue.put(text)

                # Run the orchestrator in a background task
                orchestrator_task = asyncio.create_task(
                    self.orchestrator.run(
                        query=request.message,
                        chat_history=chat_history,
                        context={"session_state": session_state},
                        on_status=on_status
                    )
                )

                # While the orchestrator is running, yield any status updates
                while not orchestrator_task.done() or not status_queue.empty():
                    if not status_queue.empty():
                        status_text = status_queue.get_nowait()
                        yield StreamingMessageResponse(
                            type="status",
                            content=status_text,
                            conversation_id=conversation_id
                        )
                    else:
                        # Brief wait to avoid busy-waiting
                        await asyncio.sleep(0.1)

                # Get the final result
                agent_result = await orchestrator_task
            else:
                # Standard execution for non-Shopify agents
                agent_result = await self.orchestrator.run(
                    query=request.message,
                    chat_history=chat_history,
                    context={"session_state": session_state}
                )
            
            # Extract final answer
            full_response = agent_result.answer
            
            # Stream the result word by word (to maintain UI experience)
            words = full_response.split(' ')
            for i, word in enumerate(words):
                # Add space back if not the last word
                display_word = word + (" " if i < len(words) - 1 else "")
                yield StreamingMessageResponse(
                    type="content",
                    content=display_word,
                    conversation_id=conversation_id
                )
                # Small artificial delay to keep UI smooth
                await asyncio.sleep(0.02)
            
            # Phase 4: Validate streaming response
            # Orchestrator already ran the Critic loop and self-correction
            # So we just store the final answer and its metadata
            
            # Extract cart_id from tool results for persistence across turns
            saved_cart_id = None
            for _, tool_result in agent_result.metadata.get("tool_results", {}).items():
                if hasattr(tool_result, "metadata") and tool_result.metadata:
                    cart = tool_result.metadata.get("cart")
                    if cart and isinstance(cart, dict) and cart.get("cart_id"):
                        saved_cart_id = cart["cart_id"]
                        break
            
            # If we have an existing cart_id from session_state and no new one was created, keep it
            if not saved_cart_id and session_state.get("cart_id"):
                saved_cart_id = session_state["cart_id"]
            
            logger.info("cart_persistence_final_state", 
                saved_cart_id=saved_cart_id, 
                from_session=session_state.get("cart_id"),
                newly_found=any("cart" in str(tr.metadata) for tr in agent_result.metadata.get("tool_results", {}).values() if hasattr(tr, 'metadata') and tr.metadata)
            )

            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=full_response,
                metadata={
                    "user_id": user_id,
                    "agent_steps": agent_result.metadata.get("steps_executed", 0),
                    "validation_passed": agent_result.metadata.get("validation_passed"),
                    "validation_issues": agent_result.metadata.get("validation_issues", []),
                    "plan": agent_result.metadata.get("plan"),
                    "cart_id": saved_cart_id,
                    "checkout_url": agent_result.metadata.get("checkout_url"),
                    "cart_lines": agent_result.metadata.get("cart_lines"),
                    "captured_ids": agent_result.metadata.get("captured_ids"),
                    "last_searched": agent_result.metadata.get("last_searched"),
                }
            )

            
            # Sync to Strapi dashboard (fire-and-forget — never blocks streaming)
            self.strapi.sync_conversation(
                conversation_id=conversation_id,
                user_message=request.message,
                assistant_message=full_response,
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
            
            # Send final metadata (orchestrator handles retrieval internally)
            # Extract tool results from orchestrator metadata for citations, products, and dealers
            tool_results = agent_result.metadata.get("tool_results", {})
            citations = []
            products = []
            dealers = []
            
            # tool_results is a dict mapping step_id -> ToolResult
            for step_id, tool_result in tool_results.items():
                if hasattr(tool_result, 'metadata') and tool_result.metadata:
                    result_metadata = tool_result.metadata
                    
                    # Extract products and dealers
                    if 'products' in result_metadata:
                        products.extend(result_metadata['products'])
                    if 'dealers' in result_metadata:
                        dealers.extend(result_metadata['dealers'])
                    
                    
                    # Extract citations from sources (sources are doc_id strings)
                    if 'sources' in result_metadata:
                        # Log metadata for debugging products issue
                        products_list = result_metadata.get('products', [])
                        if products_list:
                            logger.info("First product keys", keys=list(products_list[0].keys()))
                            logger.info("First product sample", sample=str(products_list[0])[:200])
                            
                        logger.info("Tool result metadata", step_id=step_id, 
                                   products_count=len(products_list),
                                   dealers_count=len(result_metadata.get('dealers', [])),
                                   sources_count=len(result_metadata.get('sources', [])))
                        
                        confidence = min(1.0, max(0.0, float(result_metadata.get('confidence', 1.0))))
                        
                        for source in result_metadata['sources'][:5]:  # Top 5 citations
                            # source is just a doc_id string like "essco-bathware_product_EOS-CHR-491"
                            doc_id = source if isinstance(source, str) else source.get("title", str(source))
                            citations.append({
                                "doc_id": doc_id,
                                "title": doc_id,
                                "confidence": confidence,
                                "url": None,
                                "snippet": None
                            })
            
            # Sanitize products/dealers: strip MongoDB ObjectId, datetime, and other
            # non-JSON-serializable types before they reach model_dump_json().
            safe_products = [_sanitize_for_json(p) for p in products]
            safe_dealers  = [_sanitize_for_json(d) for d in dealers]

            # Deduplicate products and dealers by ID
            unique_products = {p['id']: p for p in safe_products if p.get('id')}.values()
            unique_dealers  = {d['id']: d for d in safe_dealers  if d.get('id')}.values()

            yield StreamingMessageResponse(
                type="metadata",
                content="",
                conversation_id=conversation_id,
                citations=citations,
                context_used=len(tool_results),
                confidence_score=min(1.0, max(0.0, float(agent_result.metadata.get("validation_confidence", 1.0)))),
                products=list(unique_products),
                dealers=list(unique_dealers)
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
    
    async def inject_history(self, conversation_id: str, agent_id: str, messages: list) -> None:
        """Inject messages from human takeover into short-term memory so the AI
        has full context when it resumes control.

        Each entry in `messages` is a dict with 'role' ('user'|'assistant') and 'content'.
        A synthetic system-level summary is prepended so the LLM understands what happened.
        """
        if not messages:
            return
        try:
            await self._load_agent_config(agent_id)
            await self._ensure_memory_initialized()

            # Synthetic notice so the LLM is aware of the gap
            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="[System: The following messages were exchanged while a human support agent had control of this conversation.]",
                metadata={"injected": True, "source": "human_takeover"},
            )

            for msg in messages:
                role_str = msg.get("role", "user")
                content = msg.get("content", "")
                memory_role = MessageRole.USER if role_str == "user" else MessageRole.ASSISTANT
                await self.short_term.add_message(
                    conversation_id=conversation_id,
                    role=memory_role,
                    content=content,
                    metadata={"injected": True, "source": "human_takeover"},
                )

            logger.info(
                "takeover_history_injected",
                conversation_id=conversation_id,
                messages_count=len(messages),
            )
        except Exception as e:
            logger.warning("inject_history_failed", error=str(e), conversation_id=conversation_id)

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
