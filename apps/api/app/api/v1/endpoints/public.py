"""
Public widget bootstrap endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

from app.connections import connection_manager
from app.services.commerce_config import is_commerce_agent_config, normalize_commerce_configuration
from app.auth.widget_session import decode_widget_session
from .knowledge import _hydrate_product_cards, _product_card_from_data

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


class PublicCatalogProductsRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)
    skus: List[str] = Field(default_factory=list, max_length=50)
    variant_ids: List[str] = Field(default_factory=list, max_length=50)


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
    configuration = normalize_commerce_configuration(configuration, public_widget_projection=True)
    features = configuration.get("features") or {}
    channels = configuration.get("channels") or {}
    widget = channels.get("widget") or {}
    domain = configuration.get("domain") or {}
    url_context_boost = configuration.get("url_context_boost") or {}
    is_commerce_agent = is_commerce_agent_config(configuration)

    # 'basic' (cycling indicator) or 'advanced' (live step timeline).
    activity_mode = widget.get("activity_mode", features.get("activity_mode", "basic"))
    if activity_mode not in ("basic", "advanced"):
        activity_mode = "basic"
    # In advanced mode: 'temporary' (timeline disappears after the answer) or
    # 'persistent' (stays attached to the message, Claude/ChatGPT style).
    activity_persistence = widget.get("activity_persistence", features.get("activity_persistence", "temporary"))
    if activity_persistence not in ("temporary", "persistent"):
        activity_persistence = "temporary"
    commerce_display_policy = (configuration.get("commerce") or {}).get("display_policy") or {}
    show_sources = (
        commerce_display_policy.get("show_sources", False)
        if is_commerce_agent
        else widget.get("show_sources", features.get("show_sources", False))
    )
    show_product_cards = (
        commerce_display_policy.get("show_product_cards", True)
        if is_commerce_agent
        else widget.get("show_product_cards", features.get("show_product_cards", True))
    )

    public_config = {
        "domain": domain,
        "url_context_boost": {
            "enabled": url_context_boost.get("enabled", False),
        },
        "features": {
            "websockets": features.get("websockets", True),
            "show_sources": show_sources,
            "show_product_cards": show_product_cards,
            "human_takeover": widget.get("human_takeover", features.get("human_takeover", False)),
            "activity_mode": activity_mode,
            "activity_persistence": activity_persistence,
        },
        "channels": {
            "widget": {
                "enabled": widget.get("enabled", True),
                "preview_enabled": widget.get("preview_enabled", widget.get("enabled", True)),
                "show_sources": show_sources,
                "show_product_cards": show_product_cards,
                "human_takeover": widget.get("human_takeover", features.get("human_takeover", False)),
                "activity_mode": activity_mode,
                "activity_persistence": activity_persistence,
            }
        },
    }
    if is_commerce_agent:
        public_config["commerce"] = configuration["commerce"]
    return public_config


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


@router.post("/catalog/products")
async def get_public_catalog_products(
    request: PublicCatalogProductsRequest,
    x_widget_session: Optional[str] = Header(None),
):
    """Hydrate legacy product references using the signed public widget session."""
    session = decode_widget_session(x_widget_session, expected_agent_id=request.agent_id)
    if session is None:
        raise HTTPException(status_code=401, detail="A valid widget session token is required")
    if not request.skus and not request.variant_ids:
        return {"success": True, "products": [], "count": 0}

    db = _system_db()
    agent = await db.agents.find_one({"id": request.agent_id, "status": "active"}, {"brand_slug": 1, "configuration": 1})
    if not agent or not _widget_enabled(agent.get("configuration") or {}):
        raise HTTPException(status_code=404, detail="Agent not found")
    brand_slug = agent.get("brand_slug")
    if not brand_slug:
        raise HTTPException(status_code=400, detail="Agent has no brand catalog")

    try:
        brand_db = connection_manager.get_brand_db(brand_slug)
        collection = brand_db["knowledge_base"]
        clauses = []
        if request.skus:
            clauses.extend([
                {"product_data.sku": {"$in": request.skus}},
                {"product_data.variant_sku": {"$in": request.skus}},
            ])
        if request.variant_ids:
            clauses.extend([
                {"product_data.variant_id": {"$in": request.variant_ids}},
                {"product_data.id": {"$in": request.variant_ids}},
            ])
        cursor = collection.find({
            "content_type": "product",
            "product_data.source_active": {"$ne": False},
            "metadata.catalog_source.active": {"$ne": False},
            "$or": clauses,
        })
        matched = []
        async for document in cursor:
            product_data = document.get("product_data") or {}
            if product_data:
                matched.append(_product_card_from_data(product_data))
        retrieval = ((agent.get("configuration") or {}).get("commerce") or {}).get("retrieval") or {}
        try:
            max_variants = max(1, min(int(retrieval.get("max_variants_per_card") or 100), 500))
        except (TypeError, ValueError):
            max_variants = 100
        products = await _hydrate_product_cards(collection, matched, max_variants=max_variants)
        return {"success": True, "products": products, "count": len(products)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("public_catalog_hydration_failed", agent_id=request.agent_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Unable to hydrate catalog products")
