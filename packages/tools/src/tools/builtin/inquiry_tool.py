"""
Inquiry Tool — conversational lead capture for inquiry-based (no fixed price) brands.

Declares required fields and reports which are still missing so the calling
LLM/planner can ask for them naturally. Remembers resolved fields across
conversation turns via `remembered_inputs` / `resolved_inputs` — the same
generic mechanism this codebase already uses for context connector tools
(see app/services/tool_registry.py::ContextConnectorTool).

Fields captured (fixed for all products/brands, per product spec):
  Product Name, Name, Phone, Email, City, Country, Query

Delivery is intentionally delegated to an injected callable so this tool has
no direct dependency on SMTP/webhook specifics — the caller (message_service)
wires in the real InquiryDeliveryService + InquiryService.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Optional

from tools.types import BaseTool, ToolResult

REQUIRED_FIELDS = ["product_name", "name", "phone", "email", "city", "country", "query"]

FIELD_LABELS = {
    "product_name": "Product Name",
    "name": "Name",
    "phone": "Phone",
    "email": "Email",
    "city": "City",
    "country": "Country",
    "query": "Query",
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\-\s()]{6,18}$")


def _validate_fields(payload: dict[str, Any]) -> dict[str, str]:
    """Return {field: error_message} for any present-but-invalid fields."""
    errors: dict[str, str] = {}
    email = str(payload.get("email") or "").strip()
    if email and not _EMAIL_RE.match(email):
        errors["email"] = "That email address doesn't look valid. Could you double-check it?"
    phone = str(payload.get("phone") or "").strip()
    if phone and not _PHONE_RE.match(phone):
        errors["phone"] = "That phone number doesn't look valid. Could you share it again (with country code if possible)?"
    return errors


class InquiryTool(BaseTool):
    """Collects inquiry details conversationally and submits them on confirmation."""

    name = "submit_inquiry"
    description = (
        "ONLY use this after the user has ALREADY been shown/told about a specific product and "
        "then explicitly asks to buy it, get a quotation, request pricing, place a bulk order, "
        "contact sales, or have the team reach out (e.g. 'I want a quote for this', 'send an "
        "inquiry', 'have someone call me'). Do NOT use this for browsing, searching, or asking "
        "what a product is, what it costs, or its specs — use knowledge_search / search_catalog "
        "for all of that. If the user has not yet been told about a product, look it up first. "
        "Call this with whatever contact fields the user has already provided; it reports which "
        "fields are still missing so you can ask for them naturally, one or two at a time. It "
        "never sends anything until the user has explicitly confirmed."
    )

    parameters_schema = {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "description": "Fields collected so far from the user.",
                "properties": {
                    "product_name": {"type": "string", "description": "The product the user is asking about."},
                    "name": {"type": "string", "description": "The user's full name."},
                    "phone": {"type": "string", "description": "The user's phone number."},
                    "email": {"type": "string", "description": "The user's email address."},
                    "city": {"type": "string", "description": "The user's city."},
                    "country": {"type": "string", "description": "The user's country."},
                    "query": {"type": "string", "description": "What the user needs (quantity, use case, timeline, etc.)."},
                },
            },
            "confirm": {
                "type": "boolean",
                "description": "Set to true ONLY after the user has explicitly confirmed the summary and agreed to send the inquiry.",
            },
        },
        "required": ["payload"],
    }

    def __init__(
        self,
        *,
        brand_slug: str,
        brand_id: Optional[str],
        agent_id: Optional[str],
        conversation_id: Optional[str],
        agent_config: dict[str, Any],
        submit_callback: Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]],
        remembered_inputs: Optional[dict[str, Any]] = None,
        active_product_focus: Optional[dict[str, Any]] = None,
    ):
        """
        submit_callback(inquiry_payload, agent_config) -> dict with keys
        {success: bool, inquiry_id: str, delivered: bool, error: str|None}.
        Actual persistence + email sending happens in message_service via
        inquiry_service.save_inquiry + inquiry_delivery_service.send.
        """
        self.brand_slug = brand_slug
        self.brand_id = brand_id
        self.agent_id = agent_id
        self.conversation_id = conversation_id
        self.agent_config = agent_config or {}
        self.submit_callback = submit_callback
        # Conversation-remembered field values (multi-turn resume), read by
        # message_service the same way it does for ContextConnectorTool instances.
        self.remembered_inputs = {k: v for k, v in (remembered_inputs or {}).items() if v not in (None, "")}
        # Auto-attach the product currently being discussed, if the caller has it,
        # so the user doesn't have to repeat the product name.
        self.active_product_focus = active_product_focus or {}

    def _merged_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(self.remembered_inputs)
        merged.update({k: v for k, v in (payload or {}).items() if v not in (None, "")})
        if not merged.get("product_name"):
            focus_name = self.active_product_focus.get("name") or self.active_product_focus.get("title")
            if focus_name:
                merged["product_name"] = focus_name
        return merged

    async def run(self, payload: Optional[dict[str, Any]] = None, confirm: bool = False, **kwargs) -> ToolResult:
        merged = self._merged_payload(payload or {})

        missing = [field for field in REQUIRED_FIELDS if not str(merged.get(field) or "").strip()]
        if missing:
            missing_labels = [FIELD_LABELS[field] for field in missing]
            return ToolResult(
                success=False,
                data=None,
                error=f"Missing required fields: {', '.join(missing_labels)}",
                metadata={
                    "tool_id": "submit_inquiry",
                    "missing_input": missing,
                    # Persist whatever we already have so the next turn doesn't
                    # need to re-ask for fields the user already provided.
                    "resolved_inputs": {k: v for k, v in merged.items() if k in REQUIRED_FIELDS and v},
                },
            )

        field_errors = _validate_fields(merged)
        if field_errors:
            return ToolResult(
                success=False,
                data=None,
                error="; ".join(field_errors.values()),
                metadata={
                    "tool_id": "submit_inquiry",
                    "invalid_fields": list(field_errors.keys()),
                    "resolved_inputs": {k: v for k, v in merged.items() if k in REQUIRED_FIELDS and v},
                },
            )

        inquiry_config = self.agent_config.get("inquiry") or {}
        confirm_required = inquiry_config.get("confirm_before_send", True) is not False

        if confirm_required and not confirm:
            summary = {label: merged.get(field) for field, label in FIELD_LABELS.items()}
            return ToolResult(
                success=True,
                data="AWAITING_CONFIRMATION",
                metadata={
                    "tool_id": "submit_inquiry",
                    "awaiting_confirmation": True,
                    "summary": summary,
                    "resolved_inputs": {k: v for k, v in merged.items() if k in REQUIRED_FIELDS and v},
                },
            )

        try:
            result = await self.submit_callback(merged, self.agent_config)
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to submit the inquiry: {exc}",
                metadata={"tool_id": "submit_inquiry"},
            )

        if not result.get("success"):
            # Inquiry is still persisted even if delivery failed (see
            # inquiry_service.save_inquiry / mark_failed in message_service).
            return ToolResult(
                success=False,
                data=(
                    "I saved your inquiry, but I couldn't notify the team automatically "
                    "just now. Please also try reaching out directly, and we'll make sure "
                    "someone follows up."
                ),
                error=result.get("error") or "delivery_failed",
                metadata={
                    "tool_id": "submit_inquiry",
                    "inquiry_id": result.get("inquiry_id"),
                    "delivered": False,
                    "resolved_inputs": {k: v for k, v in merged.items() if k in REQUIRED_FIELDS and v},
                },
            )

        success_message = inquiry_config.get("success_message") or (
            "Your inquiry has been sent to our team. They'll reach out to you shortly."
        )
        return ToolResult(
            success=True,
            data=success_message,
            metadata={
                "tool_id": "submit_inquiry",
                "inquiry_id": result.get("inquiry_id"),
                "delivered": True,
                "inquiry_submitted": True,
                "resolved_inputs": {k: v for k, v in merged.items() if k in REQUIRED_FIELDS and v},
            },
        )
