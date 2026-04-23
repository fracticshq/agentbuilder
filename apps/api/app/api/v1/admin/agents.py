from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
import uuid
from datetime import datetime
import structlog

from app.connections import connection_manager, get_system_db
from app.auth.dependencies import require_dashboard_access

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(require_dashboard_access)])

# Pydantic models for request/response
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
    brand_slug: str  # Brand slug for database routing
    slug: str
    configuration: dict
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

def generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from the agent name."""
    return name.lower().replace(' ', '-').replace('&', 'and')

def get_agents_collection():
    """Get MongoDB agents collection from system database."""
    if connection_manager.system_db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return connection_manager.system_db.agents

@router.get("/", response_model=List[Agent])
async def list_agents(brand_id: Optional[str] = Query(None)):
    """Get all agents, optionally filtered by brand."""
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
    """Get a specific agent by ID."""
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
async def create_agent(agent: AgentCreate):
    """Create a new agent."""
    try:
        collection = get_agents_collection()
        brands_collection = connection_manager.get_system_db()["brands"]
        
        agent_id = str(uuid.uuid4())
        slug = generate_slug(agent.name)
        
        # Look up brand to get brand_slug
        brand = await brands_collection.find_one({"id": agent.brand_id})
        if not brand:
            raise HTTPException(status_code=404, detail=f"Brand not found: {agent.brand_id}")
        
        brand_slug = brand.get("slug")
        if not brand_slug:
            raise HTTPException(status_code=400, detail=f"Brand {agent.brand_id} has no slug")
        
        # Check if slug already exists for this brand
        existing = await collection.find_one({"brand_id": agent.brand_id, "slug": slug})
        if existing:
            slug = f"{slug}-{agent_id[:8]}"
        
        now = datetime.utcnow()
        agent_doc = {
            "id": agent_id,
            "brand_id": agent.brand_id,
            "brand_slug": brand_slug,  # Add brand_slug for database routing
            "slug": slug,
            "name": agent.name,
            "description": agent.description,
            "system_prompt": agent.system_prompt,
            "configuration": agent.configuration,
            "status": agent.status or "draft",
            "created_at": now,
            "updated_at": now
        }
        
        await collection.insert_one(agent_doc)
        logger.info("Agent created", agent_id=agent_id, name=agent.name, brand_id=agent.brand_id, brand_slug=brand_slug)
        
        return Agent(**agent_doc)
    except Exception as e:
        logger.error("Failed to create agent", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")

@router.put("/{agent_id}", response_model=Agent)
async def update_agent(agent_id: str, agent_update: AgentUpdate):
    """Update an existing agent."""
    try:
        collection = get_agents_collection()
        
        # Check if agent exists
        existing_agent = await collection.find_one({"id": agent_id})
        if not existing_agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        update_data = agent_update.dict(exclude_unset=True)
        
        # Update slug if name changed
        if "name" in update_data:
            update_data["slug"] = generate_slug(update_data["name"])
        
        update_data["updated_at"] = datetime.utcnow()
        
        # Update in MongoDB
        await collection.update_one(
            {"id": agent_id},
            {"$set": update_data}
        )
        
        # Fetch updated agent
        updated_agent = await collection.find_one({"id": agent_id})
        logger.info("Agent updated", agent_id=agent_id)
        
        return Agent(**{**updated_agent, "_id": str(updated_agent["_id"])})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update agent", agent_id=agent_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to update agent: {str(e)}")

@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete an agent."""
    try:
        collection = get_agents_collection()
        
        # Check if agent exists
        existing_agent = await collection.find_one({"id": agent_id})
        if not existing_agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        # Delete from MongoDB
        await collection.delete_one({"id": agent_id})
        logger.info("Agent deleted", agent_id=agent_id)
        
        return {"message": "Agent deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete agent", agent_id=agent_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to delete agent: {str(e)}")
