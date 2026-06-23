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
from tools.types import ToolResult
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
from .lalkitab_runtime import build_lalkitab_runtime_context
from .tool_registry import ToolRegistryService

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

    def _context_connector_runtime_metadata(self) -> list[dict]:
        connectors = (self.agent_config or {}).get("context_connectors") or []
        if not isinstance(connectors, list):
            connectors = []
        summaries: list[dict] = []
        for connector in connectors:
            if not isinstance(connector, dict):
                continue
            endpoints = [
                {
                    "id": endpoint.get("id"),
                    "name": endpoint.get("name"),
                    "enabled": bool(endpoint.get("enabled", True)) and not bool(endpoint.get("revoked")),
                    "method": endpoint.get("method") or "POST",
                    "required_user_fields": endpoint.get("required_user_fields")
                    or endpoint.get("required_fields")
                    or [],
                    "runtime_required_fields": endpoint.get("runtime_required_fields") or [],
                    "execution_order": endpoint.get("execution_order"),
                    "requires_prior_endpoint": endpoint.get("requires_prior_endpoint"),
                    "payload_mode": endpoint.get("payload_mode"),
                }
                for endpoint in (connector.get("endpoints") or [])
                if isinstance(endpoint, dict)
            ]
            summaries.append(
                {
                    "id": connector.get("id"),
                    "name": connector.get("name"),
                    "type": connector.get("type"),
                    "enabled": bool(connector.get("enabled")) and not bool(connector.get("revoked")),
                    "endpoint_count": len(endpoints),
                    "endpoints": endpoints,
                }
            )
        return summaries

    def _connector_missing_inputs_for_message(self, message: str) -> list[dict]:
        """Best-effort preflight for connector endpoints with required user fields."""
        config = self.agent_config or {}
        connectors = config.get("context_connectors") or []
        if not isinstance(connectors, list):
            return []

        message_text = (message or "").lower()
        connector_intent_terms = {
            "chart",
            "birth",
            "kundli",
            "horoscope",
            "prediction",
            "predictions",
            "remedy",
            "remedies",
            "totke",
            "varshphal",
            "lucky",
            "house",
            "houses",
            "debt",
            "debts",
            "api",
            "calculate",
        }
        if not any(term in message_text for term in connector_intent_terms):
            return []

        field_patterns = {
            "birth_date": [r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", r"\b\d{4}-\d{1,2}-\d{1,2}\b", r"\bbirth\s*date\b"],
            "date_of_birth": [r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", r"\b\d{4}-\d{1,2}-\d{1,2}\b", r"\bdate\s*of\s*birth\b"],
            "dob": [r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", r"\b\d{4}-\d{1,2}-\d{1,2}\b", r"\bdob\b"],
            "birth_time": [r"\b\d{1,2}:\d{2}\b", r"\b\d{1,2}\s*(am|pm)\b", r"\bbirth\s*time\b"],
            "time_of_birth": [r"\b\d{1,2}:\d{2}\b", r"\b\d{1,2}\s*(am|pm)\b", r"\btime\s*of\s*birth\b"],
            "birth_place": [r"\bbirth\s*place\b", r"\bborn\s+in\s+[a-z]", r"\bplace\s*of\s*birth\b"],
            "place_of_birth": [r"\bbirth\s*place\b", r"\bborn\s+in\s+[a-z]", r"\bplace\s*of\s*birth\b"],
        }

        missing_groups: list[dict] = []
        for connector in connectors:
            if not isinstance(connector, dict) or not connector.get("enabled") or connector.get("revoked"):
                continue
            for endpoint in connector.get("endpoints") or []:
                if not isinstance(endpoint, dict) or not endpoint.get("enabled", True) or endpoint.get("revoked"):
                    continue
                required_fields = [
                    str(field)
                    for field in (endpoint.get("required_user_fields") or endpoint.get("required_fields") or [])
                    if field
                ]
                if not required_fields:
                    continue
                missing = []
                for field in required_fields:
                    patterns = field_patterns.get(field.lower())
                    if patterns and any(re.search(pattern, message_text, re.IGNORECASE) for pattern in patterns):
                        continue
                    if field.lower() not in field_patterns and field.lower() in message_text:
                        continue
                    missing.append(field)
                if missing:
                    missing_groups.append(
                        {
                            "connector_id": connector.get("id"),
                            "connector_name": connector.get("name"),
                            "endpoint_id": endpoint.get("id"),
                            "endpoint_name": endpoint.get("name"),
                            "missing_input": missing,
                        }
                    )
        return missing_groups

    async def _load_lalkitab_pending_state(self, conversation_id: str) -> dict:
        """Resume Lal Kitab context across turns: merges any in-flight pending
        flow (missing input / disambiguation) with the birth details remembered
        from an earlier successful reading, so follow-ups never re-ask."""
        if not self.short_term:
            return {}
        try:
            recent = await self.short_term.get_recent_messages(conversation_id=conversation_id, limit=8)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("lalkitab_pending_state_load_failed", error=str(exc))
            return {}
        pending: dict = {}
        remembered: dict = {}
        for msg in reversed(recent):
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role != "assistant":
                continue
            meta = msg.metadata or {}
            if not pending and isinstance(meta.get("lalkitab_pending"), dict) and meta["lalkitab_pending"]:
                pending = dict(meta["lalkitab_pending"])
            if not remembered and isinstance(meta.get("connector_inputs"), dict) and meta["connector_inputs"]:
                remembered = dict(meta["connector_inputs"])
            if pending and remembered:
                break
        if not pending and not remembered:
            return {}
        normalized: dict = {}
        normalized.update(remembered)
        normalized.update(pending.get("normalized_birth_input") or {})
        result: dict = {"normalized_birth_input": normalized}
        if pending.get("awaiting_place_choice"):
            result["awaiting_place_choice"] = True
            result["place_candidates"] = pending.get("place_candidates") or []
        return result

    def _apply_remembered_connector_inputs(self, remembered_inputs: dict) -> None:
        """Push conversation-remembered inputs onto registered connector tools so
        follow-up tool calls auto-fill required fields (universal: any connector)."""
        registry = getattr(self, "tool_registry", None)
        if not remembered_inputs or registry is None:
            return
        cleaned = {k: v for k, v in remembered_inputs.items() if v not in (None, "")}
        try:
            tools = registry.list_tools()
        except Exception:  # pragma: no cover - defensive
            return
        for tool in tools:
            existing = getattr(tool, "remembered_inputs", None)
            if isinstance(existing, dict):
                tool.remembered_inputs = {**existing, **cleaned}

    def _collect_connector_inputs(self, session_state: dict, lalkitab_plan, agent_metadata: dict) -> dict:
        """Accumulate resolved connector inputs for this turn so later turns can
        reuse them (birth details, location, account id, …)."""
        inputs: dict = dict(session_state.get("connector_inputs") or {})
        if getattr(lalkitab_plan, "handled", False):
            for key, value in (getattr(lalkitab_plan, "normalized_birth_input", None) or {}).items():
                if value not in (None, ""):
                    inputs[key] = value
        for tool_result in (agent_metadata.get("tool_results") or {}).values():
            meta = getattr(tool_result, "metadata", None) or {}
            resolved = meta.get("resolved_inputs")
            if isinstance(resolved, dict):
                for key, value in resolved.items():
                    if value not in (None, ""):
                        inputs[key] = value
        return inputs

    def _memory_short_term_settings(self) -> dict:
        mem = (self.agent_config or {}).get("memory") if isinstance((self.agent_config or {}).get("memory"), dict) else {}
        st = mem.get("short_term") if isinstance(mem.get("short_term"), dict) else {}
        return st

    def _context_window_messages(self) -> int:
        try:
            return max(2, int(self._memory_short_term_settings().get("window_messages") or 12))
        except (TypeError, ValueError):
            return 12

    def _auto_compaction_enabled(self) -> bool:
        # Default on whenever short-term memory is enabled.
        return self._short_term_memory_enabled() and self._memory_short_term_settings().get("auto_compaction", True) is not False

    def _compaction_threshold(self) -> int:
        floor = self._context_window_messages() + 4
        try:
            return max(floor, int(self._memory_short_term_settings().get("compaction_threshold") or 20))
        except (TypeError, ValueError):
            return max(floor, 20)

    async def _summarize_conversation_segment(self, messages: list, prior_summary: str) -> str:
        """Fold a batch of older messages into the rolling conversation memory,
        preserving concrete facts verbatim (universal for any agent)."""
        if not self.llm_provider or not messages:
            return prior_summary or ""
        transcript = "\n".join(
            f"{(m.role.value if hasattr(m.role, 'value') else m.role)}: {m.content}" for m in messages
        )[:8000]
        prompt = f"""You maintain a running memory of a chat conversation so the assistant never loses context across a long conversation.

Update the memory below. Rules:
- Preserve concrete facts VERBATIM: names, dates, times, places, IDs, numbers, birth details, decisions, stated preferences.
- Keep a short "Open threads:" list of unresolved questions or things the user is still waiting on.
- Be concise but lossless on facts. No preamble, just the updated memory.

Existing memory:
{prior_summary or '(none yet)'}

New conversation turns to fold in:
{transcript}

Updated memory:"""
        try:
            response = await self.llm_provider.generate(prompt, max_tokens=1200)
            return (response.content or prior_summary or "").strip()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("conversation_summary_failed", error=str(exc))
            return prior_summary or ""

    async def _build_conversation_context(self, conversation_id: str) -> dict:
        """Return {summary, recent}: a rolling summary of older turns plus the
        most-recent window of messages. Universal across all agents."""
        window = self._context_window_messages()
        if not self.short_term:
            return {"summary": "", "recent": []}
        try:
            recent = await self.short_term.get_recent_messages(conversation_id=conversation_id, limit=window)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("conversation_context_failed", error=str(exc))
            recent = []
        if not isinstance(recent, list):
            recent = []

        summary_text = ""
        try:
            total = await self.short_term.get_message_count(conversation_id) if self._auto_compaction_enabled() else 0
            if isinstance(total, int) and total > self._compaction_threshold():
                older_count = max(0, total - window)
                last = await self.short_term.get_latest_summary(conversation_id)
                last_covered = last.turn_count if last else 0
                summary_text = last.summary if last else ""
                # Fold newly aged-out messages into the rolling summary (throttled).
                if isinstance(last_covered, int) and older_count - last_covered >= 4:
                    older = await self.short_term.get_earliest_messages(conversation_id, older_count)
                    segment = older[last_covered:older_count] if isinstance(older, list) else []
                    if segment:
                        summary_text = await self._summarize_conversation_segment(segment, summary_text)
                        await self.short_term.save_summary(
                            conversation_id, summary_text, older_count,
                            segment[0].timestamp, segment[-1].timestamp,
                        )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("conversation_compaction_failed", error=str(exc))
        return {"summary": summary_text, "recent": recent}

    async def _retrieve_lalkitab_rag_context(self, message: str, request: MessageRequest) -> tuple[dict, ToolResult | None]:
        """Retrieve RAG context for Lal Kitab synthesis without persisting API data."""
        if not self.retrieval_pipeline or not self._rag_enabled():
            return {}, None
        try:
            page_context = (
                request.page_context.model_dump()
                if hasattr(request.page_context, "model_dump")
                else request.page_context or {}
            )
            context = await self.retrieval_pipeline.retrieve(
                query=message,
                page_context=page_context,
                filters={},
                max_chunks=5,
            )
            chunks = []
            for chunk in (context.chunks or [])[:5]:
                chunks.append(
                    {
                        "doc_id": getattr(chunk, "doc_id", None),
                        "source": getattr(chunk, "source", None),
                        "content": (getattr(chunk, "text", "") or getattr(chunk, "content", ""))[:1200],
                        "score": getattr(chunk, "score", None),
                    }
                )
            data = "Knowledge/RAG Context:\n" + "\n\n".join(
                f"[{index + 1}] {chunk.get('doc_id')}\n{chunk.get('content')}"
                for index, chunk in enumerate(chunks)
            )
            rag_context = {
                "chunks": chunks,
                "sources": context.sources,
                "confidence": context.confidence,
            }
            return rag_context, ToolResult(
                success=True,
                data=data,
                metadata={
                    "tool_id": "knowledge_search",
                    "sources": context.sources,
                    "chunks_count": len(chunks),
                    "confidence": context.confidence,
                    "rag_chunks": chunks,
                },
            )
        except Exception as exc:
            logger.warning("lalkitab_rag_context_failed", error=str(exc))
            return {}, ToolResult(
                success=False,
                data=None,
                error=str(exc),
                metadata={"tool_id": "knowledge_search", "sources": [], "chunks_count": 0},
            )

    async def _generate_lalkitab_agent_result(
        self,
        *,
        message: str,
        chat_history: list[dict],
        lalkitab_plan,
        rag_context: dict,
        rag_tool_result: ToolResult | None,
    ) -> AgentResult:
        """Generate a Lal Kitab answer grounded in chart-first API context plus RAG."""
        api_context = lalkitab_plan.api_context or {}
        input_resolution = api_context.get("input_resolution") if isinstance(api_context.get("input_resolution"), dict) else {}
        confirmation_rule = (
            "- Start by briefly confirming the birth details you used. If a detail was inferred from a known place, say so naturally."
            if input_resolution.get("confirm_understood_details", True) is not False
            else "- Do not add a separate birth-detail confirmation unless the user asks."
        )
        prompt = f"""
{self.system_prompt}

You are answering a Lal Kitab / Vedic Jyotish question for the user.

Rules:
- Use "Calculated API Context" as the source for chart/calculation facts.
- Use "Knowledge/RAG Context" for interpretation policy, tone, explanations, FAQs, and Lal Kitab reference context.
{confirmation_rule}
- Never invent chart placements, debts, remedies, predictions, totke, lucky factors, houses, or varshphal data.
- If the API context is incomplete or an endpoint failed, say which calculated context was unavailable.
- Distinguish calculated facts from interpretation in clear language.
- Do not claim certainty beyond the provided sources.

User Query:
{message}

Conversation (rolling memory + recent turns):
{json.dumps(chat_history, default=str, indent=2)}

Calculated API Context:
{json.dumps(_sanitize_for_json(api_context), default=str, indent=2)}

Knowledge/RAG Context:
{json.dumps(_sanitize_for_json(rag_context), default=str, indent=2)}

Answer the user directly and cite what context you used in natural language.
"""
        response = await self.llm_provider.generate(prompt)
        tool_results = dict(lalkitab_plan.tool_results or {})
        if rag_tool_result:
            tool_results["knowledge_search"] = rag_tool_result
        return AgentResult(
            answer=response.content,
            metadata={
                "tool_results": tool_results,
                "steps_executed": len(tool_results),
                "validation_passed": True,
                "validation_confidence": 0.92,
                "lalkitab_runtime": True,
                "api_context": {
                    "normalized_birth_input": api_context.get("normalized_birth_input"),
                    "chart_available": bool(api_context.get("chart_context")),
                    "secondary_endpoint_ids": sorted((api_context.get("secondary_endpoint_results") or {}).keys()),
                    "source_provenance": api_context.get("source_provenance") or [],
                },
                "selected_connector_endpoint_ids": lalkitab_plan.selected_endpoint_ids,
                "rag_context": {
                    "chunks_count": len(rag_context.get("chunks") or []),
                    "sources": rag_context.get("sources") or [],
                    "confidence": rag_context.get("confidence"),
                },
            },
        )

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

        if config.get("data_source") != "shopify":
            for connector_tool in self.external_tool_registry.enabled_context_connector_tools(config):
                self.tool_registry.register(connector_tool)
                registered_tools.append(connector_tool.name)

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

                # Initialize remote MCP tools only when live Shopify actions are enabled.
                # Catalog-backed ecommerce answers can run without MCP/customer auth.
                if config.get("data_source") == "shopify":
                    from tools.mcp_client import McpClient
                    from agent_runtime.orchestrator_shopify import ShopifyOrchestrator

                    # For local development we assume port 3005 for the Shopify MCP Service
                    # In production this would be loaded from settings
                    mcp_endpoint = self.settings.SHOPIFY_MCP_URL if hasattr(self.settings, 'SHOPIFY_MCP_URL') else "http://localhost:3005/mcp"

                    # Extract per-agent Shopify credentials from dashboard-managed config.
                    # Store identity and tokens must not fall back to global env values in production.
                    shopify_conf = config.get("shopify", {})
                    shopify_mcp_enabled = bool(shopify_conf.get("mcp_enabled"))
                    shopify_url = (
                        shopify_conf.get("shop_url") or
                        config.get("shopify_shop_url")
                    )
                    shopify_client_id = shopify_conf.get("client_id") or config.get("shopify_client_id")
                    shopify_client_secret = (
                        shopify_conf.get("client_secret") or
                        config.get("shopify_client_secret")
                    )

                    if not shopify_url:
                        logger.warning(
                            "shopify_credentials_missing",
                            agent_id=agent_id,
                            has_shop_url=bool(shopify_url),
                        )

                    if shopify_mcp_enabled and shopify_url:
                        mcp_headers = {
                            "x-shopify-shop-url": str(shopify_url or ""),
                            "x-session-id": f"agent:{agent_id}",
                        }
                        if shopify_client_id:
                            mcp_headers["x-shopify-client-id"] = str(shopify_client_id)
                        if shopify_client_secret:
                            mcp_headers["x-shopify-client-secret"] = str(shopify_client_secret)
                        if shopify_conf.get("agent_profile_url"):
                            mcp_headers["x-shopify-ucp-agent-profile"] = str(shopify_conf.get("agent_profile_url"))

                        # Also try to get a customer access token from config or settings
                        customer_token = (
                            shopify_conf.get("customer_access_token") or
                            config.get("shopify_customer_access_token")
                        )

                        if customer_token:
                            mcp_headers["x-customer-access-token"] = str(customer_token)

                        mcp_client = McpClient(endpoint=mcp_endpoint, headers=mcp_headers)

                        # Connect and discover remote tools using a stable agent session.
                        remote_tools = await mcp_client.discover_tools(session_id=f"agent:{agent_id}")
                        for tool in remote_tools:
                            self.tool_registry.register(tool)

                        logger.info("mcp_tools_registered", count=len(remote_tools), brand_id=self.brand_id)

                        # Swap to ShopifyOrchestrator for live Shopify MCP actions.
                        self.orchestrator = ShopifyOrchestrator(
                            llm=self.llm_provider,
                            tools=self.tool_registry,
                            critic=self.response_validator,
                            system_prompt=self.system_prompt
                        )
                        logger.info("switched_to_shopify_orchestrator", agent_id=agent_id)
                    else:
                        logger.info(
                            "shopify_mcp_skipped",
                            agent_id=agent_id,
                            mcp_enabled=shopify_mcp_enabled,
                            has_shop_url=bool(shopify_url),
                            has_client_id=bool(shopify_client_id),
                        )
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

            # Retrieve recent history + rolling memory (auto-compaction).
            recent_messages = []
            conversation_summary = ""
            if short_term_enabled:
                conv_ctx = await self._build_conversation_context(conversation_id)
                recent_messages = conv_ctx["recent"]
                conversation_summary = conv_ctx["summary"]

            # Build chat history AND extract session state (e.g. cart_id) from
            # previous assistant message metadata so the agent can reuse the cart.
            chat_history = []
            session_state: dict = {}
            if conversation_summary:
                # Lead with the rolling memory so older context survives compaction.
                chat_history.append({
                    "role": "system",
                    "content": f"Conversation memory so far (earlier turns):\n{conversation_summary}",
                    "metadata": {"memory_summary": True},
                })
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
                    for key in (
                        "active_product_focus",
                        "product_reference_map",
                        "last_user_query",
                        "last_search_query",
                        "last_constraints",
                        "rerank_results",
                    ):
                        if key in meta:
                            session_state[key] = meta.get(key)

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
                        "active_product_focus": agent_metadata.get("active_product_focus"),
                        "product_reference_map": agent_metadata.get("product_reference_map"),
                        "last_user_query": agent_metadata.get("last_user_query"),
                        "last_search_query": agent_metadata.get("last_search_query"),
                        "last_constraints": agent_metadata.get("last_constraints"),
                        "rerank_results": agent_metadata.get("rerank_results"),
                        "resolved_reference": agent_metadata.get("resolved_reference"),
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
                    "context_connectors": self._context_connector_runtime_metadata(),
                    "memory": self._memory_runtime_metadata(),
                },
            )

            lalkitab_pending = (
                await self._load_lalkitab_pending_state(conversation_id)
                if short_term_enabled else {}
            )
            lalkitab_plan = await build_lalkitab_runtime_context(
                self.agent_config or {}, runtime_message, pending_state=lalkitab_pending
            )

            # Surface real runtime activity (geocoding, connector calls) as it happens.
            if lalkitab_plan.handled:
                for event in lalkitab_plan.events:
                    yield StreamingMessageResponse(
                        type=event.get("type") or "status",
                        content=event.get("content") or "",
                        conversation_id=conversation_id,
                        metadata=event.get("metadata") or {},
                    )

            # Birthplace disambiguation: pause and ask the user to pick a place.
            if lalkitab_plan.handled and lalkitab_plan.awaiting_place_choice:
                disambiguation_metadata = {
                    "connector_id": "vedika_lal_kitab",
                    "connector_name": "Vedika Lal Kitab",
                    "endpoint_id": "geocode_search",
                    "endpoint_name": "Vedika Geocode Search",
                    "candidates": lalkitab_plan.place_candidates,
                    "normalized_birth_input": lalkitab_plan.normalized_birth_input,
                }
                yield StreamingMessageResponse(
                    type="place_disambiguation",
                    content=lalkitab_plan.clarification,
                    conversation_id=conversation_id,
                    metadata=disambiguation_metadata,
                )
                yield StreamingMessageResponse(type="content", content=lalkitab_plan.clarification, conversation_id=conversation_id)
                if short_term_enabled:
                    await self.short_term.add_message(
                        conversation_id=conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=lalkitab_plan.clarification,
                        metadata={"user_id": user_id, "lalkitab_pending": lalkitab_plan.pending_state},
                    )
                yield StreamingMessageResponse(
                    type="done",
                    content="Awaiting birthplace selection.",
                    conversation_id=conversation_id,
                    metadata={"awaiting_place_choice": True},
                )
                return

            if lalkitab_plan.handled and lalkitab_plan.missing_input:
                missing_metadata = {
                    "connector_id": "vedika_lal_kitab",
                    "connector_name": "Vedika Lal Kitab",
                    "endpoint_id": "lalkitab_chart",
                    "endpoint_name": "Lal Kitab Chart",
                    "missing_input": lalkitab_plan.missing_input,
                    "normalized_birth_input": lalkitab_plan.normalized_birth_input,
                }
                yield StreamingMessageResponse(
                    type="missing_input",
                    content=lalkitab_plan.clarification,
                    conversation_id=conversation_id,
                    metadata=missing_metadata,
                )
                yield StreamingMessageResponse(type="content", content=lalkitab_plan.clarification, conversation_id=conversation_id)
                if short_term_enabled:
                    await self.short_term.add_message(
                        conversation_id=conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=lalkitab_plan.clarification,
                        metadata={"user_id": user_id, "lalkitab_pending": lalkitab_plan.pending_state},
                    )
                yield StreamingMessageResponse(
                    type="done",
                    content="Missing Lal Kitab input required.",
                    conversation_id=conversation_id,
                    metadata={"missing_input": missing_metadata},
                )
                return

            connector_preflight = [] if lalkitab_plan.handled else self._connector_missing_inputs_for_message(runtime_message)
            if connector_preflight:
                first_missing = connector_preflight[0]
                yield StreamingMessageResponse(
                    type="missing_input",
                    content=(
                        f"{first_missing.get('endpoint_name') or 'Connector'} needs: "
                        f"{', '.join(first_missing.get('missing_input') or [])}."
                    ),
                    conversation_id=conversation_id,
                    metadata=first_missing,
                )
                clarification = (
                    "I need a little more information before I can call the configured source: "
                    f"{', '.join(first_missing.get('missing_input') or [])}."
                )
                yield StreamingMessageResponse(type="content", content=clarification, conversation_id=conversation_id)
                yield StreamingMessageResponse(
                    type="done",
                    content="Missing input required.",
                    conversation_id=conversation_id,
                    metadata={"missing_input": first_missing},
                )
                return

            if not lalkitab_plan.handled and ((self.agent_config or {}).get("rag", {}).get("enabled") or (self.agent_config or {}).get("data_source") == "rag"):
                yield StreamingMessageResponse(
                    type="rag_context",
                    content="Knowledge retrieval is enabled for this run.",
                    conversation_id=conversation_id,
                    metadata={
                        "rag": (self.agent_config or {}).get("rag") or {},
                        "context_connectors": self._context_connector_runtime_metadata(),
                    },
                )

            # Retrieve recent history + rolling memory (auto-compaction).
            recent_messages = []
            conversation_summary = ""
            if short_term_enabled:
                conv_ctx = await self._build_conversation_context(conversation_id)
                recent_messages = conv_ctx["recent"]
                conversation_summary = conv_ctx["summary"]

            # Build chat history AND extract session state (e.g. cart_id) from
            # previous assistant message metadata so the agent can reuse the cart.
            chat_history = []
            session_state: dict = {}
            if conversation_summary:
                # Lead with the rolling memory so older context survives compaction.
                chat_history.append({
                    "role": "system",
                    "content": f"Conversation memory so far (earlier turns):\n{conversation_summary}",
                    "metadata": {"memory_summary": True},
                })
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
                    # Remembered connector inputs (birthplace, location, account
                    # id, …) so follow-up tool calls reuse them automatically.
                    if isinstance(meta.get("connector_inputs"), dict) and meta["connector_inputs"]:
                        session_state["connector_inputs"] = {**session_state.get("connector_inputs", {}), **meta["connector_inputs"]}

            # Make remembered inputs available to any connector tool the
            # orchestrator may call this turn (universal for connector agents).
            remembered_inputs = session_state.get("connector_inputs") or {}
            if remembered_inputs:
                self._apply_remembered_connector_inputs(remembered_inputs)

            prompt_context = {
                "session_state": session_state,
                "prompt_runtime": self._build_prompt_runtime_context(request),
                "prompt_metadata": self.prompt_metadata,
                "capability_scope": capability_scope,
            }
            if lalkitab_plan.handled and lalkitab_plan.api_context:
                prompt_context["prompt_runtime"]["calculated_api_context"] = {
                    "normalized_birth_input": lalkitab_plan.api_context.get("normalized_birth_input"),
                    "chart_available": bool(lalkitab_plan.api_context.get("chart_context")),
                    "secondary_endpoint_ids": sorted((lalkitab_plan.api_context.get("secondary_endpoint_results") or {}).keys()),
                    "source_provenance": lalkitab_plan.api_context.get("source_provenance") or [],
                }

            from agent_runtime.orchestrator_shopify import ShopifyOrchestrator

            if lalkitab_plan.handled:
                rag_context, rag_tool_result = await self._retrieve_lalkitab_rag_context(runtime_message, request)
                if rag_context:
                    yield StreamingMessageResponse(
                        type="rag_context",
                        content=f"Retrieved {len(rag_context.get('chunks') or [])} knowledge chunk(s) for Lal Kitab context.",
                        conversation_id=conversation_id,
                        metadata=rag_context,
                    )
                agent_result = await self._generate_lalkitab_agent_result(
                    message=runtime_message,
                    chat_history=chat_history,
                    lalkitab_plan=lalkitab_plan,
                    rag_context=rag_context,
                    rag_tool_result=rag_tool_result,
                )
            elif isinstance(self.orchestrator, ShopifyOrchestrator):
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

            tool_results = agent_metadata.get("tool_results", {})
            for tool_name, tool_result in tool_results.items():
                if not hasattr(tool_result, "metadata") or not tool_result.metadata:
                    continue
                tool_metadata = tool_result.metadata or {}
                connector_metadata = {
                    key: tool_metadata.get(key)
                    for key in (
                        "connector_id",
                        "connector_name",
                        "endpoint_id",
                        "endpoint_name",
                        "url",
                        "latency_ms",
                        "missing_input",
                        "request_shape",
                        "response_summary",
                        "blocked_reason",
                    )
                    if tool_metadata.get(key) is not None
                }
                if agent_metadata.get("lalkitab_runtime") and connector_metadata.get("connector_id"):
                    continue
                products = [_sanitize_for_json(product) for product in (tool_metadata.get("products") or [])]
                dealers = [_sanitize_for_json(dealer) for dealer in (tool_metadata.get("dealers") or [])]
                sources = tool_metadata.get("sources") or []
                summary_parts = []
                if products:
                    summary_parts.append(f"{len(products)} product result{'s' if len(products) != 1 else ''}")
                if dealers:
                    summary_parts.append(f"{len(dealers)} dealer result{'s' if len(dealers) != 1 else ''}")
                if sources:
                    summary_parts.append(f"{len(sources)} source{'s' if len(sources) != 1 else ''}")
                if tool_metadata.get("cart"):
                    summary_parts.append("cart context")
                if connector_metadata.get("connector_name"):
                    summary_parts.append(f"{connector_metadata.get('connector_name')} context")
                if connector_metadata.get("missing_input"):
                    yield StreamingMessageResponse(
                        type="missing_input",
                        content=(
                            f"{connector_metadata.get('endpoint_name') or tool_name} needs: "
                            f"{', '.join(connector_metadata.get('missing_input') or [])}."
                        ),
                        conversation_id=conversation_id,
                        metadata=connector_metadata,
                    )
                if connector_metadata.get("connector_id"):
                    event_type = "mcp_tool_start" if tool_metadata.get("tool_id") == "context_connector_mcp" else "connector_start"
                    yield StreamingMessageResponse(
                        type=event_type,
                        content=(
                            f"Calling {connector_metadata.get('connector_name') or 'connector'}"
                            f" · {connector_metadata.get('endpoint_name') or tool_name}."
                        ),
                        conversation_id=conversation_id,
                        metadata={
                            "tool_name": str(tool_name),
                            **connector_metadata,
                        },
                    )
                result_type = "tool_result"
                if connector_metadata.get("connector_id"):
                    result_type = "mcp_tool_result" if tool_metadata.get("tool_id") == "context_connector_mcp" else "connector_result"
                    if getattr(tool_result, "success", True) is False:
                        result_type = "connector_error"
                yield StreamingMessageResponse(
                    type=result_type,
                    content=(
                        f"{tool_name} returned {', '.join(summary_parts)}."
                        if summary_parts
                        else f"{tool_name} completed."
                    ),
                    conversation_id=conversation_id,
                    metadata={
                        "tool_name": str(tool_name),
                        "success": getattr(tool_result, "success", True),
                        "cart": _sanitize_for_json(tool_metadata.get("cart") or {}) if tool_metadata.get("cart") else None,
                        "orders_count": len(tool_metadata.get("orders") or []),
                        "commerce_intent": _sanitize_for_json(tool_metadata.get("commerce_intent") or {}) if tool_metadata.get("commerce_intent") else None,
                        "active_product_focus": _sanitize_for_json(tool_metadata.get("active_product_focus") or []) if tool_metadata.get("active_product_focus") else None,
                        "product_reference_map": _sanitize_for_json(tool_metadata.get("product_reference_map") or {}) if tool_metadata.get("product_reference_map") else None,
                        "original_query": tool_metadata.get("original_query"),
                        "search_query": tool_metadata.get("search_query"),
                        "rerank_results": _sanitize_for_json(tool_metadata.get("rerank_results") or []) if tool_metadata.get("rerank_results") else None,
                        **connector_metadata,
                    },
                    products=products,
                    dealers=dealers,
                )

            # Stream the result in small word batches for a smooth UI. The full
            # answer is already generated, so we flush it quickly: a per-word
            # artificial delay here only adds latency and — on long answers —
            # keeps the socket busy long enough to hit the client pong timeout
            # and drop the connection mid-stream (truncating the answer).
            words = full_response.split(' ')
            BATCH = 12
            for i in range(0, len(words), BATCH):
                chunk_words = words[i:i + BATCH]
                chunk_text = ' '.join(chunk_words)
                if i + BATCH < len(words):
                    chunk_text += ' '
                yield StreamingMessageResponse(
                    type="content",
                    content=chunk_text,
                    conversation_id=conversation_id,
                )

            yield StreamingMessageResponse(
                type="final_answer",
                content=full_response,
                conversation_id=conversation_id,
                metadata={
                    "context_used": len(tool_results),
                    "validation_confidence": agent_metadata.get("validation_confidence"),
                    "api_context": _sanitize_for_json(agent_metadata.get("api_context") or {}),
                    "rag_context": _sanitize_for_json(agent_metadata.get("rag_context") or {}),
                },
            )

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
                        "active_product_focus": agent_metadata.get("active_product_focus"),
                        "product_reference_map": agent_metadata.get("product_reference_map"),
                        "last_user_query": agent_metadata.get("last_user_query"),
                        "last_search_query": agent_metadata.get("last_search_query"),
                        "last_constraints": agent_metadata.get("last_constraints"),
                        "rerank_results": agent_metadata.get("rerank_results"),
                        "resolved_reference": agent_metadata.get("resolved_reference"),
                        # Remembered connector inputs so follow-ups reuse them.
                        "connector_inputs": self._collect_connector_inputs(session_state, lalkitab_plan, agent_metadata) or None,
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
                dealers=unique_dealers,
                metadata={
                    "commerce_intent": _sanitize_for_json(agent_metadata.get("commerce_intent") or agent_metadata.get("last_constraints") or {}),
                    "active_product_focus": _sanitize_for_json(agent_metadata.get("active_product_focus") or []),
                    "product_reference_map": _sanitize_for_json(agent_metadata.get("product_reference_map") or {}),
                    "original_query": agent_metadata.get("original_query") or agent_metadata.get("last_user_query"),
                    "search_query": agent_metadata.get("search_query") or agent_metadata.get("last_search_query"),
                    "rerank_results": _sanitize_for_json(agent_metadata.get("rerank_results") or []),
                    "resolved_reference": _sanitize_for_json(agent_metadata.get("resolved_reference") or {}),
                    "api_context": _sanitize_for_json(agent_metadata.get("api_context") or {}),
                    "rag_context": _sanitize_for_json(agent_metadata.get("rag_context") or {}),
                    "cart": _sanitize_for_json({
                        "cart_id": saved_cart_id,
                        "checkout_url": agent_metadata.get("checkout_url"),
                        "cart_lines": agent_metadata.get("cart_lines"),
                    }),
                },
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
