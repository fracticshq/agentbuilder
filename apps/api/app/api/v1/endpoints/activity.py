"""
Activity API Endpoints — write and read conversation activity events.
"""

from datetime import datetime
from typing import Optional
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ....dependencies import get_activity_service
from ....services.activity_service import ActivityService, TrackEventRequest
from ....auth.dependencies import ensure_brand_access, ensure_permission, require_dashboard_access
from ....auth.models import Permission, User
from ....auth.widget_session import WidgetSession, decode_widget_session
from ....connections import connection_manager

logger = structlog.get_logger()
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------

class BatchTrackRequest(BaseModel):
    events: list[TrackEventRequest] = Field(..., max_length=50)


class TrackEventResponse(BaseModel):
    id: str
    timestamp: datetime


class BatchTrackResponse(BaseModel):
    created: int
    ids: list[str]


def _require_widget_session(
    x_widget_session: Optional[str],
    expected_agent_id: str,
) -> WidgetSession:
    session = decode_widget_session(x_widget_session, expected_agent_id=expected_agent_id)
    if not session:
        raise HTTPException(status_code=401, detail="A valid widget session is required")
    return session


def _bind_widget_event(request: TrackEventRequest, session: WidgetSession) -> TrackEventRequest:
    """Derive tenant and actor identity from the signed widget session."""
    if request.actor_type not in {"user", "agent"}:
        raise HTTPException(status_code=422, detail="Widget activity actor_type must be user or agent")
    return request.model_copy(
        update={
            "agent_id": session.agent_id,
            "conversation_id": session.conversation_id,
            "actor_id": session.user_id if request.actor_type == "user" else session.agent_id,
            "session_id": session.conversation_id,
        }
    )


async def _require_agent_brand_access(current_user: User | None, agent_id: str) -> None:
    agent = await connection_manager.get_system_db().agents.find_one({"id": agent_id}, {"brand_id": 1})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    ensure_permission(current_user, Permission.MESSAGE_READ)
    ensure_brand_access(current_user, agent.get("brand_id"))


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------

@router.post("/events", status_code=201, response_model=TrackEventResponse)
async def track_event(
    request: TrackEventRequest,
    svc: ActivityService = Depends(get_activity_service),
    x_widget_session: Optional[str] = Header(None),
):
    """Track a single activity event."""
    session = _require_widget_session(x_widget_session, request.agent_id)
    event = await svc.track(_bind_widget_event(request, session))
    return TrackEventResponse(id=event.id, timestamp=event.timestamp)


@router.post("/events/batch", status_code=201, response_model=BatchTrackResponse)
async def track_events_batch(
    body: BatchTrackRequest,
    svc: ActivityService = Depends(get_activity_service),
    x_widget_session: Optional[str] = Header(None),
):
    """Track up to 50 activity events in a single request."""
    if not body.events:
        raise HTTPException(status_code=422, detail="events list is empty")
    expected_agent_id = body.events[0].agent_id
    if any(event.agent_id != expected_agent_id for event in body.events):
        raise HTTPException(status_code=422, detail="Widget event batches must target one agent")
    session = _require_widget_session(x_widget_session, expected_agent_id)
    events = await svc.track_batch([_bind_widget_event(event, session) for event in body.events])
    return BatchTrackResponse(created=len(events), ids=[e.id for e in events])


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@router.get("/conversations/{conversation_id}/events")
async def get_conversation_events(
    conversation_id: str,
    agent_id: str = Query(..., description="Agent ID (required to resolve brand DB)"),
    actor_type: Optional[str] = Query(None, description="Filter by actor_type"),
    event_type: Optional[str] = Query(None, description="Comma-separated event_types"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    svc: ActivityService = Depends(get_activity_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Return events for a conversation, with optional filtering."""
    await _require_agent_brand_access(current_user, agent_id)
    event_types = [e.strip() for e in event_type.split(",")] if event_type else None
    events, total = await svc.get_conversation_events(
        conversation_id=conversation_id,
        agent_id=agent_id,
        actor_type=actor_type,
        event_types=event_types,
        limit=limit,
        offset=offset,
    )
    return {
        "conversation_id": conversation_id,
        "events": [e.model_dump() for e in events],
        "total": total,
    }


@router.get("/conversations/{conversation_id}/timeline")
async def get_conversation_timeline(
    conversation_id: str,
    agent_id: str = Query(..., description="Agent ID (required to resolve brand DB)"),
    svc: ActivityService = Depends(get_activity_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Return all events for a conversation sorted by timestamp."""
    await _require_agent_brand_access(current_user, agent_id)
    events = await svc.get_conversation_timeline(
        conversation_id=conversation_id,
        agent_id=agent_id,
    )
    return {
        "conversation_id": conversation_id,
        "timeline": [e.model_dump() for e in events],
    }


@router.get("/users/{user_id}/sessions")
async def get_user_sessions(
    user_id: str,
    agent_id: str = Query(..., description="Agent ID (required to resolve brand DB)"),
    limit: int = Query(20, ge=1, le=200),
    svc: ActivityService = Depends(get_activity_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Return session summaries for a user (one row per conversation)."""
    await _require_agent_brand_access(current_user, agent_id)
    sessions = await svc.get_user_sessions(
        user_id=user_id,
        agent_id=agent_id,
        limit=limit,
    )
    return {"user_id": user_id, "sessions": [s.model_dump() for s in sessions]}


@router.get("/analytics")
async def get_analytics(
    agent_id: str = Query(..., description="Agent ID"),
    from_ts: Optional[datetime] = Query(None, alias="from"),
    to_ts: Optional[datetime] = Query(None, alias="to"),
    svc: ActivityService = Depends(get_activity_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Return aggregate analytics for an agent over a time range."""
    await _require_agent_brand_access(current_user, agent_id)
    summary = await svc.get_analytics(
        agent_id=agent_id,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    return summary.model_dump()
