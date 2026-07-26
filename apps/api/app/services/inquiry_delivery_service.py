"""
Inquiry Delivery Service.

Sends a captured inquiry to the brand owner. Testing uses plain SMTP email;
production can swap in a transactional provider or route to a webhook/CRM
without changing the calling code (InquiryTool / inquiry_service).

PII discipline: never log raw contact fields (name/email/phone). Log only
inquiry_id, brand, and delivery status.
"""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import structlog

from ..config import Settings

# smtplib is synchronous/blocking. Running it directly inside an `async def`
# stalls the ENTIRE asyncio event loop (every other request on this process)
# until the socket call resolves or times out. It must always run in a worker
# thread with a hard timeout, never awaited directly on the event loop.
_SMTP_TIMEOUT_SECONDS = 15

logger = structlog.get_logger(__name__)


@dataclass
class DeliveryResult:
    success: bool
    method: str
    error: str | None = None


def _format_inquiry_email_body(inquiry: dict[str, Any]) -> str:
    contact = inquiry.get("contact") or {}
    product = inquiry.get("product_context") or {}
    lines = [
        "New inquiry received via the AI assistant.",
        "",
        f"Product: {product.get('name') or 'Not specified'}"
        + (f" (SKU: {product.get('sku')})" if product.get("sku") else ""),
        "",
        "Contact details:",
        f"  Name:    {contact.get('name') or '-'}",
        f"  Phone:   {contact.get('phone') or '-'}",
        f"  Email:   {contact.get('email') or '-'}",
        f"  City:    {contact.get('city') or '-'}",
        f"  Country: {contact.get('country') or '-'}",
        "",
        "Query:",
        f"  {inquiry.get('requirements') or '-'}",
        "",
        f"Inquiry ID: {inquiry.get('inquiry_id')}",
        f"Conversation ID: {inquiry.get('conversation_id')}",
        f"Brand: {inquiry.get('brand_slug')}",
    ]
    return "\n".join(lines)


class InquiryDeliveryService:
    """Pluggable inquiry delivery. Test path: SMTP email. Extend with webhook/CRM later."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def send(self, inquiry: dict[str, Any], agent_config: dict[str, Any] | None = None) -> DeliveryResult:
        inquiry_config = (agent_config or {}).get("inquiry") or {}
        method = str(inquiry_config.get("delivery_method") or "email").lower()

        if method == "email":
            try:
                # Run the blocking smtplib call in a worker thread so a slow/
                # unreachable SMTP server cannot freeze the whole event loop.
                return await asyncio.wait_for(
                    asyncio.to_thread(self._send_email, inquiry, inquiry_config),
                    timeout=_SMTP_TIMEOUT_SECONDS + 5,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "inquiry_delivery_timed_out",
                    inquiry_id=inquiry.get("inquiry_id"),
                    method="email",
                )
                return DeliveryResult(success=False, method="email", error="Email delivery timed out.")

        # Only email is implemented for the test phase; other methods are
        # rejected explicitly rather than silently dropped.
        logger.warning("inquiry_delivery_unsupported_method", method=method, inquiry_id=inquiry.get("inquiry_id"))
        return DeliveryResult(success=False, method=method, error=f"Delivery method '{method}' is not implemented yet.")

    def _resolve_recipient(self, inquiry_config: dict[str, Any]) -> str:
        return (
            str(inquiry_config.get("recipient_email") or "").strip()
            or str(self.settings.INQUIRY_FALLBACK_RECIPIENT or "").strip()
        )

    def _send_email(self, inquiry: dict[str, Any], inquiry_config: dict[str, Any]) -> DeliveryResult:
        recipient = self._resolve_recipient(inquiry_config)
        inquiry_id = inquiry.get("inquiry_id")

        if not recipient:
            logger.warning("inquiry_delivery_no_recipient", inquiry_id=inquiry_id)
            return DeliveryResult(success=False, method="email", error="No recipient_email configured for this agent.")

        if not self.settings.SMTP_HOST or not self.settings.SMTP_USERNAME or not self.settings.SMTP_PASSWORD:
            logger.warning("inquiry_delivery_smtp_not_configured", inquiry_id=inquiry_id)
            return DeliveryResult(success=False, method="email", error="SMTP is not configured on the server.")

        product = inquiry.get("product_context") or {}
        subject = f"New Inquiry: {product.get('name') or 'Product'} — {inquiry.get('brand_slug') or ''}".strip()

        message = MIMEMultipart()
        message["From"] = self.settings.SMTP_FROM_EMAIL or self.settings.SMTP_USERNAME
        message["To"] = recipient
        message["Subject"] = subject
        message.attach(MIMEText(_format_inquiry_email_body(inquiry), "plain"))

        try:
            with smtplib.SMTP(self.settings.SMTP_HOST, self.settings.SMTP_PORT, timeout=_SMTP_TIMEOUT_SECONDS) as server:
                if self.settings.SMTP_USE_TLS:
                    server.starttls()
                server.login(self.settings.SMTP_USERNAME, self.settings.SMTP_PASSWORD)
                server.sendmail(message["From"], [recipient], message.as_string())
            logger.info("inquiry_delivered", inquiry_id=inquiry_id, method="email")
            return DeliveryResult(success=True, method="email")
        except Exception as exc:  # pragma: no cover - network/SMTP errors
            logger.error("inquiry_delivery_failed", inquiry_id=inquiry_id, method="email", error=str(exc))
            return DeliveryResult(success=False, method="email", error=str(exc))
