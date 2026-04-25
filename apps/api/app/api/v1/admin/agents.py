from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks
from pydantic import BaseModel
import uuid
from datetime import datetime
import structlog

from app.connections import connection_manager
from app.auth.dependencies import require_dashboard_access
from app.dependencies import get_runtime_settings_service
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.strapi_provisioning_service import StrapiProvisioningService

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(require_dashboard_access)])


class AgentBase(BaseModel):
    name: str
    description: str
    system_prompt: str


class AgentCreate(AgentBase):
    brand_id: str
    configuration: dict
    status: Optional[str] = "draft"


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    configuration: Optional[dict] = None
    status: Optional[str] = None


class Agent(AgentBase):
    id: str
    brand_id: str
    brand_slug: str
    slug: str
    configuration: dict
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def generate_slug(name: str) -> str:
    return name.lower().replace(' ', '-').replace('&', 'and')


def get_agents_collection():
    if connection_manager.system_db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return connection_manager.system_db.agents


async def get_brand_or_404(brand_id: str) -> dict:
    brands_collection = connection_manager.get_system_db()["brands"]
    brand = await brands_collection.find_one({"id": brand_id})
    if not brand:
        raise HTTPException(status_code=404, detail=f"Brand not found: {brand_id}")
    return brand


async def get_brand_for_sync(brand_id: str) -> dict | None:
    try:
        brands_collection = connection_manager.get_system_db()["brands"]
        return await brands_collection.find_one({"id": brand_id})
    except Exception as exc:
        logger.warning("strapi_brand_lookup_failed", brand_id=brand_id, error=str(exc))
        return None


def should_sync_agent_dashboard(existing_agent: dict | None, updated_agent: dict) -> bool:
    new_status = updated_agent.get("status")
    previous_status = existing_agent.get("status") if existing_agent else None
    if new_status == "active":
        return True
    if previous_status == "active" and new_status != "active":
        return True
    return False


async def sync_agent_to_strapi_best_effort(
    runtime_settings_service: RuntimeSettingsService,
    brand_doc: dict | None,
    agent_doc: dict,
) -> None:
    if not brand_doc:
        logger.warning(
            "strapi_agent_provisioning_skipped",
            reason="missing_brand",
            agent_id=agent_doc.get("id"),
            brand_id=agent_doc.get("brand_id"),
        )
        return

    try:
        config = await runtime_settings_service.get_strapi_runtime_config()
        provisioning = StrapiProvisioningService(
            config.get("base_url", ""),
            config.get("api_token", ""),
        )
        await provisioning.provision_agent_dashboard_best_effort(brand_doc, agent_doc)
    except Exception as exc:
        logger.warning(
            "strapi_agent_provisioning_setup_failed",
            error=str(exc),
            agent_id=agent_doc.get("id"),
            brand_slug=brand_doc.get("slug"),
        )


@router.get("/", response_model=List[Agent])
async def list_agents(brand_id: Optional[str] = Query(None)):
    try:
        collection = get_agents_collection()
        query = {"brand_id": brand_id} if brand_id else {}
        agents = await collection.find(query).to_list(length=None)
        return [Agent(**{**agent, "_id": str(agent["_id"])}) for agent in agents]
    except Exception as e:
        logger.error("Failed to list agents", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to list agents: {str(e)}")


@router.get("/{agent_id}", response_model=Agent)
async def get_agent(agent_id: str):
    try:
        collection = get_agents_collection()
        agent = await collection.find_one({"id": agent_id})
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return Agent(**{**agent, "_id": str(agent["_id"])})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get agent", agent_id=agent_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get agent: {str(e)}")


@router.post("/", response_model=Agent)
async def create_agent(
    agent: AgentCreate,
    background_tasks: BackgroundTasks,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    try:
        collection = get_agents_collection()
        brand = await get_brand_or_404(agent.brand_id)

        agent_id = str(uuid.uuid4())
        slug = generate_slug(agent.name)
        brand_slug = brand.get("slug")
        if not brand_slug:
            raise HTTPException(status_code=400, detail=f"Brand {agent.brand_id} has no slug")

        existing = await collection.find_one({"brand_id": agent.brand_id, "slug": slug})
        if existing:
            slug = f"{slug}-{agent_id[:8]}"

        now = datetime.utcnow()
        agent_doc = {
            "id": agent_id,
            "brand_id": agent.brand_id,
            "brand_slug": brand_slug,
            "slug": slug,
            "name": agent.name,
            "description": agent.description,
            "system_prompt": agent.system_prompt,
            "configuration": agent.configuration,
            "status": agent.status or "draft",
            "created_at": now,
            "updated_at": now,
        }

        await collection.insert_one(agent_doc)
        if should_sync_agent_dashboard(None, agent_doc):
            background_tasks.add_task(
                sync_agent_to_strapi_best_effort,
                runtime_settings_service,
                brand,
                agent_doc,
            )
        logger.info("Agent created", agent_id=agent_id, name=agent.name, brand_id=agent.brand_id, brand_slug=brand_slug)
        return Agent(**agent_doc)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create agent", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")


@router.put("/{agent_id}", response_model=Agent)
async def update_agent(
    agent_id: str,
    agent_update: AgentUpdate,
    background_tasks: BackgroundTasks,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    try:
        collection = get_agents_collection()
        existing_agent = await collection.find_one({"id": agent_id})
        if not existing_agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        update_data = agent_update.dict(exclude_unset=True)
        if "name" in update_data:
            update_data["slug"] = generate_slug(update_data["name"])
        update_data["updated_at"] = datetime.utcnow()

        await collection.update_one({"id": agent_id}, {"$set": update_data})
        updated_agent = await collection.find_one({"id": agent_id})
        if should_sync_agent_dashboard(existing_agent, updated_agent):
            brand_doc = await get_brand_for_sync(updated_agent["brand_id"])
            background_tasks.add_task(
                sync_agent_to_strapi_best_effort,
                runtime_settings_service,
                brand_doc,
                updated_agent,
            )
        logger.info("Agent updated", agent_id=agent_id)
        return Agent(**{**updated_agent, "_id": str(updated_agent["_id"])})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update agent", agent_id=agent_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to update agent: {str(e)}")


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    background_tasks: BackgroundTasks,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    try:
        collection = get_agents_collection()
        existing_agent = await collection.find_one({"id": agent_id})
        if not existing_agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        brand_doc = await get_brand_for_sync(existing_agent.get("brand_id"))
        await collection.delete_one({"id": agent_id})
        if existing_agent.get("status") == "active" and brand_doc:
            deactivated_agent = {**existing_agent, "status": "inactive"}
            background_tasks.add_task(
                sync_agent_to_strapi_best_effort,
                runtime_settings_service,
                brand_doc,
                deactivated_agent,
            )
        logger.info("Agent deleted", agent_id=agent_id)
        return {"message": "Agent deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete agent", agent_id=agent_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to delete agent: {str(e)}")
