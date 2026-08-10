"""
Lal Kitab birth-profile endpoint — form-first flow.

A mandatory pre-chat form (name, DOB, TOB, birthplace, language) submits here.
This runs the existing chart-first runtime once (geocoding + kundali chart +
all secondary Lal Kitab endpoints), persists the result as a confirmed birth
profile scoped to this widget session's conversation, and returns the chart +
report so the widget can render a horoscope dashboard immediately.

Once confirmed, chat turns for this conversation never need to re-extract
birth details from free text — message_service.py reads the persisted
profile and feeds it straight into build_lalkitab_runtime_context() as
`birth_profile`, and (for astrology_lalkitab agents with this flow enabled)
chat is gated until a confirmed profile exists.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
import structlog

from ....auth.widget_session import decode_widget_session
from ....config import Settings
from ....connections import connection_manager
from ....services.conversation_scope_store import (
    ConversationScopeAuthorizationError,
    ConversationScopeStoreError,
    conversation_scope_store,
)
from ....services.lalkitab_runtime import (
    build_lalkitab_runtime_context,
    is_lalkitab_agent,
)
from ....services.kundali_chart import extract_kundali_chart_summary
from ....services.message_service import _sanitize_for_json
from ....services.runtime_settings_service import RuntimeSettingsService
from ....services.tool_config_secrets import decrypt_full_agent_configuration_for_runtime

router = APIRouter()
logger = structlog.get_logger(__name__)


class BirthProfileRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    birth_date: str = Field(..., min_length=1, description="YYYY-MM-DD")
    birth_time: str = Field(..., min_length=1, description="HH:MM (24h) or HH:MM AM/PM")
    birth_place: str = Field(..., min_length=1)
    language: Optional[str] = "en"


class BirthProfileResponse(BaseModel):
    success: bool
    message: str
    kundali_chart: Optional[dict[str, Any]] = None
    api_context: Optional[dict[str, Any]] = None
    awaiting_place_choice: bool = False
    place_candidates: list[dict[str, Any]] = Field(default_factory=list)


def _require_session(x_widget_session: Optional[str], agent_id: str):
    session = decode_widget_session(x_widget_session, expected_agent_id=agent_id)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail="A valid widget session token is required. Start a session at POST /messages/session.",
        )
    return session


@router.post("/profile", response_model=BirthProfileResponse)
async def submit_birth_profile(
    request: BirthProfileRequest,
    x_widget_session: Optional[str] = Header(default=None, alias="X-Widget-Session"),
):
    """Build the full Lal Kitab chart + report once and persist it as this
    conversation's confirmed birth profile."""
    session = _require_session(x_widget_session, request.agent_id)

    try:
        await conversation_scope_store.require_active_widget_scope(
            conversation_id=session.conversation_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
        )
    except ConversationScopeAuthorizationError as exc:
        raise HTTPException(status_code=401, detail="Widget session is no longer valid") from exc
    except ConversationScopeStoreError as exc:
        raise HTTPException(status_code=503, detail="Widget sessions are temporarily unavailable") from exc

    system_db = connection_manager.get_system_db()
    agent = await system_db.agents.find_one({"id": request.agent_id, "status": "active"})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found or not active")

    # Connector auth (e.g. the Vedika API key) is stored encrypted at rest
    # (auth_header_encrypted) — this must be decrypted into the plain
    # auth_header field before ContextConnectorTool can build a real
    # Authorization header, exactly like message_service.py's normal chat
    # path does when loading agent config. Skipping this was the actual bug:
    # every geocode/chart call went out with no Authorization header at all,
    # regardless of whether a real key had been saved.
    raw_config = agent.get("configuration") or {}
    config = decrypt_full_agent_configuration_for_runtime(raw_config, RuntimeSettingsService(Settings()))
    if not is_lalkitab_agent(config):
        raise HTTPException(status_code=400, detail="This agent is not configured as a Lal Kitab / astrology agent")

    birth_profile = {
        "name": request.name.strip(),
        "birth_date": request.birth_date.strip(),
        "birth_time": request.birth_time.strip(),
        "birth_place": request.birth_place.strip(),
    }

    try:
        plan = await build_lalkitab_runtime_context(
            config,
            "full reading",
            birth_profile=birth_profile,
        )
    except Exception as exc:
        logger.error("lalkitab_profile_build_failed", error=str(exc))
        raise HTTPException(status_code=502, detail="Could not build the horoscope right now. Please try again.") from exc

    if plan.awaiting_place_choice:
        return BirthProfileResponse(
            success=False,
            message=plan.clarification or "Please confirm which place you were born in.",
            awaiting_place_choice=True,
            place_candidates=plan.place_candidates or [],
        )

    if plan.missing_input:
        return BirthProfileResponse(
            success=False,
            message=plan.clarification or "Some birth details could not be understood. Please check and try again.",
        )

    if plan.requires_safe_abstention or not plan.chart_validated:
        return BirthProfileResponse(
            success=False,
            message="We could not calculate a verified chart from these details right now. Please try again shortly.",
        )

    kundali_chart = extract_kundali_chart_summary(plan.api_context)
    if kundali_chart and isinstance(kundali_chart, dict):
        kundali_chart.setdefault("birth", {})
        if isinstance(kundali_chart.get("birth"), dict):
            kundali_chart["birth"].update(
                {
                    "name": birth_profile["name"],
                    "date": birth_profile["birth_date"],
                    "time": birth_profile["birth_time"],
                    "place": birth_profile["birth_place"],
                }
            )

    # Persist as this conversation's confirmed profile. Chat turns read this
    # back so birth details never need to be typed into chat.
    try:
        await conversation_scope_store.set_birth_profile(
            conversation_id=session.conversation_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            birth_profile={
                **birth_profile,
                "language": request.language or "en",
                "api_context": _sanitize_for_json(plan.api_context),
                "kundali_chart": _sanitize_for_json(kundali_chart) if kundali_chart else None,
            },
        )
    except ConversationScopeAuthorizationError as exc:
        raise HTTPException(status_code=401, detail="Widget session is no longer valid") from exc
    except ConversationScopeStoreError as exc:
        raise HTTPException(status_code=503, detail="Could not save your birth profile right now. Please try again.") from exc

    return BirthProfileResponse(
        success=True,
        message="Your horoscope has been generated.",
        kundali_chart=_sanitize_for_json(kundali_chart) if kundali_chart else None,
        api_context=_sanitize_for_json(plan.api_context),
    )


@router.get("/profile", response_model=Optional[BirthProfileResponse])
async def get_birth_profile(
    agent_id: str,
    x_widget_session: Optional[str] = Header(default=None, alias="X-Widget-Session"),
):
    """Return the confirmed birth profile for this conversation, if one exists.

    The widget calls this on session start to decide whether to show the
    birth-details form or go straight to the dashboard + chat.
    """
    session = _require_session(x_widget_session, agent_id)

    try:
        profile = await conversation_scope_store.get_birth_profile(
            conversation_id=session.conversation_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
        )
    except ConversationScopeStoreError as exc:
        raise HTTPException(status_code=503, detail="Widget sessions are temporarily unavailable") from exc

    if not profile:
        return BirthProfileResponse(success=False, message="No confirmed birth profile yet.")

    return BirthProfileResponse(
        success=True,
        message="Confirmed birth profile found.",
        kundali_chart=profile.get("kundali_chart"),
        api_context=profile.get("api_context"),
    )
