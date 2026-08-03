"""
Public inquiry submission endpoint.

Accepts form fields directly from the widget InquiryFormModal.
PII (name, phone, email, city, country) never touches the LLM — it goes
straight to InquiryService (MongoDB) and InquiryDeliveryService (SMTP).
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
import structlog

from ....services.inquiry_service import InquiryService
from ....services.inquiry_delivery_service import InquiryDeliveryService
from ....config import Settings
from ....connections import connection_manager

router = APIRouter()
logger = structlog.get_logger(__name__)


class InquirySubmitRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None
    product_name: Optional[str] = None
    product_sku: Optional[str] = None
    name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    city: str = Field(..., min_length=1)
    country: str = Field(..., min_length=1)
    query: Optional[str] = None


class InquirySubmitResponse(BaseModel):
    success: bool
    inquiry_id: Optional[str] = None
    message: str
    delivered: bool = False


@router.post("/submit", response_model=InquirySubmitResponse)
async def submit_inquiry(
    request: InquirySubmitRequest,
    x_widget_session: Optional[str] = Header(default=None, alias="X-Widget-Session"),
):
    """
    Submit a lead-capture inquiry from the widget form.

    The widget posts form fields directly here — no LLM processes this data.
    The endpoint persists to MongoDB and sends an email to the configured
    recipient, then returns a success flag + message for the widget to display.
    """
    settings = Settings()

    # Resolve brand context from agent_id
    try:
        system_db = connection_manager.get_system_db()
        agent = await system_db.agents.find_one({"id": request.agent_id})
        if not agent:
            return InquirySubmitResponse(
                success=False,
                message="Agent not found.",
                delivered=False,
            )
        brand_slug: str = agent.get("brand_slug") or agent.get("brand_id") or request.agent_id
        brand_id: str = agent.get("brand_id") or request.agent_id
        agent_config: dict = agent.get("configuration") or {}
    except Exception as exc:
        logger.error("inquiry_submit_agent_lookup_failed", error=str(exc))
        return InquirySubmitResponse(
            success=False,
            message="Could not resolve agent configuration.",
            delivered=False,
        )

    inquiry_svc = InquiryService()
    delivery_svc = InquiryDeliveryService(settings)

    # Persist inquiry (PII stays in brand-isolated MongoDB, never logged)
    try:
        inquiry_doc = await inquiry_svc.save_inquiry(
            brand_slug=brand_slug,
            brand_id=brand_id,
            agent_id=request.agent_id,
            conversation_id=request.conversation_id,
            contact={
                "name": request.name,
                "phone": request.phone,
                "email": request.email,
                "city": request.city,
                "country": request.country,
            },
            requirements=request.query or "",
            product_context={
                "name": request.product_name or "",
                "sku": request.product_sku or "",
            },
        )
    except Exception as exc:
        logger.error("inquiry_submit_save_failed", error=str(exc))
        return InquirySubmitResponse(
            success=False,
            message="Failed to save inquiry. Please try again.",
            delivered=False,
        )

    # Deliver via SMTP (non-blocking worker thread)
    delivery = await delivery_svc.send(inquiry_doc, agent_config)

    if delivery.success:
        await inquiry_svc.mark_delivered(
            brand_slug=brand_slug,
            inquiry_id=inquiry_doc["inquiry_id"],
            method=delivery.method,
        )
    else:
        await inquiry_svc.mark_failed(
            brand_slug=brand_slug,
            inquiry_id=inquiry_doc["inquiry_id"],
            method=delivery.method,
            error=delivery.error or "unknown",
        )

    inquiry_config = agent_config.get("inquiry") or {}
    success_message = (
        str(inquiry_config.get("success_message") or "").strip()
        or "Your inquiry has been sent successfully. Our team will reach out to you shortly."
    )

    return InquirySubmitResponse(
        success=True,
        inquiry_id=inquiry_doc["inquiry_id"],
        message=success_message,
        delivered=delivery.success,
    )
