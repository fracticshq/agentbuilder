"""
Message Service - Core business logic for processing messages
Integrates Phase 5 Memory System with retrieval and LLM generation.
Phase 4: Response validation to prevent hallucinations.
"""

import asyncio
import inspect
import json
import re
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
from ..monitoring import AGENT_FALLBACK_COUNT, GUARDRAIL_COUNT, MESSAGE_COUNT, MESSAGE_DURATION
from .response_validator import ResponseValidator  # Phase 4
from .strapi_client import StrapiClient
from .runtime_settings_service import RuntimeSettingsService
from .tool_config_secrets import decrypt_full_agent_configuration_for_runtime
from .capability_firewall import CapabilityDecision, CapabilityFirewall
from .observability_service import ObservabilityService
from .prompt_assembler import PromptAssembler
from .skill_registry import BuiltInSkillRegistry
from .tool_registry import ApiDataSourceTool, ToolRegistryService

logger = structlog.get_logger(__name__)


SENSITIVE_DATA_PATTERNS = [
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:api[_-]?key|secret|password|token)\s*[:=]\s*\S+", re.IGNORECASE),
]

PROMPT_ATTACK_PATTERNS = [
    re.compile(r"ignore (?:all )?(?:previous|prior) instructions", re.IGNORECASE),
    re.compile(r"reveal (?:your )?(?:system|developer) prompt", re.IGNORECASE),
    re.compile(r"show me (?:your )?(?:system|developer) prompt", re.IGNORECASE),
]

GUARDRAIL_SENSITIVE_MESSAGE = (
    "Please do not share sensitive personal data, passwords, tokens, or payment details here. "
    "I can still help with product, dealer, order, and general pre-sales questions."
)
GUARDRAIL_POLICY_MESSAGE = (
    "I can’t help with requests that try to bypass the assistant’s safety or operating rules. "
    "I can help with product and brand questions instead."
)
GUARDRAIL_ESCALATION_MESSAGE = (
    "This looks like it may need human support. I’m flagging it for assistance and can still help "
    "with general product information in the meantime."
)
GUARDRAIL_OFF_DOMAIN_MESSAGE = (
    "I can only help with questions related to this brand, its products, dealers, policies, "
    "and support information."
)
LOW_CONFIDENCE_MESSAGE = (
    "I don’t have enough verified information in the knowledge base to answer that reliably. "
    "Please share a little more detail or contact the brand team for confirmation."
)


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


def _extract_tool_result_metadata(tool_results: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Normalize citations, products, and dealers from orchestrator tool metadata."""
    citations: list[dict] = []
    products: list[dict] = []
    dealers: list[dict] = []

    for step_id, tool_result in tool_results.items():
        if not hasattr(tool_result, "metadata") or not tool_result.metadata:
            continue

        result_metadata = tool_result.metadata

        if "products" in result_metadata:
            products.extend(result_metadata["products"])
        if "dealers" in result_metadata:
            dealers.extend(result_metadata["dealers"])

        if "sources" not in result_metadata:
            continue

        confidence = min(1.0, max(0.0, float(result_metadata.get("confidence", 1.0))))
        for source in result_metadata["sources"][:5]:
            doc_id = source if isinstance(source, str) else source.get("title", str(source))
            citations.append({
                "doc_id": doc_id,
                "title": doc_id,
                "confidence": confidence,
                "url": None,
                "snippet": None,
            })

        logger.info(
            "tool_result_metadata",
            step_id=step_id,
            products_count=len(result_metadata.get("products", [])),
            dealers_count=len(result_metadata.get("dealers", [])),
            sources_count=len(result_metadata.get("sources", [])),
        )

    safe_products = [_sanitize_for_json(product) for product in products]
    safe_dealers = [_sanitize_for_json(dealer) for dealer in dealers]
    return citations, safe_products, safe_dealers


def _entity_identity(entity: dict, *keys: str) -> Optional[str]:
    """Build a stable identity string from the first populated key."""
    for key in keys:
        value = entity.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return f"{key}:{normalized}"
    return None


def _deduplicate_entities(entities: list[dict], *identity_keys: str) -> list[dict]:
    """Deduplicate metadata entities while tolerating inconsistent provider schemas."""
    unique_entities: list[dict] = []
    seen_keys: set[str] = set()

    for entity in entities:
        identity = _entity_identity(entity, *identity_keys)
        if identity is None:
            identity = f"json:{json.dumps(entity, sort_keys=True, default=str)}"

        if identity in seen_keys:
            continue

        seen_keys.add(identity)
        unique_entities.append(entity)

    return unique_entities


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
        self.agent_record: dict = {}
        self.system_prompt = None
        self.prompt_metadata: dict = {}
        self.runtime_settings_service = RuntimeSettingsService(settings)
        self.prompt_assembler = PromptAssembler()
        self.capability_firewall = CapabilityFirewall()
        self.skill_registry = BuiltInSkillRegistry()
        self.external_tool_registry = ToolRegistryService()
        
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
        
        # Initialize retrieval pipeline configuration.
        self.retrieval_config = RetrievalConfig(
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
        self.retrieval_pipeline = None
        self.llm_provider = None
        
        # Phase 4: Initialize response validator
        self.response_validator = ResponseValidator(strict_mode=True)
        
        # Phase 6: Initialize SOTA Orchestrator with Critic
        self.tool_registry = ToolRegistry()
        self.orchestrator = None

        # Strapi dashboard sync (fire-and-forget, non-blocking)
        self.strapi = StrapiClient(
            base_url=settings.STRAPI_URL,
            api_token=settings.STRAPI_API_TOKEN,
        )
        self.observability = ObservabilityService()

        logger.info("message_service_initialized", brand_id=self.brand_id)

    def _short_term_memory_enabled(self) -> bool:
        config = self.agent_config or {}
        memory = config.get("memory") or {}
        short_term = memory.get("short_term") or {}
        if "enabled" in short_term:
            return bool(short_term.get("enabled"))
        features = config.get("features") or {}
        return bool(features.get("conversation_memory", True))

    def _long_term_memory_enabled(self) -> bool:
        config = self.agent_config or {}
        memory = config.get("memory") or {}
        long_term = memory.get("long_term") or {}
        return bool(long_term.get("enabled", False))

    def _agent_rag_config(self) -> dict:
        config = self.agent_config or {}
        rag = config.get("rag")
        return rag if isinstance(rag, dict) else {}

    def _rag_enabled(self) -> bool:
        rag = self._agent_rag_config()
        if "enabled" in rag:
            return bool(rag.get("enabled"))
        return True

    def _agent_max_chunks(self) -> int:
        rag = self._agent_rag_config()
        retrieval = rag.get("retrieval") or {}
        rerank = retrieval.get("rerank") or {}
        try:
            if rerank.get("enabled") and rerank.get("top_k"):
                return max(1, min(50, int(rerank["top_k"])))
            if retrieval.get("top_k"):
                return max(1, min(50, int(retrieval["top_k"])))
        except (TypeError, ValueError):
            pass
        return 12

    def _build_retrieval_config(self) -> RetrievalConfig:
        """Build the retrieval config, applying per-agent RAG overrides when configured."""
        base = RetrievalConfig(
            vector_enabled=True,
            vector_top_k=50,
            similarity_threshold=0.7,
            bm25_enabled=True,
            bm25_top_k=50,
            rrf_k=60,
            rerank_enabled=True,
            rerank_top_k=12,
            brand_boost_enabled=bool(self.brand_id),
            page_boost_enabled=True,
            dedup_enabled=True,
        )
        rag = self._agent_rag_config()
        retrieval = rag.get("retrieval") or {}
        rerank = retrieval.get("rerank") or {}
        try:
            threshold = retrieval.get("similarity_threshold")
            if threshold is not None:
                base.similarity_threshold = min(1.0, max(0.0, float(threshold)))
        except (TypeError, ValueError):
            pass
        if "enabled" in rerank:
            base.rerank_enabled = bool(rerank.get("enabled"))
        base.rerank_top_k = self._agent_max_chunks()
        return base

    def _memory_runtime_metadata(self) -> dict:
        return {
            "short_term": {
                "enabled": self._short_term_memory_enabled(),
                "mode": "conversation_history",
            },
            "long_term": {
                "enabled": self._long_term_memory_enabled(),
                "status": "enabled" if self._long_term_memory_enabled() else "needs_privacy_setup",
            },
        }

    def _evaluate_capability_scope(self, message: str) -> CapabilityDecision:
        contract = self.capability_firewall.build_contract(
            brand_slug=self.brand_id,
            agent_config=self.agent_config or {},
            agent_record=self.agent_record or {},
            system_prompt=self.system_prompt or "",
        )
        return self.capability_firewall.evaluate(message, contract)

    def _prefix_scope_notice(self, response_text: str, guardrail_decision: dict) -> str:
        if guardrail_decision.get("action") != "filter":
            return response_text
        notice = guardrail_decision.get("message") or ""
        if not notice:
            return response_text
        return f"{notice}\n\n{response_text}"

    def _evaluate_pre_response_guardrails(self, message: str, escalations: list) -> dict:
        if any(pattern.search(message or "") for pattern in SENSITIVE_DATA_PATTERNS):
            GUARDRAIL_COUNT.labels(action="block", reason="sensitive_data").inc()
            return {
                "action": "block",
                "reason": "sensitive_data",
                "message": GUARDRAIL_SENSITIVE_MESSAGE,
            }

        if any(pattern.search(message or "") for pattern in PROMPT_ATTACK_PATTERNS):
            GUARDRAIL_COUNT.labels(action="block", reason="prompt_attack").inc()
            return {
                "action": "block",
                "reason": "prompt_attack",
                "message": GUARDRAIL_POLICY_MESSAGE,
            }

        scope_decision = self._evaluate_capability_scope(message)
        if scope_decision.action == "block":
            GUARDRAIL_COUNT.labels(action="block", reason=scope_decision.reason).inc()
            return {
                "action": "block",
                "reason": scope_decision.reason,
                "message": scope_decision.message or GUARDRAIL_OFF_DOMAIN_MESSAGE,
                "safe_query": scope_decision.safe_query,
                "capability_scope": scope_decision.to_metadata(),
            }
        if scope_decision.action == "filter":
            GUARDRAIL_COUNT.labels(action="filter", reason=scope_decision.reason).inc()
            return {
                "action": "filter",
                "reason": scope_decision.reason,
                "message": scope_decision.message,
                "safe_query": scope_decision.safe_query,
                "capability_scope": scope_decision.to_metadata(),
            }

        for escalation in escalations or []:
            severity = getattr(escalation, "severity", None)
            if isinstance(escalation, dict):
                severity = escalation.get("severity")
            if str(severity or "").lower() in {"high", "critical"}:
                GUARDRAIL_COUNT.labels(action="escalate", reason="safety_escalation").inc()
                return {
                    "action": "escalate",
                    "reason": "safety_escalation",
                    "message": GUARDRAIL_ESCALATION_MESSAGE,
                }

        GUARDRAIL_COUNT.labels(action="allow", reason="none").inc()
        return {"action": "allow", "reason": "none", "message": ""}

    def _apply_post_response_guardrails(self, response_text: str, metadata: dict) -> tuple[str, dict]:
        confidence = float(metadata.get("validation_confidence", 1.0) or 1.0)
        threshold = getattr(self.settings, "CONFIDENCE_THRESHOLD", 0.70)
        try:
            threshold_value = float(threshold)
        except (TypeError, ValueError):
            threshold_value = 0.70
        if confidence < threshold_value:
            GUARDRAIL_COUNT.labels(action="fallback", reason="low_confidence").inc()
            next_metadata = {
                **metadata,
                "guardrail_action": "fallback",
                "guardrail_reason": "low_confidence",
                "original_confidence": confidence,
            }
            return LOW_CONFIDENCE_MESSAGE, next_metadata

        return response_text, metadata

    async def _store_guardrail_response(
        self,
        *,
        conversation_id: str,
        user_id: str,
        agent_id: str,
        user_message: str,
        decision: dict,
    ) -> MessageResponse:
        response_text = decision["message"]
        if self._short_term_memory_enabled():
            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=response_text,
                metadata={
                    "user_id": user_id,
                    "guardrail_action": decision["action"],
                    "guardrail_reason": decision["reason"],
                    "capability_scope": decision.get("capability_scope"),
                    "validation_passed": False,
                },
            )
        self.strapi.sync_conversation(
            conversation_id=conversation_id,
            user_message=user_message,
            assistant_message=response_text,
            brand_slug=self.brand_id,
            agent_id=agent_id,
        )
        await self.observability.track_event(
            event_type="guardrail_decision",
            brand_slug=self.brand_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            payload={
                "action": decision["action"],
                "reason": decision["reason"],
                "mode": "sync",
                "status": f"guardrail_{decision['action']}",
                "capability_scope": decision.get("capability_scope"),
            },
        )
        MESSAGE_COUNT.labels(status=f"guardrail_{decision['action']}").inc()
        return MessageResponse(
            message=response_text,
            conversation_id=conversation_id,
            citations=[],
            context_used=0,
            confidence_score=1.0,
            processing_time_ms=0,
        )

    def _build_llm_provider(self, runtime_config: dict[str, Optional[str]]):
        """Build an LLM provider from resolved runtime settings."""
        resolved_provider = runtime_config.get("provider_name") or "openai"
        api_key = runtime_config.get("api_key") or ""
        resolved_model = runtime_config.get("model") or ""
        provider_kwargs = {
            "base_url": runtime_config.get("base_url"),
            "api_version": runtime_config.get("api_version"),
            "azure_endpoint": runtime_config.get("azure_endpoint"),
            "deployment_name": runtime_config.get("deployment_name"),
        }
        try:
            provider = create_provider_from_env(
                provider_name=resolved_provider,
                api_key=api_key,
                model=resolved_model,
                **provider_kwargs,
            )
            logger.info("llm_provider_configured", provider=resolved_provider, model=resolved_model)
            return provider
        except ValueError as e:
            logger.error("llm_provider_init_failed", provider=resolved_provider, model=resolved_model, error=str(e))
            raise

    async def _configure_retrieval_pipeline(self, brand_slug: Optional[str]) -> None:
        if not self._rag_enabled():
            self.retrieval_pipeline = None
            self.tool_registry = ToolRegistry()
            logger.info("retrieval_disabled_by_agent_config", brand_id=brand_slug, agent_id=self.agent_id)
            return

        self.retrieval_config = self._build_retrieval_config()
        voyage_config = await self.runtime_settings_service.get_voyage_runtime_config()
        try:
            self.retrieval_pipeline = RetrievalPipeline(
                config=self.retrieval_config,
                brand_id=brand_slug,
                voyage_api_key=voyage_config["api_key"] or None,
                voyage_model=voyage_config["model"],
                voyage_base_url=voyage_config["base_url"],
                rerank_api_key=voyage_config["api_key"] or None,
                rerank_model=voyage_config["rerank_model"],
                rerank_base_url=voyage_config["base_url"],
            )
            logger.info("retrieval_pipeline_initialized", brand_id=brand_slug)
        except Exception as e:
            logger.warning("retrieval_pipeline_init_failed", brand_id=brand_slug, error=str(e))
            self.retrieval_pipeline = None

        self.tool_registry = ToolRegistry()
        if self.retrieval_pipeline:
            self.tool_registry.register(RetrievalTool(self.retrieval_pipeline))

    async def _configure_runtime_dependencies(
        self,
        *,
        provider_name: Optional[str] = None,
        model: Optional[str] = None,
        brand_slug: Optional[str] = None,
    ) -> None:
        await self._configure_retrieval_pipeline(brand_slug)

        runtime_config = await self.runtime_settings_service.get_llm_runtime_config(
            provider_name=provider_name,
            model=model,
        )
        self.llm_provider = self._build_llm_provider(runtime_config)
        self.orchestrator = Orchestrator(
            llm=self.llm_provider,
            tools=self.tool_registry,
            critic=self.response_validator,
            system_prompt=self.system_prompt,
        )

        strapi_runtime_config = await self.runtime_settings_service.get_strapi_runtime_config()
        self.strapi = StrapiClient(
            base_url=strapi_runtime_config.get("base_url") or "",
            api_token=strapi_runtime_config.get("api_token") or "",
        )
        logger.info(
            "strapi_client_configured",
            base_url=strapi_runtime_config.get("base_url") or "",
            enabled=bool(strapi_runtime_config.get("base_url") and strapi_runtime_config.get("api_token")),
        )

    def _register_configured_capabilities(self, config: dict) -> dict:
        """Register only skills/tools explicitly enabled on this agent."""
        registered_skills = []
        registered_tools = []

        for skill_tool in self.skill_registry.enabled_skill_tools(config):
            self.tool_registry.register(skill_tool)
            registered_skills.append(skill_tool.name)

        for external_tool in self.external_tool_registry.enabled_runtime_tools(config):
            self.tool_registry.register(external_tool)
            registered_tools.append(external_tool.name)

        api_data_source = config.get("api_data_source") or {}
        if (
            isinstance(api_data_source, dict)
            and api_data_source.get("enabled")
            and str(api_data_source.get("url") or "").strip()
        ):
            api_tool = ApiDataSourceTool(api_data_source)
            self.tool_registry.register(api_tool)
            registered_tools.append(api_tool.name)

        if registered_skills or registered_tools:
            logger.info(
                "agent_capabilities_registered",
                agent_id=self.agent_id,
                skills=registered_skills,
                tools=registered_tools,
            )

        return {
            "skills": registered_skills,
            "tools": registered_tools,
        }
    
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
                
                await self._configure_retrieval_pipeline(brand_slug)
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
            self.agent_id = agent_id
            # Initialize brand database first
            await self._initialize_brand_database(agent_id)
            
            # Load from system agents collection
            system_db = connection_manager.get_system_db()
            agents_collection = system_db["agents"]
            agent = await agents_collection.find_one({"id": agent_id})
            
            if agent:
                self.agent_record = agent
                config = decrypt_full_agent_configuration_for_runtime(
                    agent.get("configuration", {}),
                    self.runtime_settings_service,
                )
                normalized_prompt_layers = self.prompt_assembler.normalize_prompt_layers(agent, config)
                self.agent_config = {
                    **config,
                    "prompt_layers": normalized_prompt_layers,
                }
                prompt_assembly = self.prompt_assembler.assemble_agent_prompt(agent, self.agent_config)
                self.system_prompt = prompt_assembly.prompt
                self.prompt_metadata = {
                    "prompt_version": prompt_assembly.prompt_version,
                    "cacheable_prefix_hash": prompt_assembly.cacheable_prefix_hash,
                    "layers": prompt_assembly.layer_names,
                }
                self.brand_id = agent.get("brand_slug", self.brand_id)
                llm_config = config.get("llm", {})
                llm_provider_name = llm_config.get("provider")
                llm_model = llm_config.get("model")
                await self._configure_runtime_dependencies(
                    provider_name=llm_provider_name,
                    model=llm_model,
                    brand_slug=self.brand_id,
                )
                capability_context = self._register_configured_capabilities(config)
                self.prompt_metadata["capabilities"] = capability_context
                
                # Sync system prompt to Orchestrator
                if self.orchestrator:
                    self.orchestrator.system_prompt = self.system_prompt
                
                logger.info("agent_config_loaded", 
                           agent_id=agent_id, 
                           brand_id=self.brand_id,
                           has_system_prompt=bool(self.system_prompt),
                           prompt_version=self.prompt_metadata.get("prompt_version"),
                           prompt_hash=self.prompt_metadata.get("cacheable_prefix_hash"))
                           
                # Initialize remote MCP tools if Shopify is selected
                if config.get("data_source") == "shopify":
                    from tools.mcp_client import McpClient
                    from agent_runtime.orchestrator_shopify import ShopifyOrchestrator
                    
                    # For local development we assume port 3005 for the Shopify MCP Service
                    # In production this would be loaded from settings
                    mcp_endpoint = self.settings.SHOPIFY_MCP_URL if hasattr(self.settings, 'SHOPIFY_MCP_URL') else "http://localhost:3005/mcp"
                    
                    # Extract per-agent Shopify credentials from dashboard-managed config.
                    # Store identity and tokens must not fall back to global env values in production.
                    shopify_conf = config.get("shopify", {})
                    shopify_url = (
                        shopify_conf.get("shop_url") or 
                        config.get("shopify_shop_url")
                    )
                    shopify_token = (
                        shopify_conf.get("access_token") or
                        config.get("shopify_access_token") or 
                        config.get("shopify_admin_token")
                    )

                    if not shopify_url or not shopify_token:
                        logger.warning(
                            "shopify_credentials_missing",
                            agent_id=agent_id,
                            has_shop_url=bool(shopify_url),
                            has_access_token=bool(shopify_token),
                        )
                        
                    mcp_headers = {
                        "x-shopify-shop-url": str(shopify_url or ""),
                        "x-shopify-admin-token": str(shopify_token or "")
                    }
                    
                    # Also try to get a customer access token from config or settings
                    customer_token = (
                        shopify_conf.get("customer_access_token") or
                        config.get("shopify_customer_access_token")
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
                self.agent_record = {}
                self.agent_config = {}
                self.system_prompt = ""
                self.prompt_metadata = {}
                await self._configure_runtime_dependencies(
                    brand_slug=self.brand_id,
                )
                
        except Exception as e:
            logger.error("agent_config_load_error", error=str(e))
            self.agent_record = {}
            self.agent_config = {}
            self.system_prompt = ""
            self.prompt_metadata = {}
            if self.orchestrator:
                self.orchestrator.system_prompt = ""

    def _build_prompt_runtime_context(self, request: MessageRequest) -> dict:
        """Build typed runtime variables that are appended after the stable prompt prefix."""
        if not self.agent_config:
            return {}

        return self.prompt_assembler.build_runtime_context(
            config=self.agent_config,
            page_context=request.page_context,
            filters=request.filters,
        )

    def _normalized_request_page_context(self, request: MessageRequest) -> dict | None:
        url_context_config = (self.agent_config or {}).get("url_context_boost") or {}
        if isinstance(url_context_config, dict) and url_context_config.get("enabled") is False:
            return None
        if not request.page_context:
            return None
        page_context = (
            request.page_context.model_dump()
            if hasattr(request.page_context, "model_dump")
            else dict(request.page_context)
        )
        if "meta" not in page_context and isinstance(page_context.get("metadata"), dict):
            page_context["meta"] = page_context["metadata"]
        return page_context

    def _bind_request_page_context_to_retrieval(self, request: MessageRequest) -> None:
        knowledge_tool = self.tool_registry.get("knowledge_search") if self.tool_registry else None
        if knowledge_tool is not None and hasattr(knowledge_tool, "page_context"):
            setattr(knowledge_tool, "page_context", self._normalized_request_page_context(request))

    
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
            short_term_enabled = self._short_term_memory_enabled()
            long_term_enabled = self._long_term_memory_enabled()
            
            # Generate conversation ID if not provided
            conversation_id = request.conversation_id or str(uuid.uuid4())
            user_id = request.user_id or "anonymous"
            self._bind_request_page_context_to_retrieval(request)
            
            logger.info(
                "message_processing_start",
                conversation_id=conversation_id,
                user_id=user_id,
                brand_id=self.brand_id,
            )
            
            escalations = []
            if self.memory_config.ENABLE_GRAPH_RULES and self.graph:
                escalations = await self.graph.check_escalation(request.message)

            guardrail_decision = self._evaluate_pre_response_guardrails(request.message, escalations)
            if guardrail_decision["action"] in {"block", "escalate"}:
                return await self._store_guardrail_response(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    user_message=request.message,
                    decision=guardrail_decision,
                )

            runtime_message = guardrail_decision.get("safe_query") or request.message
            capability_scope = guardrail_decision.get("capability_scope")
            user_metadata = {
                "user_id": user_id,
                "page_context": request.page_context or {},
            }
            if capability_scope:
                user_metadata["capability_scope"] = capability_scope
                user_metadata["original_user_message"] = request.message

            # 1. Store only the executable in-scope user work in short-term memory.
            if short_term_enabled:
                await self.short_term.add_message(
                    conversation_id=conversation_id,
                    role=MessageRole.USER,
                    content=runtime_message,
                    metadata=user_metadata,
                )

            # 3. Build context for the agent (pass safe context)
            memory_context = await self._build_memory_context(
                conversation_id=conversation_id,
                user_id=user_id,
                query=runtime_message,
                escalations=escalations,
            )
            
            # Retrieve recent history for context (last 6 messages)
            recent_messages = []
            if short_term_enabled:
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

            context_dict = {
                "memory": memory_context,
                "session_state": session_state,
                "prompt_runtime": self._build_prompt_runtime_context(request),
                "prompt_metadata": self.prompt_metadata,
                "capability_scope": capability_scope,
            }
            
            # 4. RUN SOTA ORCHESTRATOR LOOP
            # Instead of linear retrieve->generate, let the agent plan and execute.
            from agent_runtime.orchestrator_shopify import ShopifyOrchestrator
            
            if isinstance(self.orchestrator, ShopifyOrchestrator):
                agent_result = await self.orchestrator.run(
                    query=runtime_message,
                    chat_history=chat_history,
                    context=context_dict
                )
            else:
                agent_result = await self.orchestrator.run(
                    query=runtime_message,
                    context=context_dict
                )
            
            response_text, agent_metadata = self._apply_post_response_guardrails(
                agent_result.answer,
                agent_result.metadata,
            )
            if capability_scope:
                response_text = self._prefix_scope_notice(response_text, guardrail_decision)
                agent_metadata = {
                    **agent_metadata,
                    "capability_scope": capability_scope,
                    "guardrail_action": agent_metadata.get("guardrail_action") or guardrail_decision["action"],
                    "guardrail_reason": agent_metadata.get("guardrail_reason") or guardrail_decision["reason"],
                }
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
            if short_term_enabled:
                await self.short_term.add_message(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=response_text,
                    metadata={
                        "user_id": user_id,
                        "agent_steps": agent_metadata.get("steps_executed", 0),
                        "validation_passed": agent_metadata.get("validation_passed"),
                        "validation_issues": agent_metadata.get("validation_issues", []),
                        "guardrail_action": agent_metadata.get("guardrail_action"),
                        "guardrail_reason": agent_metadata.get("guardrail_reason"),
                        "fallback_stage": agent_metadata.get("fallback_stage"),
                        "fallback_reason": agent_metadata.get("fallback_reason"),
                        "prompt_version": self.prompt_metadata.get("prompt_version"),
                        "prompt_hash": self.prompt_metadata.get("cacheable_prefix_hash"),
                        "prompt_layers": self.prompt_metadata.get("layers", []),
                        "capability_scope": agent_metadata.get("capability_scope"),
                        "plan": agent_metadata.get("plan"),
                        "cart_id": saved_cart_id,
                        "captured_ids": agent_metadata.get("captured_ids"),
                        "last_searched": agent_metadata.get("last_searched"),
                    }
                )

            self.strapi.sync_conversation(
                conversation_id=conversation_id,
                user_message=request.message,
                assistant_message=response_text,
                brand_slug=self.brand_id,
                agent_id=agent_id,
            )
            
            # 6. Extract Facts & Auto-Summary (Async)
            if short_term_enabled and long_term_enabled and self.memory_config.ENABLE_FACT_EXTRACTION:
                messages = await self.short_term.get_recent_messages(conversation_id, limit=10)
                await self.episodic.extract_and_store_facts(
                    user_id=user_id,
                    messages=messages,
                    conversation_id=conversation_id,
                )

            if short_term_enabled and self.memory_config.ENABLE_AUTO_SUMMARY:
                if await self.short_term.should_summarize(conversation_id):
                    await self.short_term.trigger_summary(conversation_id)

            tool_results = agent_metadata.get("tool_results", {})
            citations, _products, _dealers = _extract_tool_result_metadata(tool_results)
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            status_label = "fallback" if agent_metadata.get("fallback") else "success"
            if agent_metadata.get("guardrail_action") == "fallback":
                status_label = "guardrail_fallback"
            if agent_metadata.get("fallback"):
                AGENT_FALLBACK_COUNT.labels(
                    stage=str(agent_metadata.get("fallback_stage", "unknown")),
                    reason=str(agent_metadata.get("fallback_reason", "unknown")),
                ).inc()
                await self.observability.track_event(
                    event_type="fallback_used",
                    brand_slug=self.brand_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    payload={
                        "stage": str(agent_metadata.get("fallback_stage", "unknown")),
                        "reason": str(agent_metadata.get("fallback_reason", "unknown")),
                        "mode": "sync",
                    },
                )
            confidence_score = min(
                1.0,
                max(0.0, float(agent_metadata.get("validation_confidence", 1.0))),
            )
            await self.observability.track_event(
                event_type="message_processed",
                brand_slug=self.brand_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
                payload={
                    "mode": "sync",
                    "status": status_label,
                    "latency_ms": duration_ms,
                    "confidence_score": confidence_score,
                    "validation_passed": agent_metadata.get("validation_passed"),
                    "validation_issues": agent_metadata.get("validation_issues", []),
                    "context_used": len(tool_results),
                    "citations_count": len(citations),
                    "grounded": bool(citations or tool_results),
                    "low_confidence_prevented": (
                        agent_metadata.get("guardrail_action") == "fallback"
                        and agent_metadata.get("guardrail_reason") == "low_confidence"
                    ),
                    "fallback_stage": agent_metadata.get("fallback_stage"),
                    "fallback_reason": agent_metadata.get("fallback_reason"),
                    "guardrail_action": agent_metadata.get("guardrail_action"),
                    "guardrail_reason": agent_metadata.get("guardrail_reason"),
                    "capability_scope": agent_metadata.get("capability_scope"),
                    "prompt_version": self.prompt_metadata.get("prompt_version"),
                    "prompt_hash": self.prompt_metadata.get("cacheable_prefix_hash"),
                    "prompt_layers": self.prompt_metadata.get("layers", []),
                },
            )
            MESSAGE_COUNT.labels(status=status_label).inc()
            MESSAGE_DURATION.labels(mode="sync", status=status_label).observe(duration_ms / 1000)
                
            # Return response
            return MessageResponse(
                message=response_text,
                conversation_id=conversation_id,
                citations=citations,
                context_used=len(tool_results),
                confidence_score=confidence_score,
                processing_time_ms=duration_ms,
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
            short_term_enabled = self._short_term_memory_enabled()
            long_term_enabled = self._long_term_memory_enabled()
            
            # Set user_id
            user_id = request.user_id or "anonymous"
            self._bind_request_page_context_to_retrieval(request)
            
            yield StreamingMessageResponse(
                type="context_start",
                content="Loading agent configuration, memory, and runtime capabilities...",
                conversation_id=conversation_id
            )

            escalations = []
            if self.memory_config.ENABLE_GRAPH_RULES and self.graph:
                escalations = await self.graph.check_escalation(request.message)

            guardrail_decision = self._evaluate_pre_response_guardrails(request.message, escalations)
            if guardrail_decision["action"] in {"block", "escalate"}:
                response_text = guardrail_decision["message"]
                if short_term_enabled:
                    await self.short_term.add_message(
                        conversation_id=conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=response_text,
                        metadata={
                            "user_id": user_id,
                            "guardrail_action": guardrail_decision["action"],
                            "guardrail_reason": guardrail_decision["reason"],
                            "capability_scope": guardrail_decision.get("capability_scope"),
                            "validation_passed": False,
                        },
                    )
                self.strapi.sync_conversation(
                    conversation_id=conversation_id,
                    user_message=request.message,
                    assistant_message=response_text,
                    brand_slug=self.brand_id,
                    agent_id=agent_id,
                )
                await self.observability.track_event(
                    event_type="guardrail_decision",
                    brand_slug=self.brand_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    payload={
                        "action": guardrail_decision["action"],
                        "reason": guardrail_decision["reason"],
                        "mode": "stream",
                        "status": f"guardrail_{guardrail_decision['action']}",
                        "capability_scope": guardrail_decision.get("capability_scope"),
                    },
                )
                MESSAGE_COUNT.labels(status=f"guardrail_{guardrail_decision['action']}").inc()
                yield StreamingMessageResponse(
                    type="content",
                    content=response_text,
                    conversation_id=conversation_id,
                )
                yield StreamingMessageResponse(
                    type="metadata",
                    content="",
                    conversation_id=conversation_id,
                    citations=[],
                    context_used=0,
                    confidence_score=1.0,
                )
                return

            runtime_message = guardrail_decision.get("safe_query") or request.message
            capability_scope = guardrail_decision.get("capability_scope")
            user_metadata = {
                "user_id": user_id,
                "page_context": request.page_context or {},
            }
            if capability_scope:
                user_metadata["capability_scope"] = capability_scope
                user_metadata["original_user_message"] = request.message

            if short_term_enabled:
                await self.short_term.add_message(
                    conversation_id=conversation_id,
                    role=MessageRole.USER,
                    content=runtime_message,
                    metadata=user_metadata,
                )
            
            # Phase 6: Use SOTA Orchestrator for Planning, Execution, and Critic loop
            yield StreamingMessageResponse(
                type="context_result",
                content="Runtime context loaded.",
                conversation_id=conversation_id,
                metadata={
                    "capabilities": self.prompt_metadata.get("capabilities", {}),
                    "page_context": (
                        request.page_context.model_dump()
                        if hasattr(request.page_context, "model_dump")
                        else request.page_context or {}
                    ),
                    "api_data_source": {
                        "enabled": bool((self.agent_config or {}).get("api_data_source", {}).get("enabled")),
                        "name": (self.agent_config or {}).get("api_data_source", {}).get("name"),
                    },
                    "memory": self._memory_runtime_metadata(),
                },
            )
            
            # Retrieve recent history for context (last 6 messages)
            recent_messages = []
            if short_term_enabled:
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

            prompt_context = {
                "session_state": session_state,
                "prompt_runtime": self._build_prompt_runtime_context(request),
                "prompt_metadata": self.prompt_metadata,
                "capability_scope": capability_scope,
            }
            
            from agent_runtime.orchestrator_shopify import ShopifyOrchestrator
            
            if isinstance(self.orchestrator, ShopifyOrchestrator):
                # Define a queue to capture status updates from the orchestrator
                status_queue = asyncio.Queue()
                
                async def on_status(text: str):
                    await status_queue.put(text)

                run_params = inspect.signature(self.orchestrator.run).parameters
                run_kwargs = {
                    "query": runtime_message,
                    "context": prompt_context,
                }
                if "chat_history" in run_params:
                    run_kwargs["chat_history"] = chat_history
                if "on_status" in run_params:
                    run_kwargs["on_status"] = on_status

                # Run the orchestrator in a background task.
                orchestrator_task = asyncio.create_task(self.orchestrator.run(**run_kwargs))

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
                event_queue = asyncio.Queue()

                async def on_event(event: dict):
                    await event_queue.put(event)

                run_params = inspect.signature(self.orchestrator.run).parameters
                run_kwargs = {
                    "query": runtime_message,
                    "context": prompt_context,
                }
                if "chat_history" in run_params:
                    run_kwargs["chat_history"] = chat_history
                if "on_event" in run_params:
                    run_kwargs["on_event"] = on_event

                orchestrator_task = asyncio.create_task(self.orchestrator.run(**run_kwargs))

                while not orchestrator_task.done() or not event_queue.empty():
                    if not event_queue.empty():
                        event = event_queue.get_nowait()
                        yield StreamingMessageResponse(
                            type=event.get("type") or "status",
                            content=event.get("content") or "",
                            conversation_id=conversation_id,
                            metadata={key: value for key, value in event.items() if key not in {"type", "content"}},
                        )
                    else:
                        await asyncio.sleep(0.1)

                agent_result = await orchestrator_task
            
            # Extract final answer
            full_response, agent_metadata = self._apply_post_response_guardrails(
                agent_result.answer,
                agent_result.metadata,
            )
            if capability_scope:
                full_response = self._prefix_scope_notice(full_response, guardrail_decision)
                agent_metadata = {
                    **agent_metadata,
                    "capability_scope": capability_scope,
                    "guardrail_action": agent_metadata.get("guardrail_action") or guardrail_decision["action"],
                    "guardrail_reason": agent_metadata.get("guardrail_reason") or guardrail_decision["reason"],
                }
            
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
            for _, tool_result in agent_metadata.get("tool_results", {}).items():
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
                newly_found=any("cart" in str(tr.metadata) for tr in agent_metadata.get("tool_results", {}).values() if hasattr(tr, 'metadata') and tr.metadata)
            )

            if short_term_enabled:
                await self.short_term.add_message(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=full_response,
                    metadata={
                        "user_id": user_id,
                        "agent_steps": agent_metadata.get("steps_executed", 0),
                        "validation_passed": agent_metadata.get("validation_passed"),
                        "validation_issues": agent_metadata.get("validation_issues", []),
                        "guardrail_action": agent_metadata.get("guardrail_action"),
                        "guardrail_reason": agent_metadata.get("guardrail_reason"),
                        "fallback_stage": agent_metadata.get("fallback_stage"),
                        "fallback_reason": agent_metadata.get("fallback_reason"),
                        "prompt_version": self.prompt_metadata.get("prompt_version"),
                        "prompt_hash": self.prompt_metadata.get("cacheable_prefix_hash"),
                        "prompt_layers": self.prompt_metadata.get("layers", []),
                        "capability_scope": agent_metadata.get("capability_scope"),
                        "plan": agent_metadata.get("plan"),
                        "cart_id": saved_cart_id,
                        "checkout_url": agent_metadata.get("checkout_url"),
                        "cart_lines": agent_metadata.get("cart_lines"),
                        "captured_ids": agent_metadata.get("captured_ids"),
                        "last_searched": agent_metadata.get("last_searched"),
                    }
                )

            
            # Sync to Strapi dashboard (fire-and-forget — never blocks streaming)
            self.strapi.sync_conversation(
                conversation_id=conversation_id,
                user_message=request.message,
                assistant_message=full_response,
                brand_slug=self.brand_id,
                agent_id=agent_id,
            )

            # Extract episodic facts
            if short_term_enabled and long_term_enabled and self.memory_config.ENABLE_FACT_EXTRACTION:
                messages = await self.short_term.get_recent_messages(conversation_id, limit=10)
                facts = await self.episodic.extract_and_store_facts(
                    user_id=user_id,
                    messages=messages,
                    conversation_id=conversation_id
                )
            
            # Check auto-summary
            if short_term_enabled and self.memory_config.ENABLE_AUTO_SUMMARY:
                if await self.short_term.should_summarize(conversation_id):
                    await self.short_term.trigger_summary(conversation_id)
            
            # Send final metadata (orchestrator handles retrieval internally)
            tool_results = agent_metadata.get("tool_results", {})
            citations, safe_products, safe_dealers = _extract_tool_result_metadata(tool_results)

            unique_products = _deduplicate_entities(
                safe_products,
                "id",
                "sku",
                "product_id",
                "variant_id",
                "name",
            )
            unique_dealers = _deduplicate_entities(
                safe_dealers,
                "id",
                "dealer_id",
                "email",
                "phone",
                "name",
            )

            yield StreamingMessageResponse(
                type="metadata",
                content="",
                conversation_id=conversation_id,
                citations=citations,
                context_used=len(tool_results),
                confidence_score=min(1.0, max(0.0, float(agent_metadata.get("validation_confidence", 1.0)))),
                products=unique_products,
                dealers=unique_dealers
            )

            yield StreamingMessageResponse(
                type="done",
                content="Run complete.",
                conversation_id=conversation_id,
                metadata={
                    "latency_ms": int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                    "context_used": len(tool_results),
                    "citations_count": len(citations),
                },
            )
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            status_label = "fallback" if agent_metadata.get("fallback") else "success"
            if agent_metadata.get("guardrail_action") == "fallback":
                status_label = "guardrail_fallback"
            if agent_metadata.get("fallback"):
                AGENT_FALLBACK_COUNT.labels(
                    stage=str(agent_metadata.get("fallback_stage", "unknown")),
                    reason=str(agent_metadata.get("fallback_reason", "unknown")),
                ).inc()
                await self.observability.track_event(
                    event_type="fallback_used",
                    brand_slug=self.brand_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    payload={
                        "stage": str(agent_metadata.get("fallback_stage", "unknown")),
                        "reason": str(agent_metadata.get("fallback_reason", "unknown")),
                        "mode": "stream",
                    },
                )
            confidence_score = min(1.0, max(0.0, float(agent_metadata.get("validation_confidence", 1.0))))
            await self.observability.track_event(
                event_type="message_processed",
                brand_slug=self.brand_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
                payload={
                    "mode": "stream",
                    "status": status_label,
                    "latency_ms": int(duration * 1000),
                    "confidence_score": confidence_score,
                    "validation_passed": agent_metadata.get("validation_passed"),
                    "validation_issues": agent_metadata.get("validation_issues", []),
                    "context_used": len(tool_results),
                    "citations_count": len(citations),
                    "grounded": bool(citations or tool_results),
                    "low_confidence_prevented": (
                        agent_metadata.get("guardrail_action") == "fallback"
                        and agent_metadata.get("guardrail_reason") == "low_confidence"
                    ),
                    "fallback_stage": agent_metadata.get("fallback_stage"),
                    "fallback_reason": agent_metadata.get("fallback_reason"),
                    "guardrail_action": agent_metadata.get("guardrail_action"),
                    "guardrail_reason": agent_metadata.get("guardrail_reason"),
                    "prompt_version": self.prompt_metadata.get("prompt_version"),
                    "prompt_hash": self.prompt_metadata.get("cacheable_prefix_hash"),
                    "prompt_layers": self.prompt_metadata.get("layers", []),
                },
            )
            MESSAGE_COUNT.labels(status=status_label).inc()
            MESSAGE_DURATION.labels(mode="stream", status=status_label).observe(duration)
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
            if not self._short_term_memory_enabled():
                logger.info("takeover_history_injection_skipped_memory_disabled", agent_id=agent_id)
                return

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
                max_chunks=self._agent_max_chunks()
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
        short_term_enabled = self._short_term_memory_enabled()
        long_term_enabled = self._long_term_memory_enabled()

        # Get short-term messages
        recent_messages = []
        if short_term_enabled:
            recent_messages = await self.short_term.get_recent_messages(
                conversation_id, limit=10
            )
        
        # Get user facts from episodic memory
        user_facts = []
        if long_term_enabled and self.memory_config.ENABLE_FACT_EXTRACTION:
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
        if short_term_enabled:
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
