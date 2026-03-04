"""
Activity API Endpoints — write and read conversation activity events.
"""

from datetime import datetime
from typing import Optional
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ....dependencies import get_activity_service
from ....services.activity_service import ActivityService, TrackEventRequest

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


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------

@router.post("/events", status_code=201, response_model=TrackEventResponse)
async def track_event(
    request: TrackEventRequest,
    svc: ActivityService = Depends(get_activity_service),
):
    """Track a single activity event."""
    event = await svc.track(request)
    return TrackEventResponse(id=event.id, timestamp=event.timestamp)


@router.post("/events/batch", status_code=201, response_model=BatchTrackResponse)
async def track_events_batch(
    body: BatchTrackRequest,
    svc: ActivityService = Depends(get_activity_service),
):
    """Track up to 50 activity events in a single request."""
    if not body.events:
        raise HTTPException(status_code=422, detail="events list is empty")
    events = await svc.track_batch(body.events)
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
):
    """Return events for a conversation, with optional filtering."""
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
):
    """Return all events for a conversation sorted by timestamp."""
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
):
    """Return session summaries for a user (one row per conversation)."""
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
):
    """Return aggregate analytics for an agent over a time range."""
    summary = await svc.get_analytics(
        agent_id=agent_id,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    return summary.model_dump()
