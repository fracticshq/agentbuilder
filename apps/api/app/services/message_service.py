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
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Optional
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
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
from tools.builtin.retrieval_tool import CatalogSearchTool, RetrievalTool
from tools.types import ToolResult
from agent_runtime.orchestrator import Orchestrator, AgentResult
from agent_runtime.orchestrator_shopify import ShopifyOrchestrator

from ..config import Settings
from ..connections import connection_manager
from ..monitoring import AGENT_FALLBACK_COUNT, GUARDRAIL_COUNT, MESSAGE_COUNT, MESSAGE_DURATION
from .response_validator import ResponseValidator, validate_claim_evidence  # Phase 4
from .strapi_client import StrapiClient
from .runtime_settings_service import RuntimeSettingsService
from .tool_config_secrets import decrypt_full_agent_configuration_for_runtime
from .capability_firewall import CapabilityDecision, CapabilityFirewall, configured_verticals
from .commerce_config import is_commerce_agent_config, normalize_commerce_configuration
from .observability_service import ObservabilityService
from .prompt_assembler import PromptAssembler
from .skill_registry import BuiltInSkillRegistry
from .artifact_registry import is_artifact_enabled
from .birth_profile_extractor import extract_birth_profile
from .lalkitab_runtime import (
    LAL_KITAB_CHART_UNAVAILABLE_MESSAGE,
    build_lalkitab_runtime_context,
    extract_kundali_chart_summary,
    is_lalkitab_agent,
    is_valid_lalkitab_context_payload,
)
from .conversation_policy import (
    activity_stream_response_kwargs,
    normalize_conversation_policy,
    plan_conversation_turn,
)
from .agent_turn_planner import AgentTurnPlan, AgentTurnPlanner
from .tool_registry import ToolRegistryService
from .conversation_scope_store import ConversationScopeStoreError, conversation_scope_store
from . import response_metadata as _response_metadata

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
LAL_KITAB_UNSUPPORTED_CLAIM_MESSAGE = (
    "I can’t verify that Lal Kitab interpretation or remedy from the calculated context I have. "
    "Please ask a narrower question or try again when the supporting information is available."
)
STREAM_GENERATION_ERROR_MESSAGE = (
    "I’m sorry, but I can’t complete that response right now. Please try again in a moment."
)
STREAM_GENERATION_ERROR_METADATA = {
    "code": "generation_failed",
    "retryable": True,
}
INTERNAL_SOURCE_TERMS = re.compile(
    r"\b(api|rag|chunk|chunks|connector|connectors|endpoint|endpoints|tool call|tool calls|tool-backed|"
    r"execution history|observation|observations|geocode lookup|runtime|mcp)\b",
    re.IGNORECASE,
)


def _is_unrecoverable_generation_failure(agent_result: AgentResult) -> bool:
    """Identify terminal generation failures without reclassifying safe abstentions.

    The orchestrator deliberately converts a second failed generation attempt
    into its ``safe_canned`` fallback so synchronous callers still receive a
    safe response.  In a stream, clients need an explicit terminal error to
    distinguish that failure from a completed answer.  Lal Kitab's validated
    chart abstention does not use this fallback marker and must remain a normal
    response.
    """
    metadata = getattr(agent_result, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}

    return (
        getattr(agent_result, "success", True) is False
        or metadata.get("fallback_stage") == "safe_canned"
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


def _public_lalkitab_api_context(api_context: dict | None, *, chart_validated: bool | None = None) -> dict:
    """Return the safe public subset of Lal Kitab runtime state.

    The complete chart input and response remain available only in internal
    short-term state for a later retry.  Public API and stream metadata must not
    include birth date/time/place, coordinates, provider URLs, or raw payloads.
    """
    context = api_context if isinstance(api_context, dict) else {}
    validated = (
        is_valid_lalkitab_context_payload(context.get("chart_context"))
        if chart_validated is None
        else bool(chart_validated)
    )
    provenance = []
    for item in context.get("source_provenance") or []:
        if isinstance(item, dict) and item.get("endpoint_id"):
            provenance.append(
                {
                    "endpoint_id": item.get("endpoint_id"),
                    "endpoint_name": item.get("endpoint_name"),
                }
            )
    return {
        "chart_available": validated,
        "chart_validated": validated,
        "secondary_endpoint_ids": sorted((context.get("secondary_endpoint_results") or {}).keys()),
        "source_provenance": provenance,
    }


def _public_lalkitab_place_candidates(candidates: list | None) -> list[dict]:
    """Expose disambiguation labels without precise location data."""
    return [
        {
            "placeId": candidate.get("placeId"),
            "name": candidate.get("name"),
            "adminRegion": candidate.get("adminRegion"),
            "country": candidate.get("country"),
            "label": candidate.get("label"),
        }
        for candidate in (candidates or [])
        if isinstance(candidate, dict)
    ]


def _public_lalkitab_missing_fields(missing: list | None) -> list[str]:
    """Hide coordinate fields behind the birth-place prompt shown to users."""
    public_fields: list[str] = []
    for field in missing or []:
        public_field = {
            "date": "birth_date",
            "time": "birth_time",
            "latitude": "birth_place",
            "longitude": "birth_place",
            "timezone": "birth_place",
        }.get(str(field), str(field))
        if public_field not in public_fields:
            public_fields.append(public_field)
    return public_fields


def _lalkitab_validation_confidence(lalkitab_plan, api_context: dict) -> float:
    """Derive confidence from the validated endpoint coverage for this turn."""
    selected = {
        str(endpoint_id)
        for endpoint_id in (getattr(lalkitab_plan, "selected_endpoint_ids", None) or [])
        if endpoint_id
    }
    validated_sources = {
        str(item.get("endpoint_id"))
        for item in (api_context.get("source_provenance") or [])
        if isinstance(item, dict) and item.get("endpoint_id")
    }
    if not selected:
        return 1.0 if is_valid_lalkitab_context_payload(api_context.get("chart_context")) else 0.0
    return min(1.0, len(selected & validated_sources) / len(selected))


def _normalize_commerce_product_currency(product: dict, agent_config: dict | None) -> dict:
    """Apply configured commerce currency policy before products leave the API."""
    if not isinstance(product, dict) or not is_commerce_agent_config(agent_config or {}):
        return product

    commerce = (agent_config or {}).get("commerce") or {}
    default_currency = str(commerce.get("default_currency") or "").strip().upper() or None
    policy = str(commerce.get("currency_policy") or "catalog_first_config_fallback").strip().lower()
    catalog_currency = (
        str(product.get("currency")).strip().upper()
        if product.get("currency") not in (None, "") and str(product.get("currency")).strip()
        else None
    )
    catalog_source = str(product.get("currency_source") or "").strip().lower()

    normalized = dict(product)
    if catalog_currency and catalog_source == "shopify_store":
        normalized["currency"] = catalog_currency
        normalized["currency_source"] = "shopify_store"
        return normalized
    if policy == "default_only":
        normalized["currency"] = default_currency
        normalized["currency_source"] = "commerce.default_currency" if default_currency else "missing"
        return normalized

    if catalog_currency:
        normalized["currency"] = catalog_currency
        normalized["currency_source"] = normalized.get("currency_source") or "product"
        return normalized

    if policy != "catalog_only" and default_currency:
        normalized["currency"] = default_currency
        normalized["currency_source"] = "commerce.default_currency"
        return normalized

    normalized["currency"] = None
    normalized["currency_source"] = "missing"
    return normalized


def _normalize_commerce_products_currency(products: list[dict], agent_config: dict | None) -> list[dict]:
    return [_canonicalize_commerce_product(_normalize_commerce_product_currency(product, agent_config)) for product in products]


def _canonicalize_commerce_product(product: dict) -> dict:
    """Normalize provider aliases into the widget's explicit minor-unit contract."""
    if not isinstance(product, dict):
        return product
    normalized = dict(product)
    if normalized.get("price_minor") is None and normalized.get("price") not in (None, ""):
        try:
            normalized["price_minor"] = int(round(float(normalized["price"])))
        except (TypeError, ValueError):
            normalized["price_minor"] = None
    normalized["price_unit"] = "minor"
    normalized["image_url"] = normalized.get("image_url") or normalized.get("image")
    normalized["product_url"] = normalized.get("product_url") or normalized.get("url")
    if normalized.get("currency_source") == "product":
        normalized["currency_source"] = "catalog"
    variants = normalized.get("variants")
    if isinstance(variants, list):
        normalized["variants"] = [_canonicalize_commerce_product(variant) for variant in variants if isinstance(variant, dict)]
    return normalized


def _safe_commerce_cart(
    agent_metadata: dict,
    tool_results: dict,
    previous: Optional[dict] = None,
    allowed_shop_url: Optional[str] = None,
) -> Optional[dict]:
    """Build one safe cart shape for sync, streaming, and persisted history."""
    state = dict(previous or {})
    for key in ("cart_id", "checkout_url", "cart_lines"):
        if agent_metadata.get(key) not in (None, ""):
            state[key] = agent_metadata[key]
    for tool_result in tool_results.values() if isinstance(tool_results, dict) else []:
        metadata = getattr(tool_result, "metadata", {}) or {}
        action = metadata.get("commerce_action") if isinstance(metadata.get("commerce_action"), dict) else {}
        cart = action.get("cart") if isinstance(action.get("cart"), dict) else metadata.get("cart")
        if not isinstance(cart, dict):
            continue
        for target, keys in {
            "cart_id": ("cart_id", "cartId", "id"),
            "checkout_url": ("checkout_url", "checkoutUrl"),
            "cart_lines": ("cart_lines", "lines", "line_items"),
        }.items():
            for key in keys:
                if cart.get(key) not in (None, ""):
                    state[target] = cart[key]
                    break
    if state.get("checkout_url"):
        try:
            parsed = urlsplit(str(state["checkout_url"]))
            allowed_host = urlsplit(str(allowed_shop_url)).hostname if allowed_shop_url else None
            if parsed.scheme != "https" or not parsed.hostname or (allowed_host and parsed.hostname != allowed_host):
                state["checkout_url"] = None
            else:
                state["checkout_url"] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        except Exception:
            state["checkout_url"] = None
    if not isinstance(state.get("cart_lines"), list):
        state["cart_lines"] = []
    return state if any(state.get(key) for key in ("cart_id", "checkout_url", "cart_lines")) else None


def _base_product_url(url: Any) -> Optional[str]:
    if url in (None, ""):
        return None
    try:
        parts = urlsplit(str(url))
        if not parts.scheme or not parts.netloc:
            return re.sub(r"\?.*$", "", str(url)).rstrip("/")
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except Exception:
        return re.sub(r"\?.*$", "", str(url)).rstrip("/")


def _commerce_product_group_key(product: dict) -> Optional[str]:
    for key in ("product_group_id", "product_id", "handle"):
        value = product.get(key)
        if value not in (None, ""):
            return f"{key}:{str(value).strip().lower()}"
    base_url = _base_product_url(product.get("product_url") or product.get("url") or product.get("variant_url"))
    if base_url:
        return f"url:{base_url.lower()}"
    return None


def _commerce_variant_identity(product: dict) -> Optional[str]:
    for key in ("variant_id", "variant_sku", "sku", "variant_url", "id"):
        value = product.get(key)
        if value not in (None, ""):
            return re.sub(r"\s+", " ", str(value).strip().lower())
    return None


def _variant_rank(product: dict, default: int = 9999) -> int:
    try:
        return int(product.get("_variant_rank"))
    except (TypeError, ValueError):
        return default


def _common_product_name(products: list[dict]) -> str:
    parent_names = [str(product.get("parent_name")) for product in products if product.get("parent_name")]
    if parent_names:
        return parent_names[0]
    names = [str(product.get("name") or product.get("title") or "") for product in products if product.get("name") or product.get("title")]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    prefix = names[0]
    for name in names[1:]:
        while prefix and not name.lower().startswith(prefix.lower()):
            prefix = prefix[:-1]
    return re.sub(r"[\s\-–—/]+$", "", prefix).strip() or names[0]


def _variant_label(product: dict, parent_name: str) -> str:
    explicit = product.get("variant_title")
    if explicit not in (None, "", "Default Title"):
        return str(explicit)
    name = str(product.get("name") or product.get("title") or "")
    if parent_name and name.lower().startswith(parent_name.lower()):
        suffix = re.sub(r"^[\s\-–—/]+", "", name[len(parent_name):]).strip()
        if suffix:
            return suffix
    return str(product.get("variant_sku") or product.get("sku") or product.get("variant_id") or "Variant")


def _commerce_variant_from_product(product: dict, selected: dict, parent_name: str) -> dict:
    variant_options = product.get("variant_options")
    if not isinstance(variant_options, dict) or not variant_options:
        variant_options = {"Variant": _variant_label(product, parent_name)}
    return {
        "id": product.get("variant_id") or product.get("id") or product.get("sku"),
        "variant_id": product.get("variant_id") or product.get("id") or product.get("sku"),
        "sku": product.get("variant_sku") or product.get("sku"),
        "variant_sku": product.get("variant_sku") or product.get("sku"),
        "name": product.get("name"),
        "title": product.get("variant_title") or _variant_label(product, parent_name),
        "variant_title": product.get("variant_title") or _variant_label(product, parent_name),
        "variant_options": variant_options,
        "price": product.get("price"),
        "currency": product.get("currency"),
        "currency_source": product.get("currency_source"),
        "image_url": product.get("image_url") or product.get("image"),
        "image": product.get("image") or product.get("image_url"),
        "product_url": product.get("product_url") or product.get("url"),
        "variant_url": product.get("variant_url") or product.get("product_url") or product.get("url"),
        "in_stock": product.get("in_stock", True),
        "is_default": _commerce_variant_identity(product) == _commerce_variant_identity(selected),
    }


def _group_commerce_products_for_cards(products: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    passthrough: list[dict] = []
    for index, product in enumerate(products):
        if not isinstance(product, dict):
            continue
        variants = product.get("variants")
        if isinstance(variants, list) and len(variants) > 1:
            passthrough.append(product)
            continue
        group_key = _commerce_product_group_key(product)
        if not group_key:
            passthrough.append(product)
            continue
        product_copy = dict(product)
        product_copy["_variant_rank"] = index
        if group_key not in groups:
            groups[group_key] = []
            order.append(group_key)
        groups[group_key].append(product_copy)

    grouped_products: list[dict] = []
    for group_key in order:
        group_products = groups[group_key]
        if len(group_products) == 1:
            product = dict(group_products[0])
            product.pop("_variant_rank", None)
            grouped_products.append(product)
            continue

        group_products = _deduplicate_entities(
            group_products,
            "variant_id",
            "variant_sku",
            "sku",
            "variant_url",
            "id",
        )
        selected = min(
            group_products,
            key=lambda product: (
                _variant_rank(product),
                0 if product.get("in_stock", True) else 1,
                float(product.get("price") or 10**18),
            ),
        )
        group_products = sorted(
            group_products,
            key=lambda product: (
                0 if _commerce_variant_identity(product) == _commerce_variant_identity(selected) else 1,
                _variant_rank(product),
                0 if product.get("in_stock", True) else 1,
                float(product.get("price") or 10**18),
                _commerce_variant_identity(product) or "",
            ),
        )
        parent_name = _common_product_name(group_products)
        variants = [_commerce_variant_from_product(product, selected, parent_name) for product in group_products]
        prices = [float(variant["price"]) for variant in variants if variant.get("price") not in (None, "")]
        card = dict(selected)
        card["product_group_id"] = selected.get("product_group_id") or group_key
        card["name"] = parent_name or selected.get("name") or selected.get("title") or "Product"
        card["title"] = card["name"]
        card["has_variants"] = True
        card["variant_count"] = max(int(selected.get("variant_count") or 0), len(variants))
        card["variants"] = variants
        card["default_variant_id"] = selected.get("variant_id") or selected.get("id") or selected.get("sku")
        if prices:
            card["price_min"] = min(prices)
            card["price_max"] = max(prices)
        card.pop("_variant_rank", None)
        grouped_products.append(card)

    return [*grouped_products, *passthrough]


def _prepare_commerce_products_for_response(products: list[dict], agent_config: dict | None) -> list[dict]:
    normalized = _normalize_commerce_products_currency(products, agent_config)
    return _group_commerce_products_for_cards(normalized)


def _safe_citation_text(value: Any, *, limit: int) -> Optional[str]:
    return _response_metadata._safe_citation_text(value, limit=limit)


def _safe_citation_url(value: Any) -> Optional[str]:
    return _response_metadata._safe_citation_url(value)


def _normalized_citation_confidence(value: Any, *, default: float) -> float:
    return _response_metadata._normalized_citation_confidence(value, default=default)


def _citation_from_metadata(value: Any, *, default_confidence: float) -> Optional[dict]:
    return _response_metadata._citation_from_metadata(value, default_confidence=default_confidence)


def _merge_citation(existing: dict, candidate: dict) -> dict:
    return _response_metadata._merge_citation(existing, candidate)


def _safe_retrieval_health(value: Any) -> Optional[dict]:
    return _response_metadata._safe_retrieval_health(value)


def _retrieval_health_from_tool_results(tool_results: Any) -> Optional[dict]:
    return _response_metadata._retrieval_health_from_tool_results(tool_results)


def _response_retrieval_health(tool_results: Any, agent_metadata: Any = None) -> Optional[dict]:
    return _response_metadata._response_retrieval_health(tool_results, agent_metadata)


def _extract_tool_result_metadata(tool_results: dict) -> tuple[list[dict], list[dict], list[dict]]:
    return _response_metadata._extract_tool_result_metadata(tool_results)


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

    async def _long_term_memory_consent_granted(
        self,
        *,
        conversation_id: str,
        user_id: str,
        agent_id: str,
    ) -> bool:
        """Fail closed unless this signed widget session explicitly opted in."""
        if not self._long_term_memory_enabled():
            return False
        try:
            return await conversation_scope_store.has_long_term_memory_consent(
                conversation_id=conversation_id,
                user_id=user_id,
                agent_id=agent_id,
            )
        except ConversationScopeStoreError:
            logger.warning(
                "long_term_memory_consent_unavailable",
                conversation_id=conversation_id,
                agent_id=agent_id,
            )
            return False

    def _agent_rag_config(self) -> dict:
        config = self.agent_config or {}
        rag = config.get("rag")
        return rag if isinstance(rag, dict) else {}

    def _rag_enabled(self) -> bool:
        if (self.agent_config or {}).get("data_source") == "shopify":
            shopify = (self.agent_config or {}).get("shopify") or {}
            if shopify.get("integration_mode") in {None, "", "hybrid_catalog_rag_mcp", "admin_catalog_sync"}:
                return True
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
                "status": (
                    "requires_explicit_session_consent"
                    if self._long_term_memory_enabled()
                    else "needs_privacy_setup"
                ),
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
        api_context: dict = {}
        rag_context: dict = {}
        for msg in reversed(recent):
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role != "assistant":
                continue
            meta = msg.metadata or {}
            if not pending and isinstance(meta.get("lalkitab_pending"), dict) and meta["lalkitab_pending"]:
                pending = dict(meta["lalkitab_pending"])
            if not remembered and isinstance(meta.get("connector_inputs"), dict) and meta["connector_inputs"]:
                remembered = dict(meta["connector_inputs"])
            if not api_context and isinstance(meta.get("lalkitab_api_context"), dict) and meta["lalkitab_api_context"]:
                api_context = dict(meta["lalkitab_api_context"])
            if not rag_context and isinstance(meta.get("lalkitab_rag_context"), dict) and meta["lalkitab_rag_context"]:
                rag_context = dict(meta["lalkitab_rag_context"])
            if pending and remembered and api_context and rag_context:
                break
        if not pending and not remembered and not api_context and not rag_context:
            return {}
        normalized: dict = {}
        normalized.update(remembered)
        normalized.update(pending.get("normalized_birth_input") or {})
        result: dict = {"normalized_birth_input": normalized}
        if api_context:
            result["api_context"] = api_context
            if isinstance(api_context.get("normalized_birth_input"), dict):
                result["normalized_birth_input"] = {
                    **(api_context.get("normalized_birth_input") or {}),
                    **normalized,
                }
        if rag_context:
            result["rag_context"] = rag_context
        if pending.get("awaiting_place_choice"):
            result["awaiting_place_choice"] = True
            result["place_candidates"] = pending.get("place_candidates") or []
        return result

    async def _load_conversation_policy_state(self, conversation_id: str) -> dict:
        """Load generic policy-guided conversation state from recent assistant turns."""
        if not self.short_term:
            return {}
        try:
            recent = await self.short_term.get_recent_messages(conversation_id=conversation_id, limit=8)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("conversation_policy_state_load_failed", error=str(exc))
            return {}
        state: dict = {"resolved_inputs": {}, "pending_inputs": [], "cached_evidence": {}, "context_decisions": []}
        for msg in reversed(recent or []):
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role != "assistant":
                continue
            meta = msg.metadata or {}
            if isinstance(meta.get("resolved_inputs"), dict) and meta["resolved_inputs"]:
                state["resolved_inputs"] = {**meta["resolved_inputs"], **state.get("resolved_inputs", {})}
            if not state.get("pending_inputs") and isinstance(meta.get("pending_inputs"), list):
                state["pending_inputs"] = meta["pending_inputs"]
            if not state.get("cached_evidence") and isinstance(meta.get("cached_evidence"), dict):
                state["cached_evidence"] = meta["cached_evidence"]
            if isinstance(meta.get("context_decision"), dict):
                state.setdefault("context_decisions", []).append(meta["context_decision"])
            if state.get("resolved_inputs") and state.get("cached_evidence"):
                break
        return state

    def _lalkitab_pending_from_policy(self, policy_state: dict, turn_plan) -> dict:
        """Bridge generic resolved inputs into the existing chart-first adapter."""
        resolved = {
            **(policy_state.get("resolved_inputs") if isinstance(policy_state.get("resolved_inputs"), dict) else {}),
            **(getattr(turn_plan, "resolved_inputs", None) or {}),
        }
        normalized: dict = {}
        if resolved.get("birth_date"):
            normalized["date"] = resolved["birth_date"]
            normalized["birth_date"] = resolved["birth_date"]
        if resolved.get("birth_time"):
            normalized["time"] = resolved["birth_time"]
            normalized["birth_time"] = resolved["birth_time"]
        if resolved.get("birth_place"):
            normalized["birth_place"] = resolved["birth_place"]
        if normalized.get("date") and normalized.get("time"):
            normalized["datetime"] = f"{normalized['date']}T{normalized['time']}"
        return {"normalized_birth_input": normalized} if normalized else {}

    _LALKITAB_COORD_FIELD_IDS = {"latitude", "longitude", "timezone", "lat", "lon", "lng", "long", "coordinates"}
    _LALKITAB_PROFILE_TO_INPUT = (
        ("name", "name"),
        ("birth_date", "birth_date"),
        ("birth_time", "birth_time"),
        ("birth_place", "birth_place"),
    )

    async def _prepare_lalkitab_turn(
        self,
        turn_plan: AgentTurnPlan,
        message: str,
        policy_state: dict[str, Any],
        llm_provider: Any | None = None,
    ) -> tuple[AgentTurnPlan, dict[str, Any] | None]:
        """LLM-first understanding for Lal Kitab turns.

        Runs the birth-profile extractor (name / date / time / place /
        question separated by an LLM, deterministically validated) and uses it
        to correct the planner's view of the turn, so a person's name or the
        question can never be treated as the birth place. Returns the adapted
        plan plus the profile for the chart-first runtime.
        """
        if not is_lalkitab_agent(self.agent_config or {}):
            return turn_plan, None

        prior_profile = {
            **(policy_state.get("resolved_inputs") if isinstance(policy_state.get("resolved_inputs"), dict) else {}),
            **(turn_plan.resolved_inputs or {}),
        }
        try:
            profile = await extract_birth_profile(
                message,
                prior_profile=prior_profile,
                llm_provider=llm_provider or self.llm_provider,
            )
        except Exception as exc:  # pragma: no cover - extractor is defensive already
            logger.warning("lalkitab_birth_profile_failed", error=str(exc))
            profile = None

        if profile:
            # The profile is the authoritative interpretation of this turn.
            for profile_key, input_key in self._LALKITAB_PROFILE_TO_INPUT:
                if profile.get(profile_key):
                    turn_plan.resolved_inputs[input_key] = profile[profile_key]
            if profile.get("question"):
                turn_plan.question = profile["question"]
            # Re-derive missing inputs now that the profile filled fields the
            # planner missed (this is what previously forced wrong clarifications).
            still_missing = [
                item for item in (turn_plan.missing_inputs or [])
                if str(item.get("id", "")) not in turn_plan.resolved_inputs
            ]
            if still_missing != (turn_plan.missing_inputs or []):
                turn_plan.missing_inputs = still_missing
                turn_plan.pending_inputs = still_missing
                if not still_missing and turn_plan.action == "ask_missing_input":
                    turn_plan.action = "ready"
                    turn_plan.intent = "answer"
                    turn_plan.public_response = None
                    turn_plan.response_text = ""
            # Genuine ambiguities (e.g. 03/04/1990 day-month order) are the
            # only reason to pause and ask.
            required_missing = any(
                not turn_plan.resolved_inputs.get(field)
                for field in ("birth_date", "birth_time", "birth_place")
            )
            if profile.get("ambiguities") and required_missing:
                turn_plan.action = "clarify"
                turn_plan.intent = "clarify"
                clarification = " ".join(profile["ambiguities"])
                turn_plan.public_response = clarification
                turn_plan.response_text = clarification

        return self._adapt_turn_plan_for_lalkitab(turn_plan), profile

    def _adapt_turn_plan_for_lalkitab(self, turn_plan: AgentTurnPlan) -> AgentTurnPlan:
        """Keep Lal Kitab turns on the chart-first runtime.

        - Planner tool plans would call Vedika endpoints directly and skip
          geocoding + chart-first ordering, so they are dropped in favour of
          the dedicated runtime (this is what previously caused the agent to
          ask users for latitude/longitude).
        - Coordinates/timezone are derived automatically from the birthplace,
          so a turn must never block asking the user for them.
        - Once the birth details are complete, the kundali chart is built and
          shown right away instead of first asking "what would you like to
          ask?" — the chart does not depend on the question.
        """
        if not is_lalkitab_agent(self.agent_config or {}):
            return turn_plan
        if turn_plan.tool_plan:
            turn_plan.tool_plan = []
            turn_plan.context_decision = {
                **(turn_plan.context_decision or {}),
                "use_connectors": True,
                "reason": "lalkitab_chart_first_runtime",
            }
        if turn_plan.missing_inputs or turn_plan.pending_inputs:
            kept = [
                item
                for item in (turn_plan.missing_inputs or turn_plan.pending_inputs or [])
                if str(item.get("id", "")).lower() not in self._LALKITAB_COORD_FIELD_IDS
            ]
            if len(kept) != len(turn_plan.missing_inputs or turn_plan.pending_inputs or []):
                turn_plan.missing_inputs = kept
                turn_plan.pending_inputs = kept
                if not kept and turn_plan.action == "ask_missing_input":
                    turn_plan.action = "ready"
                    turn_plan.intent = "answer"
                    turn_plan.public_response = None
                    turn_plan.response_text = ""
        if turn_plan.action == "ask_question":
            turn_plan.action = "ready"
            turn_plan.intent = "answer"
            turn_plan.public_response = None
            turn_plan.response_text = ""
            turn_plan.context_decision = {
                **(turn_plan.context_decision or {}),
                "use_connectors": True,
                "reason": "birth_details_complete_build_chart_first",
            }
        return turn_plan

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
        birth_profile: dict | None = None,
    ) -> AgentResult:
        """Generate a Lal Kitab answer grounded in chart-first API context plus RAG."""
        api_context = lalkitab_plan.api_context or {}
        chart_validated = bool(
            getattr(lalkitab_plan, "chart_validated", False)
            and is_valid_lalkitab_context_payload(api_context.get("chart_context"))
        )
        requires_safe_abstention = bool(
            getattr(lalkitab_plan, "requires_safe_abstention", False)
            or not chart_validated
        )
        tool_results = dict(lalkitab_plan.tool_results or {})
        if rag_tool_result:
            tool_results["knowledge_search"] = rag_tool_result
        if requires_safe_abstention:
            # Never ask the LLM to fill gaps in a chart reading.  A connector
            # failure, malformed payload, or missing validated chart must be a
            # deterministic abstention rather than an astrology synthesis.
            return AgentResult(
                answer=LAL_KITAB_CHART_UNAVAILABLE_MESSAGE,
                metadata={
                    "tool_results": tool_results,
                    "steps_executed": len(tool_results),
                    "validation_passed": False,
                    "validation_confidence": 0.0,
                    "validation_issues": ["validated_chart_context_unavailable"],
                    "lalkitab_runtime": True,
                    "api_context": _public_lalkitab_api_context(
                        api_context, chart_validated=False
                    ),
                    "selected_connector_endpoint_ids": getattr(
                        lalkitab_plan, "selected_endpoint_ids", []
                    ),
                    "used_cached_context": False,
                    # Retained only in internal short-term metadata so a later
                    # request can retry with the already-collected birth input.
                    "lalkitab_api_context_full": _sanitize_for_json(api_context),
                    "lalkitab_rag_context_full": _sanitize_for_json(rag_context),
                    "rag_context": {
                        "chunks_count": len(rag_context.get("chunks") or []),
                        "sources": rag_context.get("sources") or [],
                        "confidence": rag_context.get("confidence"),
                    },
                },
            )
        validation_confidence = _lalkitab_validation_confidence(
            lalkitab_plan, api_context
        )
        input_resolution = api_context.get("input_resolution") if isinstance(api_context.get("input_resolution"), dict) else {}
        confirmation_rule = (
            "- Start by briefly confirming the birth details you used. If a detail was inferred from a known place, say so naturally."
            if input_resolution.get("confirm_understood_details", True) is not False
            else "- Do not add a separate birth-detail confirmation unless the user asks."
        )
        hide_internal_sources = bool((self.agent_config or {}).get("conversation_policy", {}).get("hide_internal_sources", True))
        source_rule = (
            "- Do not mention APIs, RAG, chunks, connectors, tools, endpoint names, source provenance, or internal context handling in the user-facing answer."
            if hide_internal_sources
            else "- You may briefly describe the evidence used if it helps the user."
        )
        # Structured chart summary for the widget's visual kundali artifact.
        # Admin-configurable per agent (configuration.artifacts.kundali_chart);
        # when disabled the reading falls back to the markdown chart table.
        kundali_chart = (
            extract_kundali_chart_summary(api_context)
            if is_artifact_enabled(self.agent_config or {}, "kundali_chart")
            else None
        )
        normalized_birth = api_context.get("normalized_birth_input") or {}
        user_name = normalized_birth.get("name") or (birth_profile or {}).get("name")
        name_rule = (
            f"- Address the user by name ({user_name}) naturally, like an astrologer who knows them.\n"
            if user_name else ""
        )
        profile_question = (birth_profile or {}).get("question")
        question_rule = (
            f"- The user's actual question this turn is: \"{profile_question}\" — answer that directly.\n"
            if profile_question else ""
        )
        chart_step = (
            "2. The kundali chart itself is rendered as a visual diagram by the app alongside\n"
            "   your reply — do NOT print a chart table, ASCII chart, or house-by-house grid.\n"
            "   Go straight from the birth-details line to the walkthrough."
            if kundali_chart
            else
            "2. **The Lal Kitab kundali chart** — a markdown table with columns\n"
            "   House | Rashi | Planets, listing all 12 houses in order, built ONLY from the\n"
            "   calculated chart context. Write \"—\" for empty houses. Never guess a placement."
        )
        prompt = f"""
{self.system_prompt}

You are answering a Lal Kitab / Vedic Jyotish question for the user, in the voice of a
warm, seasoned Lal Kitab astrologer sitting across the table — human, direct, a little
affectionate ("beta", "child"), never clinical or system-like.

Rules:
- Use the calculated context internally for chart/calculation facts.
- Use the knowledge context internally for interpretation policy, tone, explanations, FAQs, and Lal Kitab reference context.
{confirmation_rule}
- Never invent chart placements, debts, remedies, predictions, totke, lucky factors, houses, or varshphal data.
- If calculated context is incomplete, ask for the missing detail or say that you cannot verify that part.
- Speak like a human advisor helping the user, not like a system explaining its architecture.
{source_rule}
- Do not claim certainty beyond the provided sources.
- Reply in the language the user is writing in (Hindi, Hinglish, or English); use both
  English and Hindi names for rashis and planets (e.g. "Pisces (Meen)", "Shani (Saturn)").
{name_rule}{question_rule}

Answer format — follow this order strictly (the kundali chart always comes FIRST,
before any interpretation, prediction, or remedy):

1. One-line confirmation of the birth details used: date, time, place (and the lagna/
   ascendant if the calculated context provides it).
{chart_step}
3. **Where the planets sit** — short, warm notes for each occupied house (what that
   house governs and what the placement means), like an astrologer walking through
   the chart aloud.
4. **The real matter** — directly address the user's question using the chart and any
   prediction/houses/debts evidence. Name the strengths first, then the weak spot,
   plainly and kindly.
5. **Lal Kitab remedies** — a short numbered list, only from remedy/totke evidence;
   practical conduct corrections, not just rituals.
6. **The final word** — two or three encouraging closing lines in the same voice.
7. A small **Confidence** table (Area | Confidence | Why) for the life areas touched
   by the question, honestly graded from the strength of the evidence.
8. End with one line: Lal Kitab reading is a guidance tradition, not a guarantee —
   conduct, effort and discipline are themselves the biggest remedy.

If the user has NOT asked a specific question yet, stop after steps 1-3 plus a brief
overall reading, then warmly invite their question (career, marriage, foreign, health…).

User Query:
{message}

Conversation (rolling memory + recent turns):
{json.dumps(chat_history, default=str, indent=2)}

Calculated API Context:
{json.dumps(_sanitize_for_json(api_context), default=str, indent=2)}

Knowledge Context:
{json.dumps(_sanitize_for_json(rag_context), default=str, indent=2)}

Answer the user directly.
"""
        response = await self.llm_provider.generate(prompt)
        return AgentResult(
            answer=response.content,
            metadata={
                "tool_results": tool_results,
                "steps_executed": len(tool_results),
                "validation_passed": chart_validated,
                "validation_confidence": validation_confidence,
                "lalkitab_runtime": True,
                "extractor_source": (birth_profile or {}).get("source"),
                "kundali_chart": _sanitize_for_json(kundali_chart) if kundali_chart else None,
                "api_context": _public_lalkitab_api_context(
                    api_context, chart_validated=chart_validated
                ),
                "selected_connector_endpoint_ids": lalkitab_plan.selected_endpoint_ids,
                "used_cached_context": bool(getattr(lalkitab_plan, "used_cached_context", False)),
                "lalkitab_api_context_full": _sanitize_for_json(api_context),
                "lalkitab_rag_context_full": _sanitize_for_json(rag_context),
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
        metadata = dict(metadata or {})
        if metadata.pop("_trusted_safety_template", False):
            # Pre-response block/escalation messages are server-owned templates,
            # not generated factual claims. They may safely bypass evidence
            # matching while retaining an auditable, non-sensitive marker.
            metadata["evidence_validation"] = {
                "claim_count": 0,
                "evidence_record_count": 0,
                "unsupported_claim_count": 0,
                "trusted_safety_template": True,
            }
            return response_text, metadata
        validation_issues = metadata.get("validation_issues") or []
        lalkitab_safe_abstention = bool(
            metadata.get("lalkitab_runtime")
            and (
                response_text == LAL_KITAB_CHART_UNAVAILABLE_MESSAGE
                or "validated_chart_context_unavailable" in validation_issues
            )
        )
        confidence = float(metadata.get("validation_confidence", 1.0) or 1.0)
        threshold = getattr(self.settings, "CONFIDENCE_THRESHOLD", 0.70)
        try:
            threshold_value = float(threshold)
        except (TypeError, ValueError):
            threshold_value = 0.70
        if confidence < threshold_value and not lalkitab_safe_abstention:
            GUARDRAIL_COUNT.labels(action="fallback", reason="low_confidence").inc()
            next_metadata = {
                **metadata,
                "guardrail_action": "fallback",
                "guardrail_reason": "low_confidence",
                "original_confidence": confidence,
            }
            return self._apply_claim_evidence_guard(LOW_CONFIDENCE_MESSAGE, next_metadata)

        hide_internal_sources = bool(
            ((self.agent_config or {}).get("conversation_policy") or {}).get("hide_internal_sources", True)
        )
        if hide_internal_sources and response_text and INTERNAL_SOURCE_TERMS.search(response_text):
            response_text, metadata = self._strip_internal_source_language(response_text), {
                **metadata,
                "public_answer_sanitized": True,
            }

        return self._apply_claim_evidence_guard(response_text, metadata)

    def _apply_claim_evidence_guard(self, response_text: str, metadata: dict | None) -> tuple[str, dict]:
        """Fail closed when a final answer makes a factual claim without evidence.

        This central final-answer gate is intentionally synchronous and
        deterministic. It accepts textual retrieval evidence and structured
        commerce/chart data, while keeping the evidence comparison private.
        """
        next_metadata = dict(metadata or {})
        validation = validate_claim_evidence(
            response_text,
            tool_results=next_metadata.get("tool_results"),
            runtime_metadata=next_metadata,
        )
        next_metadata["evidence_validation"] = validation.metadata
        if validation.is_valid:
            return validation.sanitized_response, next_metadata

        is_lalkitab = bool(next_metadata.get("lalkitab_runtime"))
        chart_was_validated = bool(next_metadata.get("validation_passed")) and (
            "validated_chart_context_unavailable" not in (next_metadata.get("validation_issues") or [])
        )
        if is_lalkitab and chart_was_validated:
            fallback_message = LAL_KITAB_UNSUPPORTED_CLAIM_MESSAGE
        elif is_lalkitab:
            fallback_message = LAL_KITAB_CHART_UNAVAILABLE_MESSAGE
        else:
            fallback_message = LOW_CONFIDENCE_MESSAGE
        GUARDRAIL_COUNT.labels(action="fallback", reason="claim_evidence").inc()
        logger.warning(
            "claim_evidence_guard_fallback",
            claim_count=validation.metadata.get("claim_count", 0),
            evidence_record_count=validation.metadata.get("evidence_record_count", 0),
            unsupported_claim_count=validation.metadata.get("unsupported_claim_count", 0),
            lalkitab_runtime=is_lalkitab,
        )
        return fallback_message, {
            **next_metadata,
            "fallback": True,
            "fallback_stage": "claim_evidence",
            "fallback_reason": "unsupported_claim",
            "guardrail_action": "fallback",
            "guardrail_reason": "claim_evidence",
            "validation_passed": False,
            "validation_confidence": 0.0,
            "validation_issues": ["unsupported_factual_claim"],
        }

    def _strip_internal_source_language(self, response_text: str) -> str:
        """Remove backend/runtime explanations from public answers."""
        kept: list[str] = []
        for paragraph in re.split(r"\n{2,}", response_text or ""):
            if INTERNAL_SOURCE_TERMS.search(paragraph):
                continue
            cleaned = paragraph.strip()
            if cleaned:
                kept.append(cleaned)
        if kept:
            return "\n\n".join(kept)
        return (
            "I couldn’t complete the calculation cleanly from the details available right now. "
            "Please share your question again and I’ll re-check it carefully."
        )

    async def _store_guardrail_response(
        self,
        *,
        conversation_id: str,
        user_id: str,
        agent_id: str,
        user_message: str,
        decision: dict,
    ) -> MessageResponse:
        response_text, response_metadata = self._apply_post_response_guardrails(
            decision["message"],
            {
                "validation_confidence": 1.0,
                "validation_passed": False,
                "guardrail_action": decision["action"],
                "guardrail_reason": decision["reason"],
                "_trusted_safety_template": True,
            },
        )
        if self._short_term_memory_enabled():
            await self.short_term.add_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=response_text,
                metadata={
                    "user_id": user_id,
                    "guardrail_action": response_metadata.get("guardrail_action"),
                    "guardrail_reason": response_metadata.get("guardrail_reason"),
                    "capability_scope": decision.get("capability_scope"),
                    "validation_passed": response_metadata.get("validation_passed"),
                    "evidence_validation": response_metadata.get("evidence_validation"),
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

    async def _planner_llm_provider(self, policy: dict[str, Any]):
        """Use the configured planner model when available, otherwise the agent LLM.

        Planner model override is best-effort; if the deployment is not
        configured yet, the harness keeps running with the agent model.
        """
        planner_model = (policy or {}).get("planner_model")
        current_model = getattr(getattr(self.llm_provider, "config", None), "model", None)
        if not planner_model or planner_model == current_model:
            return self.llm_provider
        try:
            llm_config = (self.agent_config or {}).get("llm") if isinstance((self.agent_config or {}).get("llm"), dict) else {}
            runtime_config = await self.runtime_settings_service.get_llm_runtime_config(
                provider_name=llm_config.get("provider"),
                model=str(planner_model),
            )
            return self._build_llm_provider(runtime_config)
        except Exception as exc:  # pragma: no cover - defensive; runtime fallback
            logger.warning(
                "planner_model_override_failed",
                planner_model=planner_model,
                current_model=current_model,
                error=str(exc),
            )
            return self.llm_provider

    def _tool_schemas_for_planner(self) -> list[dict[str, Any]]:
        if not self.tool_registry:
            return []
        try:
            return self.tool_registry.get_tool_schemas()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("planner_tool_schema_failed", error=str(exc))
            return []

    def _resolve_planner_tool(self, tool_id: str):
        if not self.tool_registry or not tool_id:
            return None
        exact = self.tool_registry.get(tool_id)
        if exact:
            return exact
        safe_tool_id = str(tool_id).lower().strip()
        for tool in self.tool_registry.list_tools():
            if getattr(tool, "name", "") == tool_id:
                return tool
            endpoint = getattr(tool, "endpoint", None)
            if isinstance(endpoint, dict):
                endpoint_id = str(endpoint.get("id") or "").lower()
                endpoint_name = str(endpoint.get("name") or "").lower()
                if safe_tool_id in {endpoint_id, endpoint_name} or getattr(tool, "name", "").lower().endswith(safe_tool_id):
                    return tool
        return None

    async def _execute_planner_tool_plan(
        self,
        *,
        turn_plan: AgentTurnPlan,
        message: str,
        conversation_id: str,
    ) -> tuple[dict[str, ToolResult], list[StreamingMessageResponse]]:
        """Execute a validated planner tool plan through registered allowlisted tools."""
        tool_results: dict[str, ToolResult] = {}
        events: list[StreamingMessageResponse] = []
        resolved_inputs = dict(turn_plan.resolved_inputs or {})
        for index, step in enumerate(turn_plan.tool_plan or []):
            tool_id = str(step.get("tool_id") or "").strip()
            tool = self._resolve_planner_tool(tool_id)
            step_key = tool_id or f"step_{index + 1}"
            if not tool:
                result = ToolResult(
                    success=False,
                    data=None,
                    error=f"Tool {tool_id} is not available to this agent.",
                    metadata={"tool_id": tool_id, "blocked_reason": "tool_not_available"},
                )
                tool_results[step_key] = result
                events.append(
                    StreamingMessageResponse(
                        type="activity",
                        content=f"{tool_id} is not available.",
                        conversation_id=conversation_id,
                        metadata={
                            "activity": {
                                "activity_id": f"tool:{step_key}",
                                "kind": "tool_call",
                                "status": "failed",
                                "visibility": "console",
                                "label": f"Tool unavailable: {tool_id}",
                                "summary": result.error,
                                "data": result.metadata,
                                "controls": [],
                            }
                        },
                    )
                )
                continue

            tool_name = getattr(tool, "name", tool_id)
            tool_input = step.get("input") if isinstance(step.get("input"), dict) else {}
            payload = tool_input.get("payload") if isinstance(tool_input.get("payload"), dict) else {}
            payload = {**resolved_inputs, **payload}
            run_kwargs = dict(tool_input)
            if "query" not in run_kwargs:
                run_kwargs["query"] = turn_plan.question or message
            if payload:
                run_kwargs["payload"] = payload

            events.append(
                StreamingMessageResponse(
                    type="activity",
                    content=step.get("reason") or f"Running {tool_name}",
                    conversation_id=conversation_id,
                    metadata={
                        "activity": {
                            "activity_id": f"tool:{tool_name}",
                            "kind": "connector_call" if str(tool_name).startswith("tool_context_") else "tool_call",
                            "status": "running",
                            "visibility": "public",
                            "label": step.get("reason") or "Checking the configured source",
                            "summary": step.get("reason") or "",
                            "data": {"tool_name": tool_name, "tool_id": tool_id},
                            "controls": [],
                        }
                    },
                )
            )
            try:
                result = await tool.run(**run_kwargs)
            except Exception as exc:  # pragma: no cover - defensive
                result = ToolResult(success=False, data=None, error=str(exc), metadata={"tool_id": tool_id, "tool_name": tool_name})
            tool_results[tool_name] = result
            metadata = getattr(result, "metadata", None) or {}
            status = "completed" if result.success else "failed"
            events.append(
                StreamingMessageResponse(
                    type="activity",
                    content=f"{tool_name} completed." if result.success else (result.error or f"{tool_name} failed."),
                    conversation_id=conversation_id,
                    metadata={
                        "activity": {
                            "activity_id": f"tool:{tool_name}",
                            "kind": "connector_call" if metadata.get("connector_id") else "tool_call",
                            "status": status,
                            "visibility": "public" if result.success else "console",
                            "label": metadata.get("endpoint_name") or metadata.get("connector_name") or tool_name,
                            "summary": "Done." if result.success else (result.error or "The call failed."),
                            "data": _sanitize_for_json(metadata),
                            "controls": [],
                        }
                    },
                )
            )
            if isinstance(metadata.get("resolved_inputs"), dict):
                resolved_inputs.update({k: v for k, v in metadata["resolved_inputs"].items() if v not in (None, "")})
        return tool_results, events

    async def _generate_planner_agent_result(
        self,
        *,
        message: str,
        chat_history: list[dict],
        turn_plan: AgentTurnPlan,
        tool_results: dict[str, ToolResult],
        rag_tool_result: ToolResult | None = None,
    ) -> AgentResult:
        """Synthesize a public answer from the LLM-first plan and executed evidence."""
        all_tool_results = dict(tool_results or {})
        if rag_tool_result:
            all_tool_results["knowledge_search"] = rag_tool_result
        hide_internal_sources = bool((self.agent_config or {}).get("conversation_policy", {}).get("hide_internal_sources", True))
        evidence = {
            key: {
                "success": result.success,
                "data": _sanitize_for_json(result.data if isinstance(result.data, dict) else {"value": result.data}),
                "error": result.error,
                "metadata": _sanitize_for_json(result.metadata or {}),
            }
            for key, result in all_tool_results.items()
        }
        source_rule = (
            "Do not mention APIs, RAG, chunks, connectors, tools, endpoint names, source provenance, or internal context handling."
            if hide_internal_sources
            else "You may briefly describe evidence sources if it helps."
        )
        prompt = f"""
{self.system_prompt}

You are writing the final answer for a NOVA agent after a structured planner and allowlisted tools ran.

User message:
{message}

Planner output:
{json.dumps(_sanitize_for_json(turn_plan.raw_plan or {}), indent=2, default=str)}

Resolved user inputs:
{json.dumps(_sanitize_for_json(turn_plan.resolved_inputs or {}), indent=2, default=str)}

Conversation history:
{json.dumps(chat_history[-8:], indent=2, default=str)}

Tool and context evidence:
{json.dumps(evidence, indent=2, default=str)}

Rules:
- Answer the user directly in the configured agent style.
- Use the evidence internally; do not fabricate missing facts.
- If evidence is insufficient, ask for the next useful detail or say what you can answer without overclaiming.
- {source_rule}
"""
        response = await self.llm_provider.generate(prompt)
        return AgentResult(
            answer=response.content,
            metadata={
                "tool_results": all_tool_results,
                "steps_executed": len(all_tool_results),
                "validation_passed": True,
                "validation_confidence": 0.9,
                "planner": {
                    "source": turn_plan.source,
                    "intent": turn_plan.intent,
                    "context_decision": turn_plan.context_decision,
                    "tool_plan": turn_plan.tool_plan,
                    "resolved_inputs": turn_plan.resolved_inputs,
                },
                "api_context": {
                    "tool_outputs": {
                        key: _sanitize_for_json(result.metadata or {})
                        for key, result in all_tool_results.items()
                    }
                },
            },
        )

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
                verticals=sorted(configured_verticals(self.agent_config or {})),
            )
            logger.info("retrieval_pipeline_initialized", brand_id=brand_slug)
        except Exception as e:
            logger.warning("retrieval_pipeline_init_failed", brand_id=brand_slug, error=str(e))
            self.retrieval_pipeline = None

        self.tool_registry = ToolRegistry()
        if self.retrieval_pipeline:
            self.tool_registry.register(RetrievalTool(self.retrieval_pipeline))
            if (self.agent_config or {}).get("data_source") == "shopify":
                commerce_config = (self.agent_config or {}).get("commerce") or {}
                self.tool_registry.register(CatalogSearchTool(self.retrieval_pipeline, name="search_catalog", commerce_config=commerce_config))
                self.tool_registry.register(CatalogSearchTool(self.retrieval_pipeline, name="search_shop_catalog", commerce_config=commerce_config))

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
                config = normalize_commerce_configuration(config)
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
                    from tools.mcp_client import McpClient, McpDiscoveryError
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
                        if self.settings.MCP_SERVICE_AUTH_TOKEN:
                            mcp_headers["Authorization"] = (
                                f"Bearer {self.settings.MCP_SERVICE_AUTH_TOKEN}"
                            )
                        elif self.settings.is_production:
                            logger.error("shopify_mcp_service_token_missing", agent_id=agent_id)
                            raise McpDiscoveryError("Shopify MCP service authentication is not configured")
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
                        if not remote_tools:
                            raise McpDiscoveryError("Shopify MCP did not expose any enabled tools")
                        local_catalog_tool_names = {"search_catalog", "search_shop_catalog"}
                        prefer_local_catalog = shopify_conf.get("integration_mode") == "hybrid_catalog_rag_mcp"
                        for tool in remote_tools:
                            if prefer_local_catalog and tool.name in local_catalog_tool_names:
                                continue
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

        except McpDiscoveryError:
            # Live commerce was explicitly enabled.  Do not silently replace a
            # failed/misconfigured MCP boundary with a generic agent runtime.
            raise
        except Exception as e:
            logger.error("agent_config_load_error", error_type=type(e).__name__)
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
            long_term_enabled = await self._long_term_memory_consent_granted(
                conversation_id=conversation_id,
                user_id=user_id,
                agent_id=agent_id,
            )
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

            conversation_policy = normalize_conversation_policy(self.agent_config or {})
            policy_state = (
                await self._load_conversation_policy_state(conversation_id)
                if short_term_enabled else {}
            )
            fallback_turn_plan = plan_conversation_turn(
                message=runtime_message,
                policy=conversation_policy,
                previous_state=policy_state,
            )
            planner_provider = await self._planner_llm_provider(conversation_policy)
            turn_plan = await AgentTurnPlanner(planner_provider).plan(
                message=runtime_message,
                policy=conversation_policy,
                previous_state=policy_state,
                tool_schemas=self._tool_schemas_for_planner(),
                system_prompt=self.system_prompt or "",
                fallback_plan=fallback_turn_plan,
            )
            turn_plan, lalkitab_profile = await self._prepare_lalkitab_turn(
                turn_plan, runtime_message, policy_state, llm_provider=planner_provider
            )

            if turn_plan.should_short_circuit:
                response_text = turn_plan.response_text
                duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                metadata = {
                    "user_id": user_id,
                    "resolved_inputs": _sanitize_for_json(turn_plan.resolved_inputs),
                    "pending_inputs": turn_plan.pending_inputs,
                    "context_decision": turn_plan.context_decision,
                    "validation_passed": True,
                    "validation_confidence": 1.0,
                }
                response_text, metadata = self._apply_post_response_guardrails(response_text, metadata)
                if short_term_enabled:
                    await self.short_term.add_message(
                        conversation_id=conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=response_text,
                        metadata=metadata,
                    )
                self.strapi.sync_conversation(
                    conversation_id=conversation_id,
                    user_message=request.message,
                    assistant_message=response_text,
                    brand_slug=self.brand_id,
                    agent_id=agent_id,
                )
                await self.observability.track_event(
                    event_type="message_processed",
                    brand_slug=self.brand_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    payload={
                        "mode": "sync",
                        "status": f"policy_{turn_plan.action}",
                        "latency_ms": duration_ms,
                        "context_used": 0,
                        "context_decision": turn_plan.context_decision,
                    },
                )
                MESSAGE_COUNT.labels(status=f"policy_{turn_plan.action}").inc()
                MESSAGE_DURATION.labels(mode="sync", status=f"policy_{turn_plan.action}").observe(duration_ms / 1000)
                return MessageResponse(
                    message=response_text,
                    conversation_id=conversation_id,
                    citations=[],
                    context_used=0,
                    confidence_score=min(1.0, max(0.0, float(metadata.get("validation_confidence", 1.0)))),
                    processing_time_ms=duration_ms,
                )

            # 3. Build context for the agent (pass safe context)
            memory_context = await self._build_memory_context(
                conversation_id=conversation_id,
                user_id=user_id,
                query=runtime_message,
                escalations=escalations,
                long_term_enabled=long_term_enabled,
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
                        "connector_inputs",
                    ):
                        if key in meta:
                            session_state[key] = meta.get(key)

            remembered_inputs = session_state.get("connector_inputs") or {}
            if remembered_inputs:
                self._apply_remembered_connector_inputs(remembered_inputs)

            context_dict = {
                "memory": memory_context,
                "session_state": session_state,
                "prompt_runtime": self._build_prompt_runtime_context(request),
                "prompt_metadata": self.prompt_metadata,
                "capability_scope": capability_scope,
            }
            if is_commerce_agent_config(self.agent_config or {}):
                context_dict["commerce"] = (self.agent_config or {}).get("commerce") or {}

            # Chart-first Lal Kitab runtime (mirrors the streaming path): parse
            # birth details, geocode the birthplace automatically, build the
            # chart first, then call only the relevant secondary endpoints.
            agent_result = None
            lalkitab_pending: dict[str, Any] = {}
            lalkitab_plan = SimpleNamespace(handled=False, api_context=None)
            if not turn_plan.tool_plan:
                lalkitab_pending = (
                    await self._load_lalkitab_pending_state(conversation_id)
                    if short_term_enabled else {}
                )
                lalkitab_pending = {
                    **lalkitab_pending,
                    **self._lalkitab_pending_from_policy(policy_state, turn_plan),
                }
                lalkitab_plan = await build_lalkitab_runtime_context(
                    self.agent_config or {},
                    runtime_message,
                    pending_state=lalkitab_pending,
                    birth_profile=lalkitab_profile,
                )

            if lalkitab_plan.handled and (
                getattr(lalkitab_plan, "awaiting_place_choice", False) or lalkitab_plan.missing_input
            ):
                clarification, clarification_metadata = self._apply_post_response_guardrails(
                    lalkitab_plan.clarification,
                    {
                        "lalkitab_runtime": True,
                        "validation_passed": True,
                        "validation_confidence": 1.0,
                    },
                )
                if short_term_enabled:
                    await self.short_term.add_message(
                        conversation_id=conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=clarification,
                        metadata={
                            "user_id": user_id,
                            "lalkitab_pending": lalkitab_plan.pending_state,
                            "evidence_validation": clarification_metadata.get("evidence_validation"),
                        },
                    )
                self.strapi.sync_conversation(
                    conversation_id=conversation_id,
                    user_message=request.message,
                    assistant_message=clarification,
                    brand_slug=self.brand_id,
                    agent_id=agent_id,
                )
                duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                return MessageResponse(
                    message=clarification,
                    conversation_id=conversation_id,
                    citations=[],
                    context_used=0,
                    confidence_score=1.0,
                    processing_time_ms=duration_ms,
                )

            if lalkitab_plan.handled:
                cached_rag_context = (
                    lalkitab_pending.get("rag_context")
                    if isinstance(lalkitab_pending.get("rag_context"), dict)
                    else {}
                )
                if getattr(lalkitab_plan, "used_cached_context", False) and cached_rag_context:
                    rag_context, rag_tool_result = cached_rag_context, None
                else:
                    rag_context, rag_tool_result = await self._retrieve_lalkitab_rag_context(runtime_message, request)
                agent_result = await self._generate_lalkitab_agent_result(
                    message=runtime_message,
                    chat_history=chat_history,
                    lalkitab_plan=lalkitab_plan,
                    rag_context=rag_context,
                    rag_tool_result=rag_tool_result,
                    birth_profile=lalkitab_profile,
                )

            # 4. RUN SOTA ORCHESTRATOR LOOP
            # Instead of linear retrieve->generate, let the agent plan and execute.
            from agent_runtime.orchestrator_shopify import ShopifyOrchestrator

            if agent_result is not None:
                pass
            elif turn_plan.tool_plan:
                planner_tool_results, _ = await self._execute_planner_tool_plan(
                    turn_plan=turn_plan,
                    message=runtime_message,
                    conversation_id=conversation_id,
                )
                agent_result = await self._generate_planner_agent_result(
                    message=runtime_message,
                    chat_history=chat_history,
                    turn_plan=turn_plan,
                    tool_results=planner_tool_results,
                )
            elif isinstance(self.orchestrator, ShopifyOrchestrator):
                agent_result = await self.orchestrator.run(
                    query=runtime_message,
                    chat_history=chat_history,
                    context=context_dict
                )
            else:
                agent_result = await self.orchestrator.run(
                    query=runtime_message,
                    chat_history=chat_history,
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

            tool_results = agent_metadata.get("tool_results", {})
            retrieval_health = _response_retrieval_health(tool_results, agent_metadata)
            cart_state = _safe_commerce_cart(
                agent_metadata,
                tool_results,
                {"cart_id": saved_cart_id} if saved_cart_id else None,
                ((self.agent_config or {}).get("shopify") or {}).get("shop_url") or (self.agent_config or {}).get("shopify_shop_url"),
            )
            if cart_state and cart_state.get("cart_id"):
                saved_cart_id = cart_state["cart_id"]
            citations, safe_products, safe_dealers = _extract_tool_result_metadata(tool_results)
            is_commerce_agent = is_commerce_agent_config(self.agent_config or {})
            if is_commerce_agent:
                citations = []
                safe_products = _prepare_commerce_products_for_response(safe_products, self.agent_config or {})
            unique_products = _deduplicate_entities(
                safe_products,
                "product_group_id",
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
            response_metadata = {
                "commerce_intent": _sanitize_for_json(agent_metadata.get("commerce_intent") or agent_metadata.get("last_constraints") or {}),
                "active_product_focus": _sanitize_for_json(
                    _normalize_commerce_products_currency(
                        agent_metadata.get("active_product_focus") or [],
                        self.agent_config or {},
                    )
                ),
                "product_reference_map": _sanitize_for_json(agent_metadata.get("product_reference_map") or {}),
                "original_query": agent_metadata.get("original_query") or agent_metadata.get("last_user_query"),
                "search_query": agent_metadata.get("search_query") or agent_metadata.get("last_search_query"),
                "rerank_results": _sanitize_for_json(agent_metadata.get("rerank_results") or []),
                "resolved_reference": _sanitize_for_json(agent_metadata.get("resolved_reference") or {}),
                "cart": _sanitize_for_json(cart_state) if cart_state else None,
            } if is_commerce_agent or unique_products or unique_dealers or cart_state else None
            if retrieval_health:
                response_metadata = {
                    **(response_metadata or {}),
                    "retrieval": retrieval_health,
                }
            if agent_metadata.get("kundali_chart"):
                response_metadata = {
                    **(response_metadata or {}),
                    "kundali_chart": _sanitize_for_json(agent_metadata["kundali_chart"]),
                }
            strapi_assistant_metadata = {
                "products": unique_products,
                "dealers": unique_dealers,
                "metadata": response_metadata or {},
            } if response_metadata is not None or unique_products or unique_dealers else None

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
                        "evidence_validation": agent_metadata.get("evidence_validation"),
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
                        "checkout_url": cart_state.get("checkout_url") if cart_state else None,
                        "cart_lines": cart_state.get("cart_lines") if cart_state else [],
                        "products": unique_products,
                        "dealers": unique_dealers,
                        "response_metadata": response_metadata or {},
                        "captured_ids": agent_metadata.get("captured_ids"),
                        "last_searched": agent_metadata.get("last_searched"),
                        "active_product_focus": agent_metadata.get("active_product_focus"),
                        "product_reference_map": agent_metadata.get("product_reference_map"),
                        "last_user_query": agent_metadata.get("last_user_query"),
                        "last_search_query": agent_metadata.get("last_search_query"),
                        "last_constraints": agent_metadata.get("last_constraints"),
                        "rerank_results": agent_metadata.get("rerank_results"),
                        "resolved_reference": agent_metadata.get("resolved_reference"),
                        "resolved_inputs": _sanitize_for_json(turn_plan.resolved_inputs),
                        "pending_inputs": turn_plan.pending_inputs,
                        "context_decision": turn_plan.context_decision,
                        "cached_evidence": _sanitize_for_json({
                            "api_context": agent_metadata.get("lalkitab_api_context_full"),
                            "rag_context": agent_metadata.get("lalkitab_rag_context_full"),
                        }) if agent_metadata.get("lalkitab_runtime") else None,
                        "lalkitab_api_context": agent_metadata.get("lalkitab_api_context_full"),
                        "lalkitab_rag_context": agent_metadata.get("lalkitab_rag_context_full"),
                        "connector_inputs": self._collect_connector_inputs(session_state, lalkitab_plan, agent_metadata) or None,
                    }
                )

            self.strapi.sync_conversation(
                conversation_id=conversation_id,
                user_message=request.message,
                assistant_message=response_text,
                brand_slug=self.brand_id,
                agent_id=agent_id,
                assistant_metadata=strapi_assistant_metadata,
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
                products=unique_products,
                dealers=unique_dealers,
                metadata=response_metadata,
                commerce={"cart": cart_state} if cart_state else None,
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
            long_term_enabled = await self._long_term_memory_consent_granted(
                conversation_id=conversation_id,
                user_id=user_id,
                agent_id=agent_id,
            )
            self._bind_request_page_context_to_retrieval(request)

            escalations = []
            if self.memory_config.ENABLE_GRAPH_RULES and self.graph:
                escalations = await self.graph.check_escalation(request.message)

            guardrail_decision = self._evaluate_pre_response_guardrails(request.message, escalations)
            if guardrail_decision["action"] in {"block", "escalate"}:
                response_text, guardrail_response_metadata = self._apply_post_response_guardrails(
                    guardrail_decision["message"],
                    {
                        "validation_confidence": 1.0,
                        "validation_passed": False,
                        "guardrail_action": guardrail_decision["action"],
                        "guardrail_reason": guardrail_decision["reason"],
                        "_trusted_safety_template": True,
                    },
                )
                if short_term_enabled:
                    await self.short_term.add_message(
                        conversation_id=conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=response_text,
                        metadata={
                            "user_id": user_id,
                            "guardrail_action": guardrail_response_metadata.get("guardrail_action"),
                            "guardrail_reason": guardrail_response_metadata.get("guardrail_reason"),
                            "capability_scope": guardrail_decision.get("capability_scope"),
                            "validation_passed": guardrail_response_metadata.get("validation_passed"),
                            "evidence_validation": guardrail_response_metadata.get("evidence_validation"),
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

            conversation_policy = normalize_conversation_policy(self.agent_config or {})
            policy_state = (
                await self._load_conversation_policy_state(conversation_id)
                if short_term_enabled else {}
            )
            fallback_turn_plan = plan_conversation_turn(
                message=runtime_message,
                policy=conversation_policy,
                previous_state=policy_state,
            )
            planner_provider = await self._planner_llm_provider(conversation_policy)
            turn_plan = await AgentTurnPlanner(planner_provider).plan(
                message=runtime_message,
                policy=conversation_policy,
                previous_state=policy_state,
                tool_schemas=self._tool_schemas_for_planner(),
                system_prompt=self.system_prompt or "",
                fallback_plan=fallback_turn_plan,
            )
            turn_plan, lalkitab_profile = await self._prepare_lalkitab_turn(
                turn_plan, runtime_message, policy_state, llm_provider=planner_provider
            )
            for activity in turn_plan.activities:
                if activity.get("visibility") != "hidden":
                    yield StreamingMessageResponse(**activity_stream_response_kwargs(activity, conversation_id))

            if turn_plan.should_short_circuit:
                short_circuit_metadata = {
                    "resolved_inputs": _sanitize_for_json(turn_plan.resolved_inputs),
                    "pending_inputs": turn_plan.pending_inputs,
                    "context_decision": turn_plan.context_decision,
                    "validation_passed": True,
                    "validation_confidence": 1.0,
                }
                response_text, short_circuit_metadata = self._apply_post_response_guardrails(
                    turn_plan.response_text,
                    short_circuit_metadata,
                )
                yield StreamingMessageResponse(
                    type="content",
                    content=response_text,
                    conversation_id=conversation_id,
                )
                yield StreamingMessageResponse(
                    type="final_answer",
                    content=response_text,
                    conversation_id=conversation_id,
                    metadata={
                        "resolved_inputs": _sanitize_for_json(turn_plan.resolved_inputs),
                        "pending_inputs": turn_plan.pending_inputs,
                        "context_decision": turn_plan.context_decision,
                    },
                )
                if short_term_enabled:
                    await self.short_term.add_message(
                        conversation_id=conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=response_text,
                        metadata={
                            "user_id": user_id,
                            "resolved_inputs": _sanitize_for_json(turn_plan.resolved_inputs),
                            "pending_inputs": turn_plan.pending_inputs,
                            "context_decision": turn_plan.context_decision,
                            "validation_passed": short_circuit_metadata.get("validation_passed"),
                            "evidence_validation": short_circuit_metadata.get("evidence_validation"),
                        },
                    )
                self.strapi.sync_conversation(
                    conversation_id=conversation_id,
                    user_message=request.message,
                    assistant_message=response_text,
                    brand_slug=self.brand_id,
                    agent_id=agent_id,
                )
                yield StreamingMessageResponse(
                    type="metadata",
                    content="",
                    conversation_id=conversation_id,
                    context_used=0,
                    confidence_score=min(
                        1.0,
                        max(0.0, float(short_circuit_metadata.get("validation_confidence", 1.0))),
                    ),
                    metadata={
                        "resolved_inputs": _sanitize_for_json(turn_plan.resolved_inputs),
                        "pending_inputs": turn_plan.pending_inputs,
                        "context_decision": turn_plan.context_decision,
                    },
                )
                yield StreamingMessageResponse(
                    type="done",
                    content="Run complete.",
                    conversation_id=conversation_id,
                    metadata={
                        "latency_ms": int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                        "context_used": 0,
                    },
                )
                return

            # Phase 6: Use SOTA Orchestrator for Planning, Execution, and Critic loop.
            # Do not emit generic context events here. Public widget traffic often
            # starts with greetings, and timeline events should represent actual
            # retrieval/tool work rather than configuration loading.
            agent_result = None
            lalkitab_pending: dict[str, Any] = {}
            lalkitab_plan = SimpleNamespace(handled=False, api_context=None)

            if not turn_plan.tool_plan:
                lalkitab_pending = (
                    await self._load_lalkitab_pending_state(conversation_id)
                    if short_term_enabled else {}
                )
                lalkitab_pending = {
                    **lalkitab_pending,
                    **self._lalkitab_pending_from_policy(policy_state, turn_plan),
                }
                lalkitab_plan = await build_lalkitab_runtime_context(
                    self.agent_config or {},
                    runtime_message,
                    pending_state=lalkitab_pending,
                    birth_profile=lalkitab_profile,
                )

            # Surface real runtime activity (geocoding, connector calls) as it happens.
            if agent_result is None and lalkitab_plan.handled:
                for event in lalkitab_plan.events:
                    yield StreamingMessageResponse(
                        type=event.get("type") or "status",
                        content=event.get("content") or "",
                        conversation_id=conversation_id,
                        metadata=event.get("metadata") or {},
                    )

            # Birthplace disambiguation: pause and ask the user to pick a place.
            if agent_result is None and lalkitab_plan.handled and lalkitab_plan.awaiting_place_choice:
                clarification, clarification_metadata = self._apply_post_response_guardrails(
                    lalkitab_plan.clarification,
                    {
                        "lalkitab_runtime": True,
                        "validation_passed": True,
                        "validation_confidence": 1.0,
                    },
                )
                disambiguation_metadata = {
                    "connector_id": "vedika_lal_kitab",
                    "connector_name": "Vedika Lal Kitab",
                    "endpoint_id": "geocode_search",
                    "endpoint_name": "Vedika Geocode Search",
                    "candidates": _public_lalkitab_place_candidates(
                        lalkitab_plan.place_candidates
                    ),
                }
                yield StreamingMessageResponse(
                    type="place_disambiguation",
                    content=clarification,
                    conversation_id=conversation_id,
                    metadata=disambiguation_metadata,
                )
                yield StreamingMessageResponse(type="content", content=clarification, conversation_id=conversation_id)
                if short_term_enabled:
                    await self.short_term.add_message(
                        conversation_id=conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=clarification,
                        metadata={
                            "user_id": user_id,
                            "lalkitab_pending": lalkitab_plan.pending_state,
                            "evidence_validation": clarification_metadata.get("evidence_validation"),
                        },
                    )
                yield StreamingMessageResponse(
                    type="done",
                    content="Awaiting birthplace selection.",
                    conversation_id=conversation_id,
                    metadata={"awaiting_place_choice": True},
                )
                return

            if agent_result is None and lalkitab_plan.handled and lalkitab_plan.missing_input:
                clarification, clarification_metadata = self._apply_post_response_guardrails(
                    lalkitab_plan.clarification,
                    {
                        "lalkitab_runtime": True,
                        "validation_passed": True,
                        "validation_confidence": 1.0,
                    },
                )
                missing_metadata = {
                    "connector_id": "vedika_lal_kitab",
                    "connector_name": "Vedika Lal Kitab",
                    "endpoint_id": "lalkitab_chart",
                    "endpoint_name": "Lal Kitab Chart",
                    "missing_input": _public_lalkitab_missing_fields(
                        lalkitab_plan.missing_input
                    ),
                }
                yield StreamingMessageResponse(
                    type="missing_input",
                    content=clarification,
                    conversation_id=conversation_id,
                    metadata=missing_metadata,
                )
                yield StreamingMessageResponse(type="content", content=clarification, conversation_id=conversation_id)
                if short_term_enabled:
                    await self.short_term.add_message(
                        conversation_id=conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=clarification,
                        metadata={
                            "user_id": user_id,
                            "lalkitab_pending": lalkitab_plan.pending_state,
                            "evidence_validation": clarification_metadata.get("evidence_validation"),
                        },
                    )
                yield StreamingMessageResponse(
                    type="done",
                    content="Missing Lal Kitab input required.",
                    conversation_id=conversation_id,
                    metadata={"missing_input": missing_metadata},
                )
                return

            connector_preflight = [] if turn_plan.tool_plan or lalkitab_plan.handled else self._connector_missing_inputs_for_message(runtime_message)
            if connector_preflight:
                first_missing = connector_preflight[0]
                clarification, _ = self._apply_post_response_guardrails(
                    (
                        "I need a little more information before I can call the configured source: "
                        f"{', '.join(first_missing.get('missing_input') or [])}."
                    ),
                    {"validation_passed": True, "validation_confidence": 1.0},
                )
                yield StreamingMessageResponse(
                    type="missing_input",
                    content=(
                        f"{first_missing.get('endpoint_name') or 'Connector'} needs: "
                        f"{', '.join(first_missing.get('missing_input') or [])}."
                    ),
                    conversation_id=conversation_id,
                    metadata=first_missing,
                )
                yield StreamingMessageResponse(type="content", content=clarification, conversation_id=conversation_id)
                yield StreamingMessageResponse(
                    type="done",
                    content="Missing input required.",
                    conversation_id=conversation_id,
                    metadata={"missing_input": first_missing},
                )
                return

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

            planner_tool_results: dict[str, ToolResult] = {}
            if turn_plan.tool_plan:
                planner_tool_results, planner_events = await self._execute_planner_tool_plan(
                    turn_plan=turn_plan,
                    message=runtime_message,
                    conversation_id=conversation_id,
                )
                for event in planner_events:
                    yield event

            prompt_context = {
                "session_state": session_state,
                "prompt_runtime": self._build_prompt_runtime_context(request),
                "prompt_metadata": self.prompt_metadata,
                "capability_scope": capability_scope,
            }
            if is_commerce_agent_config(self.agent_config or {}):
                prompt_context["commerce"] = (self.agent_config or {}).get("commerce") or {}
            if lalkitab_plan.handled and lalkitab_plan.api_context:
                prompt_context["prompt_runtime"]["calculated_api_context"] = {
                    "normalized_birth_input": lalkitab_plan.api_context.get("normalized_birth_input"),
                    "chart_available": bool(lalkitab_plan.api_context.get("chart_context")),
                    "secondary_endpoint_ids": sorted((lalkitab_plan.api_context.get("secondary_endpoint_results") or {}).keys()),
                    "source_provenance": lalkitab_plan.api_context.get("source_provenance") or [],
                }

            from agent_runtime.orchestrator_shopify import ShopifyOrchestrator

            if turn_plan.tool_plan:
                agent_result = await self._generate_planner_agent_result(
                    message=runtime_message,
                    chat_history=chat_history,
                    turn_plan=turn_plan,
                    tool_results=planner_tool_results,
                )
            elif lalkitab_plan.handled:
                cached_rag_context = (
                    lalkitab_pending.get("rag_context")
                    if isinstance(lalkitab_pending.get("rag_context"), dict)
                    else {}
                )
                if getattr(lalkitab_plan, "used_cached_context", False) and cached_rag_context:
                    rag_context = cached_rag_context
                    rag_tool_result = ToolResult(
                        success=True,
                        data="Cached Knowledge/RAG Context:\n" + "\n\n".join(
                            f"[{index + 1}] {chunk.get('doc_id')}\n{chunk.get('content')}"
                            for index, chunk in enumerate((rag_context.get("chunks") or [])[:5])
                            if isinstance(chunk, dict)
                        ),
                        metadata={
                            "tool_id": "knowledge_search",
                            "sources": rag_context.get("sources") or [],
                            "chunks_count": len(rag_context.get("chunks") or []),
                            "confidence": rag_context.get("confidence"),
                            "rag_chunks": rag_context.get("chunks") or [],
                            "cached": True,
                        },
                    )
                else:
                    rag_context, rag_tool_result = await self._retrieve_lalkitab_rag_context(runtime_message, request)
                if rag_context and not getattr(lalkitab_plan, "used_cached_context", False):
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
                    birth_profile=lalkitab_profile,
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

            if _is_unrecoverable_generation_failure(agent_result):
                # ``safe_canned`` means every generation path failed. Do not
                # stream the canned fallback as a successful final answer:
                # clients use ``error`` as their terminal event.  Provider
                # diagnostics stay in server logs and are never sent to users.
                failure_metadata = getattr(agent_result, "metadata", None)
                if not isinstance(failure_metadata, dict):
                    failure_metadata = {}
                logger.warning(
                    "stream_generation_unrecoverable",
                    conversation_id=conversation_id,
                    fallback_stage=failure_metadata.get("fallback_stage"),
                )
                yield StreamingMessageResponse(
                    type="error",
                    content=STREAM_GENERATION_ERROR_MESSAGE,
                    conversation_id=conversation_id,
                    metadata=dict(STREAM_GENERATION_ERROR_METADATA),
                )
                return

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
            retrieval_health = _response_retrieval_health(tool_results, agent_metadata)
            is_commerce_agent = is_commerce_agent_config(self.agent_config or {})
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
                if is_commerce_agent:
                    products = _prepare_commerce_products_for_response(products, self.agent_config or {})
                dealers = [_sanitize_for_json(dealer) for dealer in (tool_metadata.get("dealers") or [])]
                sources = [] if is_commerce_agent else (tool_metadata.get("sources") or [])
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

            final_answer_metadata = {
                "context_used": len(tool_results),
                "validation_confidence": agent_metadata.get("validation_confidence"),
                "api_context": _sanitize_for_json(agent_metadata.get("api_context") or {}),
                "rag_context": _sanitize_for_json(agent_metadata.get("rag_context") or {}),
            }
            if retrieval_health:
                final_answer_metadata["retrieval"] = retrieval_health
            if agent_metadata.get("kundali_chart"):
                # Structured chart payload the widget renders as the visual
                # kundali artifact above the reading.
                final_answer_metadata["kundali_chart"] = _sanitize_for_json(agent_metadata["kundali_chart"])
            yield StreamingMessageResponse(
                type="final_answer",
                content=full_response,
                conversation_id=conversation_id,
                metadata=final_answer_metadata,
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

            cart_state = _safe_commerce_cart(
                agent_metadata,
                tool_results,
                {"cart_id": saved_cart_id} if saved_cart_id else None,
                ((self.agent_config or {}).get("shopify") or {}).get("shop_url") or (self.agent_config or {}).get("shopify_shop_url"),
            )
            if cart_state and cart_state.get("cart_id"):
                saved_cart_id = cart_state["cart_id"]

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
                        "evidence_validation": agent_metadata.get("evidence_validation"),
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
                        "checkout_url": cart_state.get("checkout_url") if cart_state else None,
                        "cart_lines": cart_state.get("cart_lines") if cart_state else [],
                        "products": _sanitize_for_json(agent_metadata.get("active_product_focus") or []),
                        "response_metadata": {
                            "cart": _sanitize_for_json(cart_state) if cart_state else None,
                            **({"retrieval": retrieval_health} if retrieval_health else {}),
                        },
                        "captured_ids": agent_metadata.get("captured_ids"),
                        "last_searched": agent_metadata.get("last_searched"),
                        "active_product_focus": agent_metadata.get("active_product_focus"),
                        "product_reference_map": agent_metadata.get("product_reference_map"),
                        "last_user_query": agent_metadata.get("last_user_query"),
                        "last_search_query": agent_metadata.get("last_search_query"),
                        "last_constraints": agent_metadata.get("last_constraints"),
                        "rerank_results": agent_metadata.get("rerank_results"),
                        "resolved_reference": agent_metadata.get("resolved_reference"),
                        "resolved_inputs": _sanitize_for_json(turn_plan.resolved_inputs),
                        "pending_inputs": turn_plan.pending_inputs,
                        "context_decision": turn_plan.context_decision,
                        "cached_evidence": _sanitize_for_json({
                            "api_context": agent_metadata.get("lalkitab_api_context_full"),
                            "rag_context": agent_metadata.get("lalkitab_rag_context_full"),
                        }) if agent_metadata.get("lalkitab_runtime") else None,
                        "lalkitab_api_context": agent_metadata.get("lalkitab_api_context_full"),
                        "lalkitab_rag_context": agent_metadata.get("lalkitab_rag_context_full"),
                        # Remembered connector inputs so follow-ups reuse them.
                        "connector_inputs": self._collect_connector_inputs(session_state, lalkitab_plan, agent_metadata) or None,
                    }
                )

            # Sync to Strapi dashboard (fire-and-forget — never blocks streaming)
            _, stream_products, stream_dealers = _extract_tool_result_metadata(tool_results)
            if is_commerce_agent_config(self.agent_config or {}):
                stream_products = _prepare_commerce_products_for_response(stream_products, self.agent_config or {})
            strapi_products = _deduplicate_entities(
                stream_products,
                "product_group_id",
                "id",
                "sku",
                "product_id",
                "variant_id",
                "name",
            )
            strapi_dealers = _deduplicate_entities(
                stream_dealers,
                "id",
                "dealer_id",
                "email",
                "phone",
                "name",
            )
            strapi_response_metadata = {
                "commerce_intent": _sanitize_for_json(agent_metadata.get("commerce_intent") or agent_metadata.get("last_constraints") or {}),
                "active_product_focus": _sanitize_for_json(
                    _normalize_commerce_products_currency(
                        agent_metadata.get("active_product_focus") or [],
                        self.agent_config or {},
                    )
                ),
                "product_reference_map": _sanitize_for_json(agent_metadata.get("product_reference_map") or {}),
                "original_query": agent_metadata.get("original_query") or agent_metadata.get("last_user_query"),
                "search_query": agent_metadata.get("search_query") or agent_metadata.get("last_search_query"),
                "rerank_results": _sanitize_for_json(agent_metadata.get("rerank_results") or []),
                "resolved_reference": _sanitize_for_json(agent_metadata.get("resolved_reference") or {}),
                "cart": _sanitize_for_json(cart_state) if cart_state else None,
            } if is_commerce_agent_config(self.agent_config or {}) or strapi_products or strapi_dealers or cart_state else None
            strapi_assistant_metadata = {
                "products": strapi_products,
                "dealers": strapi_dealers,
                "metadata": strapi_response_metadata or {},
            } if strapi_response_metadata is not None or strapi_products or strapi_dealers else None

            # Sync to Strapi dashboard (fire-and-forget — never blocks streaming)
            self.strapi.sync_conversation(
                conversation_id=conversation_id,
                user_message=request.message,
                assistant_message=full_response,
                brand_slug=self.brand_id,
                agent_id=agent_id,
                assistant_metadata=strapi_assistant_metadata,
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
            if is_commerce_agent_config(self.agent_config or {}):
                citations = []
                safe_products = _prepare_commerce_products_for_response(safe_products, self.agent_config or {})

            unique_products = _deduplicate_entities(
                safe_products,
                "product_group_id",
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

            stream_response_metadata = {
                "commerce_intent": _sanitize_for_json(agent_metadata.get("commerce_intent") or agent_metadata.get("last_constraints") or {}),
                "active_product_focus": _sanitize_for_json(
                    _normalize_commerce_products_currency(
                        agent_metadata.get("active_product_focus") or [],
                        self.agent_config or {},
                    )
                ),
                "product_reference_map": _sanitize_for_json(agent_metadata.get("product_reference_map") or {}),
                "original_query": agent_metadata.get("original_query") or agent_metadata.get("last_user_query"),
                "search_query": agent_metadata.get("search_query") or agent_metadata.get("last_search_query"),
                "rerank_results": _sanitize_for_json(agent_metadata.get("rerank_results") or []),
                "resolved_reference": _sanitize_for_json(agent_metadata.get("resolved_reference") or {}),
                "api_context": _sanitize_for_json(agent_metadata.get("api_context") or {}),
                "rag_context": _sanitize_for_json(agent_metadata.get("rag_context") or {}),
                "cart": _sanitize_for_json({
                    "cart_id": cart_state.get("cart_id") if cart_state else saved_cart_id,
                    "checkout_url": cart_state.get("checkout_url") if cart_state else None,
                    "cart_lines": cart_state.get("cart_lines") if cart_state else [],
                }),
            }
            if retrieval_health:
                stream_response_metadata["retrieval"] = retrieval_health

            yield StreamingMessageResponse(
                type="metadata",
                content="",
                conversation_id=conversation_id,
                citations=citations,
                context_used=len(tool_results),
                confidence_score=min(1.0, max(0.0, float(agent_metadata.get("validation_confidence", 1.0)))),
                products=unique_products,
                dealers=unique_dealers,
                metadata=stream_response_metadata,
                commerce={"cart": cart_state} if cart_state else None,
            )

            done_metadata = {
                "latency_ms": int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                "context_used": len(tool_results),
                "citations_count": len(citations),
            }
            if retrieval_health:
                done_metadata["retrieval"] = retrieval_health
            yield StreamingMessageResponse(
                type="done",
                content="Run complete.",
                conversation_id=conversation_id,
                metadata=done_metadata,
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
                content=STREAM_GENERATION_ERROR_MESSAGE,
                conversation_id=conversation_id,
                metadata=dict(STREAM_GENERATION_ERROR_METADATA),
            )

    async def inject_history(self, conversation_id: str, agent_id: str, messages: list) -> None:
        """Inject messages from human takeover into short-term memory so the AI
        has full context when it resumes control.

        Each entry in `messages` is a dict with 'role' ('user'|'assistant') and 'content'.
        A synthetic system-level summary is prepended so the LLM understands what happened.
        """
        if not messages:
            return
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

        except Exception as exc:
            logger.error("retrieval_context_failed", error_type=type(exc).__name__, exc_info=True)
            # Return empty context on error
            from retrieval.types import RetrievalContext
            return RetrievalContext(
                chunks=[],
                confidence=0.0,
                sources=[],
                query=request.message,
                retrieval_metadata={
                    "status": "error",
                    "reason": "retrieval_unavailable",
                    "backend_status": "unavailable",
                },
            )

    async def _build_memory_context(
        self,
        conversation_id: str,
        user_id: str,
        query: str,
        escalations: list,
        long_term_enabled: bool | None = None,
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
        if long_term_enabled is None:
            long_term_enabled = False

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
