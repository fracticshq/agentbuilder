"""
Open Inquiry Form Tool — LLM-callable trigger for the in-widget lead-capture
form (V2 inquiry flow).

This tool does NOT collect contact fields (name/phone/email/etc.) and does NOT
persist anything. It only signals intent: "the user wants pricing/a quote/to
talk to a human/bulk pricing — open the form". All PII collection and
persistence happens entirely on the frontend (InquiryFormModal) and the
dedicated POST /api/v1/inquiry/submit endpoint, so this tool never sees PII
and never touches the LLM writer with contact details.

Only registered for agents with configuration.inquiry.enabled == true (see
message_service.py::_register_configured_capabilities). If that flag is off,
this tool does not exist in the agent's tool registry and the LLM has no way
to call it — the inquiry feature is fully inert for that agent.
"""

from __future__ import annotations

from typing import Any

from tools.types import BaseTool, ToolResult


class OpenInquiryFormTool(BaseTool):
    """Signals the widget to open the inline inquiry/lead-capture form."""

    name = "open_inquiry_form"

    description = (
        "Call this tool ONLY when the user's message shows clear intent to be "
        "contacted, get pricing, or move toward a purchase — NOT for ordinary "
        "product questions, browsing, comparisons, or specs.\n\n"
        "CALL THIS TOOL when the user says things equivalent in meaning to:\n"
        "- \"request a quote\", \"send inquiry\", \"send an inquiry for this\"\n"
        "- \"I want to buy this\", \"I want to purchase\", \"place an order\"\n"
        "- \"can someone call me\", \"contact me\", \"contact sales\", \"talk to a human\", "
        "\"talk to support\", \"connect me with your team\", \"speak to an agent\"\n"
        "- \"I need bulk pricing\", \"what's the pricing for 50 units\", \"wholesale pricing\", "
        "\"price breakdown\", \"custom quote\"\n"
        "- the user clicked a \"Request a Quote\" / \"Send Inquiry\" button (message will "
        "read like \"Request a quote for <product>\")\n\n"
        "DO NOT call this tool when the user is:\n"
        "- Asking what a product is, its price, specs, availability, or comparing products "
        "(use knowledge_search / search_catalog / search_shop_catalog for that — retrieval "
        "and MCP/commerce tools must run normally for all product search and Q&A)\n"
        "- Asking a general question, greeting, or making small talk\n"
        "- Already mid-way through filling out the inquiry form (the widget owns that state; "
        "do not call this tool again for the same request)\n"
        "- Trying to cancel/skip an inquiry (\"never mind\", \"cancel that\", \"skip this\") — "
        "just acknowledge in a normal reply, do not call this tool\n\n"
        "Behavior: this tool takes no contact fields (no name/phone/email) — it only opens "
        "the form. The user fills in their own details directly in the widget form, never "
        "through you. Pass product_name/product_sku ONLY if the user's CURRENT message "
        "itself names or clearly identifies a specific product — do NOT carry forward a "
        "product name from an earlier turn just because it was discussed before. A new, "
        "product-less request (e.g. \"bulk order of 50\", \"talk to a human\", \"contact "
        "sales\") that does not itself name a product must open the form generically (omit "
        "product_name/product_sku); the form will ask the user which product if needed. "
        "After calling this tool, your reply should be a short one-line acknowledgement "
        "(e.g. \"Opening the quote form for you — please fill in your details.\") and "
        "nothing else — do not ask for name/phone/email yourself."
    )

    parameters_schema = {
        "type": "object",
        "properties": {
            "product_name": {
                "type": "string",
                "description": (
                    "The product name, ONLY if the user's CURRENT message itself names or "
                    "clearly identifies a specific product (e.g. they typed a product name, "
                    "clicked a product's quote button, or their message is a direct reply to "
                    "'which product?' naming one). Do NOT reuse a product name from earlier in "
                    "the conversation just because it was discussed before — a new inquiry "
                    "message (bulk order, contact request, pricing request, etc.) that does not "
                    "itself mention a product is a fresh, product-less inquiry. Leave this "
                    "field empty in that case; the form will open generically and ask the user "
                    "for the product."
                ),
            },
            "product_sku": {
                "type": "string",
                "description": "The SKU/product code, only if the CURRENT message provides or clearly identifies one (leave empty otherwise — do not reuse one from earlier turns).",
            },
            "reason": {
                "type": "string",
                "description": "Short internal note on why the form is being opened (e.g. 'quote_request', 'bulk_pricing', 'human_contact'). Not shown to the user.",
            },
        },
        "required": [],
    }

    async def run(
        self,
        product_name: str = "",
        product_sku: str = "",
        reason: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        # Accept either calling shape: top-level args (per this tool's own
        # parameters_schema) or nested under "payload" (the shape most other
        # tools in this registry use) — the planner LLM occasionally mirrors
        # whichever shape it saw most recently in the tool list.
        payload = kwargs.get("payload") if isinstance(kwargs.get("payload"), dict) else {}
        product_name = str(product_name or payload.get("product_name") or "").strip()
        product_sku = str(product_sku or payload.get("product_sku") or "").strip()
        reason = str(reason or payload.get("reason") or "").strip()
        return ToolResult(
            success=True,
            data={
                "open_inquiry_form": True,
                "product_name": product_name,
                "product_sku": product_sku,
                "reason": reason,
            },
            metadata={
                "tool_id": "open_inquiry_form",
                "open_inquiry_form": True,
                "product_name": product_name,
                "product_sku": product_sku,
                "reason": reason,
            },
        )
