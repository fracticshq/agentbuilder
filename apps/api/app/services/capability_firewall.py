"""
Capability firewall for agent scope control.

This is intentionally deterministic: it keeps unrelated work out of the
orchestrator prompt path without adding another LLM call in front of every
message. The contract is derived from explicit agent/brand configuration;
vertical vocabulary is opt-in rather than inherited by every agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


DEFAULT_ALLOWED_TERMS = {
    "accessory",
    "accessories",
    "availability",
    "available",
    "catalog",
    "catalogue",
    "color",
    "colour",
    "dealer",
    "dealers",
    "finish",
    "installation",
    "policy",
    "price",
    "product",
    "products",
    "showroom",
    "sku",
    "store",
    "support",
    "warranty",
}

VERTICAL_ALLOWED_TERMS = {
    "bathware": {
        "basin",
        "bath",
        "bathroom",
        "bathware",
        "bidet",
        "cistern",
        "commode",
        "diverter",
        "faucet",
        "faucets",
        "flush",
        "hook",
        "mixer",
        "robe",
        "sanitary",
        "sanitaryware",
        "shower",
        "showers",
        "sink",
        "soap",
        "spout",
        "tap",
        "toilet",
        "towel",
        "tumbler",
        "urinal",
    },
}

BLOCKED_CAPABILITY_TERMS = {
    "finance_crypto": {
        "bitcoin",
        "btc",
        "crypto",
        "cryptocurrency",
        "ethereum",
        "market price",
        "share price",
        "stock",
        "stock price",
    },
    "food_nutrition": {
        "breakfast",
        "diet",
        "dinner",
        "food",
        "lunch",
        "meal",
        "nutrition",
        "protein",
        "restaurant",
        "snack",
        "supplement",
        "supplements",
    },
    "news_weather": {
        "election",
        "latest news",
        "news",
        "rain",
        "temperature",
        "weather",
    },
}

CONTEXTUAL_FOLLOWUP_PATTERNS = [
    re.compile(r"^\s*(?:yes|no|ok|okay|sure|thanks?|show more|tell me more)\s*[.!?]*$", re.IGNORECASE),
    re.compile(r"\b(?:compare|which one|which is best|more details|how much|is it available)\b", re.IGNORECASE),
]

CLAUSE_SPLIT_RE = re.compile(
    r"[.;!?]+|,\s+|\b(?:but|also|then|because|so)\b",
    re.IGNORECASE,
)
MIXED_SPLIT_RE = re.compile(r"\b(?:and|before|after|while|then|so)\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z][a-z0-9-]{2,}", re.IGNORECASE)


def configured_verticals(agent_config: dict[str, Any] | None) -> set[str]:
    """Read auditable opt-in vertical profiles from ``domain.verticals`` only.

    Do not infer profiles from an agent name, brand slug, prompt, or free-form
    description. Those sources are mutable prose and would make one tenant's
    historical bathware vocabulary silently affect another vertical.
    """
    config = agent_config if isinstance(agent_config, dict) else {}
    domain = config.get("domain") if isinstance(config.get("domain"), dict) else {}
    raw_verticals = domain.get("verticals")
    if isinstance(raw_verticals, str):
        raw_verticals = [raw_verticals]
    if not isinstance(raw_verticals, list):
        return set()
    return {
        str(vertical).strip().lower()
        for vertical in raw_verticals
        if str(vertical).strip().lower() in VERTICAL_ALLOWED_TERMS
    }


@dataclass(frozen=True)
class CapabilityContract:
    brand_slug: str
    brand_name: str = ""
    agent_name: str = ""
    allowed_terms: set[str] = field(default_factory=set)
    allowed_external_capabilities: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class WorkUnit:
    text: str
    status: str
    capability: str
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "text": self.text,
            "status": self.status,
            "capability": self.capability,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CapabilityDecision:
    action: str
    reason: str
    safe_query: str
    message: str
    work_units: list[WorkUnit]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "safe_query": self.safe_query,
            "blocked_units": [
                unit.to_dict() for unit in self.work_units if unit.status == "blocked"
            ],
            "allowed_units": [
                unit.to_dict() for unit in self.work_units if unit.status == "allowed"
            ],
        }


class CapabilityFirewall:
    """Classify messages into in-scope and out-of-scope work units."""

    def build_contract(
        self,
        *,
        brand_slug: str,
        agent_config: dict[str, Any] | None = None,
        agent_record: dict[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> CapabilityContract:
        agent_config = agent_config or {}
        agent_record = agent_record or {}
        brand_name = (
            agent_record.get("brand_name")
            or agent_config.get("brand_name")
            or str(brand_slug or "").replace("-", " ").title()
        )
        agent_name = agent_record.get("name") or agent_config.get("name") or ""

        contract_text = " ".join(
            str(value or "")
            for value in [
                brand_slug,
                brand_name,
                agent_name,
                agent_config.get("business_type"),
                agent_config.get("description"),
                agent_config.get("purpose"),
                system_prompt,
            ]
        ).lower()

        verticals = configured_verticals(agent_config)
        vertical_terms = set().union(*VERTICAL_ALLOWED_TERMS.values())
        allowed_terms = set(DEFAULT_ALLOWED_TERMS)
        for vertical in verticals:
            allowed_terms.update(VERTICAL_ALLOWED_TERMS.get(vertical, set()))
        identity_terms = set()
        identity_terms.update(self._extract_contract_terms(brand_slug))
        identity_terms.update(self._extract_contract_terms(brand_name))
        identity_terms.update(self._extract_contract_terms(agent_name))
        # Identity prose is useful for brand-local signals, but it must not
        # silently activate a vertical profile just because a name mentions a
        # plumbing/bathware term.
        if not verticals:
            identity_terms.difference_update(vertical_terms)
        allowed_terms.update(identity_terms)

        allowed_external_capabilities: set[str] = set()
        for capability, terms in BLOCKED_CAPABILITY_TERMS.items():
            if self._contains_any(contract_text, terms):
                allowed_external_capabilities.add(capability)
                allowed_terms.update(terms)

        return CapabilityContract(
            brand_slug=brand_slug,
            brand_name=brand_name,
            agent_name=agent_name,
            allowed_terms=allowed_terms,
            allowed_external_capabilities=allowed_external_capabilities,
        )

    def evaluate(self, message: str, contract: CapabilityContract) -> CapabilityDecision:
        raw_message = (message or "").strip()
        if not raw_message:
            return CapabilityDecision(
                action="allow",
                reason="empty",
                safe_query=raw_message,
                message="",
                work_units=[],
            )

        fragments = self._split_fragments(raw_message, contract)
        work_units = [self._classify_fragment(fragment, contract) for fragment in fragments]
        work_units = [unit for unit in work_units if unit.text]

        blocked_units = [unit for unit in work_units if unit.status == "blocked"]
        allowed_units = [unit for unit in work_units if unit.status == "allowed"]

        if blocked_units and not allowed_units:
            return CapabilityDecision(
                action="block",
                reason="capability_scope",
                safe_query="",
                message=self._block_message(contract),
                work_units=work_units,
            )

        if blocked_units and allowed_units:
            safe_query = self._join_units(allowed_units)
            return CapabilityDecision(
                action="filter",
                reason="capability_scope",
                safe_query=safe_query,
                message=self._filter_message(blocked_units, contract),
                work_units=work_units,
            )

        return CapabilityDecision(
            action="allow",
            reason="in_scope",
            safe_query=raw_message,
            message="",
            work_units=work_units,
        )

    def _split_fragments(self, message: str, contract: CapabilityContract) -> list[str]:
        fragments: list[str] = []
        for fragment in CLAUSE_SPLIT_RE.split(message):
            fragment = fragment.strip()
            if not fragment:
                continue
            if self._has_allowed_signal(fragment, contract) and self._blocked_capability(fragment, contract):
                fragments.extend(part.strip() for part in MIXED_SPLIT_RE.split(fragment) if part.strip())
            else:
                fragments.append(fragment)
        return fragments or [message]

    def _classify_fragment(self, fragment: str, contract: CapabilityContract) -> WorkUnit:
        blocked_capability = self._blocked_capability(fragment, contract)
        has_allowed_signal = self._has_allowed_signal(fragment, contract)

        if blocked_capability:
            return WorkUnit(
                text=fragment,
                status="blocked",
                capability=blocked_capability,
                reason="not_in_agent_contract",
            )

        if has_allowed_signal:
            return WorkUnit(
                text=fragment,
                status="allowed",
                capability="brand_support",
                reason="matches_agent_contract",
            )

        if any(pattern.search(fragment) for pattern in CONTEXTUAL_FOLLOWUP_PATTERNS):
            return WorkUnit(
                text=fragment,
                status="allowed",
                capability="contextual_followup",
                reason="conversation_followup",
            )

        return WorkUnit(
            text=fragment,
            status="unknown",
            capability="unknown",
            reason="no_scope_signal",
        )

    def _blocked_capability(
        self,
        fragment: str,
        contract: CapabilityContract,
    ) -> str | None:
        normalized = fragment.lower()
        for capability, terms in BLOCKED_CAPABILITY_TERMS.items():
            if capability in contract.allowed_external_capabilities:
                continue
            if self._contains_any(normalized, terms):
                return capability
        return None

    def _has_allowed_signal(self, fragment: str, contract: CapabilityContract) -> bool:
        normalized = fragment.lower()
        return self._contains_any(normalized, contract.allowed_terms)

    def _contains_any(self, text: str, terms: set[str]) -> bool:
        for term in terms:
            normalized = str(term or "").strip().lower()
            if not normalized:
                continue
            if " " in normalized:
                if normalized in text:
                    return True
            elif re.search(rf"\b{re.escape(normalized)}s?\b", text):
                return True
        return False

    def _extract_contract_terms(self, value: str | None) -> set[str]:
        if not value:
            return set()
        return {
            token.lower()
            for token in TOKEN_RE.findall(str(value).replace("-", " "))
            if token.lower() not in {"agent", "assistant", "brand", "the", "and", "for"}
        }

    def _join_units(self, units: list[WorkUnit]) -> str:
        safe_parts = [unit.text.strip() for unit in units if unit.text.strip()]
        return ". ".join(safe_parts)

    def _block_message(self, contract: CapabilityContract) -> str:
        brand = contract.brand_name or "this brand"
        brand_hint = f" ({brand})" if brand and brand != "this brand" else ""
        return (
            f"I can only help with questions related to this brand{brand_hint}, its products, dealers, policies, "
            "and support information."
        )

    def _filter_message(self, blocked_units: list[WorkUnit], contract: CapabilityContract) -> str:
        brand = contract.brand_name or "the brand"
        blocked_labels = sorted({self._friendly_capability(unit.capability) for unit in blocked_units})
        blocked_text = ", ".join(label for label in blocked_labels if label)
        if blocked_text:
            return (
                f"I’ll stay focused on {brand}. I can help with the relevant product or support part, "
                f"but I can’t help with {blocked_text}."
            )
        return (
            f"I’ll stay focused on {brand}. I can help with the relevant product or support part."
        )

    def _friendly_capability(self, capability: str) -> str:
        return {
            "finance_crypto": "finance or crypto requests",
            "food_nutrition": "food or nutrition recommendations",
            "news_weather": "news or weather requests",
        }.get(capability, "unrelated requests")
