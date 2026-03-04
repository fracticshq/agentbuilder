"""
Activity Service — per-conversation event tracking.

Stores structured activity events in each brand's MongoDB database
(collection: activity_events). Provides write + analytics read methods.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import structlog
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from ..config import Settings
from ..connections import connection_manager

logger = structlog.get_logger(__name__)

# Track which brand DBs already have indexes so we only create them once.
_indexed_dbs: set[str] = set()


# ---------------------------------------------------------------------------
# Event type catalogue
# ---------------------------------------------------------------------------

class ActivityEventType(str, Enum):
    # Conversation lifecycle
    conversation_started = "conversation_started"
    conversation_resumed = "conversation_resumed"
    conversation_closed = "conversation_closed"
    conversation_abandoned = "conversation_abandoned"
    conversation_archived = "conversation_archived"

    # Handoff / assignment
    conversation_transferred = "conversation_transferred"
    conversation_reassigned = "conversation_reassigned"

    # Management
    conversation_tagged = "conversation_tagged"

    # Intent & topic
    intent_detected = "intent_detected"
    intent_changed = "intent_changed"
    topic_identified = "topic_identified"
    unknown_intent = "unknown_intent"
    ambiguous_query_flagged = "ambiguous_query_flagged"
    high_query_topic_spike = "high_query_topic_spike"

    # Knowledge
    knowledge_source_used = "knowledge_source_used"
    document_retrieved = "document_retrieved"

    # User behaviour / safety
    frustration_detected = "frustration_detected"
    negative_sentiment_spiked = "negative_sentiment_spiked"
    sensitive_info_detected = "sensitive_info_detected"
    policy_violation_attempt = "policy_violation_attempt"

    # Escalation
    human_escalation_triggered = "human_escalation_triggered"

    # Conversions
    demo_requested = "demo_requested"
    meeting_booked = "meeting_booked"
    lead_form_invoked = "lead_form_invoked"
    lead_form_filled = "lead_form_filled"

    # Commerce
    product_clicked = "product_clicked"
    checkout_initiated = "checkout_initiated"
    added_to_cart = "added_to_cart"

    # Messages
    message_sent = "message_sent"
    message_received = "message_received"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TrackEventRequest(BaseModel):
    event_type: str
    actor_type: str  # "user" | "agent" | "system"
    actor_id: str
    agent_id: str
    conversation_id: str
    session_id: Optional[str] = None
    payload: Optional[dict] = None
    page_context: Optional[dict] = None


class ActivityEvent(BaseModel):
    id: str
    event_type: str
    actor_type: str
    actor_id: str
    agent_id: str
    brand_id: str
    conversation_id: str
    session_id: Optional[str] = None
    payload: Optional[dict] = None
    page_context: Optional[dict] = None
    timestamp: datetime


class SessionSummary(BaseModel):
    conversation_id: str
    started_at: datetime
    last_seen_at: datetime
    event_count: int
    event_types: list[str]


class AnalyticsSummary(BaseModel):
    period: dict  # {from, to}
    total_events: int
    by_type: dict[str, int]
    by_actor: dict[str, int]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ActivityService:
    def __init__(self, settings: Settings):
        self.settings = settings

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_agent(self, agent_id: str) -> tuple[AsyncIOMotorDatabase, str]:
        """Single DB lookup: returns (brand_db, brand_id).

        Replaces the former _get_db + _brand_id_for_agent pair that each did
        a separate find_one against the system agents collection.
        """
        system_db = connection_manager.get_system_db()
        agent = await system_db.agents.find_one({"id": agent_id})
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
        brand_slug = agent.get("brand_slug")
        if not brand_slug:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} has no brand_slug")
        db = connection_manager.get_brand_db(brand_slug)
        return db, brand_slug

    async def _get_db(self, agent_id: str) -> AsyncIOMotorDatabase:
        db, _ = await self._resolve_agent(agent_id)
        return db

    async def _ensure_indexes(self, db: AsyncIOMotorDatabase) -> None:
        db_name: str = db.name
        if db_name in _indexed_dbs:
            return
        col = db["activity_events"]
        await col.create_index([("conversation_id", 1), ("timestamp", 1)])
        await col.create_index([("actor_id", 1), ("timestamp", -1)])
        await col.create_index([("agent_id", 1), ("timestamp", -1)])
        await col.create_index([("event_type", 1), ("agent_id", 1)])
        _indexed_dbs.add(db_name)
        logger.info("activity_indexes_created", db=db_name)

    def _doc_to_event(self, doc: dict) -> ActivityEvent:
        doc.pop("_id", None)
        return ActivityEvent(**doc)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def track(self, req: TrackEventRequest) -> ActivityEvent:
        db, brand_id = await self._resolve_agent(req.agent_id)
        await self._ensure_indexes(db)

        event = ActivityEvent(
            id=str(uuid.uuid4()),
            event_type=req.event_type,
            actor_type=req.actor_type,
            actor_id=req.actor_id,
            agent_id=req.agent_id,
            brand_id=brand_id,
            conversation_id=req.conversation_id,
            session_id=req.session_id,
            payload=req.payload,
            page_context=req.page_context,
            timestamp=datetime.now(timezone.utc),
        )

        await db["activity_events"].insert_one(event.model_dump())
        logger.info("activity_event_tracked", id=event.id, event_type=event.event_type)
        return event

    async def track_batch(self, reqs: list[TrackEventRequest]) -> list[ActivityEvent]:
        if not reqs:
            return []

        # All events in a batch must share the same agent_id to keep DB routing simple.
        # We group by agent_id to support mixed batches gracefully.
        from collections import defaultdict
        by_agent: dict[str, list[TrackEventRequest]] = defaultdict(list)
        for r in reqs:
            by_agent[r.agent_id].append(r)

        events: list[ActivityEvent] = []
        for agent_id, agent_reqs in by_agent.items():
            db, brand_id = await self._resolve_agent(agent_id)
            await self._ensure_indexes(db)
            now = datetime.now(timezone.utc)
            docs = []
            for req in agent_reqs:
                ev = ActivityEvent(
                    id=str(uuid.uuid4()),
                    event_type=req.event_type,
                    actor_type=req.actor_type,
                    actor_id=req.actor_id,
                    agent_id=req.agent_id,
                    brand_id=brand_id,
                    conversation_id=req.conversation_id,
                    session_id=req.session_id,
                    payload=req.payload,
                    page_context=req.page_context,
                    timestamp=now,
                )
                docs.append(ev.model_dump())
                events.append(ev)
            await db["activity_events"].insert_many(docs)

        logger.info("activity_batch_tracked", count=len(events))
        return events

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_conversation_events(
        self,
        conversation_id: str,
        agent_id: str,
        actor_type: Optional[str] = None,
        event_types: Optional[list[str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ActivityEvent], int]:
        db = await self._get_db(agent_id)
        query: dict = {"conversation_id": conversation_id}
        if actor_type:
            query["actor_type"] = actor_type
        if event_types:
            query["event_type"] = {"$in": event_types}

        col = db["activity_events"]
        total = await col.count_documents(query)
        cursor = col.find(query).sort("timestamp", 1).skip(offset).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self._doc_to_event(d) for d in docs], total

    async def get_conversation_timeline(
        self, conversation_id: str, agent_id: str
    ) -> list[ActivityEvent]:
        db = await self._get_db(agent_id)
        cursor = (
            db["activity_events"]
            .find({"conversation_id": conversation_id})
            .sort("timestamp", 1)
        )
        docs = await cursor.to_list(length=1000)
        return [self._doc_to_event(d) for d in docs]

    async def get_user_sessions(
        self,
        user_id: str,
        agent_id: str,
        limit: int = 20,
    ) -> list[SessionSummary]:
        db = await self._get_db(agent_id)
        pipeline = [
            {"$match": {"actor_id": user_id, "actor_type": "user"}},
            {"$group": {
                "_id": "$conversation_id",
                "started_at": {"$min": "$timestamp"},
                "last_seen_at": {"$max": "$timestamp"},
                "event_count": {"$sum": 1},
                "event_types": {"$addToSet": "$event_type"},
            }},
            {"$sort": {"last_seen_at": -1}},
            {"$limit": limit},
        ]
        rows = await db["activity_events"].aggregate(pipeline).to_list(length=limit)
        return [
            SessionSummary(
                conversation_id=r["_id"],
                started_at=r["started_at"],
                last_seen_at=r["last_seen_at"],
                event_count=r["event_count"],
                event_types=r["event_types"],
            )
            for r in rows
        ]

    async def get_analytics(
        self,
        agent_id: str,
        from_ts: Optional[datetime] = None,
        to_ts: Optional[datetime] = None,
    ) -> AnalyticsSummary:
        db = await self._get_db(agent_id)
        match: dict = {"agent_id": agent_id}
        if from_ts or to_ts:
            ts_filter: dict = {}
            if from_ts:
                ts_filter["$gte"] = from_ts
            if to_ts:
                ts_filter["$lte"] = to_ts
            match["timestamp"] = ts_filter

        col = db["activity_events"]

        # Run three aggregations in parallel
        type_pipeline = [
            {"$match": match},
            {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
        ]
        actor_pipeline = [
            {"$match": match},
            {"$group": {"_id": "$actor_type", "count": {"$sum": 1}}},
        ]
        bounds_pipeline = [
            {"$match": match},
            {"$group": {
                "_id": None,
                "total": {"$sum": 1},
                "min_ts": {"$min": "$timestamp"},
                "max_ts": {"$max": "$timestamp"},
            }},
        ]

        import asyncio as _asyncio
        type_rows, actor_rows, bounds_rows = await _asyncio.gather(
            col.aggregate(type_pipeline).to_list(length=500),
            col.aggregate(actor_pipeline).to_list(length=20),
            col.aggregate(bounds_pipeline).to_list(length=1),
        )

        by_type = {r["_id"]: r["count"] for r in type_rows}
        by_actor: dict[str, int] = {"user": 0, "agent": 0, "system": 0}
        for r in actor_rows:
            by_actor[r["_id"]] = r["count"]

        now = datetime.now(timezone.utc)
        if bounds_rows:
            total_events = bounds_rows[0]["total"]
            effective_from = from_ts or bounds_rows[0]["min_ts"] or now
            effective_to = to_ts or bounds_rows[0]["max_ts"] or now
        else:
            total_events = 0
            effective_from = from_ts or now
            effective_to = to_ts or now

        return AnalyticsSummary(
            period={"from": effective_from.isoformat(), "to": effective_to.isoformat()},
            total_events=total_events,
            by_type=by_type,
            by_actor=by_actor,
        )
