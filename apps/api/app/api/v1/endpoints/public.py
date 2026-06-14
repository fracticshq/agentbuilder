"""
Public widget bootstrap endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.connections import connection_manager

router = APIRouter()


class PublicAgentResponse(BaseModel):
    id: str
    brand_id: str
    name: str
    description: str
    configuration: dict[str, Any]
    status: str


class PublicBrandResponse(BaseModel):
    id: str
    name: str
    slug: str
    colors: dict[str, Any] | None = None
    logo_url: str | None = None
    website: str | None = None
    updated_at: datetime


def _system_db():
    if connection_manager.system_db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return connection_manager.system_db


def _widget_enabled(configuration: dict[str, Any]) -> bool:
    channels = configuration.get("channels") or {}
    widget = channels.get("widget") or {}
    return widget.get("enabled", True) is not False


def _public_agent_config(configuration: dict[str, Any]) -> dict[str, Any]:
    """Return widget-safe configuration without secrets or admin-only material."""
    features = configuration.get("features") or {}
    channels = configuration.get("channels") or {}
    widget = channels.get("widget") or {}
    domain = configuration.get("domain") or {}
    url_context_boost = configuration.get("url_context_boost") or {}

    return {
        "domain": domain,
        "url_context_boost": {
            "enabled": url_context_boost.get("enabled", False),
        },
        "features": {
            "websockets": features.get("websockets", True),
            "show_sources": widget.get("show_sources", features.get("show_sources", False)),
            "show_product_cards": widget.get("show_product_cards", features.get("show_product_cards", True)),
            "human_takeover": widget.get("human_takeover", features.get("human_takeover", False)),
        },
        "channels": {
            "widget": {
                "enabled": widget.get("enabled", True),
                "preview_enabled": widget.get("preview_enabled", widget.get("enabled", True)),
                "show_sources": widget.get("show_sources", features.get("show_sources", False)),
                "show_product_cards": widget.get("show_product_cards", features.get("show_product_cards", True)),
                "human_takeover": widget.get("human_takeover", features.get("human_takeover", False)),
            }
        },
    }


@router.get("/agents", response_model=list[PublicAgentResponse])
async def list_public_agents():
    db = _system_db()
    agents = await db.agents.find({"status": "active"}).sort("created_at", 1).to_list(length=100)
    return [
        PublicAgentResponse(
            id=agent["id"],
            brand_id=agent["brand_id"],
            name=agent["name"],
            description=agent.get("description", ""),
            configuration=_public_agent_config(agent.get("configuration", {})),
            status=agent.get("status", "draft"),
        )
        for agent in agents
        if _widget_enabled(agent.get("configuration", {}))
    ]


@router.get("/agents/{agent_id}", response_model=PublicAgentResponse)
async def get_public_agent(agent_id: str):
    db = _system_db()
    agent = await db.agents.find_one({"id": agent_id, "status": "active"})
    if not agent or not _widget_enabled(agent.get("configuration", {})):
        raise HTTPException(status_code=404, detail="Agent not found")
    return PublicAgentResponse(
        id=agent["id"],
        brand_id=agent["brand_id"],
        name=agent["name"],
        description=agent.get("description", ""),
        configuration=_public_agent_config(agent.get("configuration", {})),
        status=agent.get("status", "draft"),
    )


@router.get("/brands/{brand_id}", response_model=PublicBrandResponse)
async def get_public_brand(brand_id: str):
    db = _system_db()
    brand = await db.brands.find_one({"id": brand_id})
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    return PublicBrandResponse(
        id=brand["id"],
        name=brand["name"],
        slug=brand["slug"],
        colors=brand.get("colors", {}),
        logo_url=brand.get("logo_url"),
        website=brand.get("website"),
        updated_at=brand["updated_at"],
    )
