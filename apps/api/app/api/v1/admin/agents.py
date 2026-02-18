from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import uuid
from datetime import datetime
import structlog

from app.connections import connection_manager, get_system_db
from memory.processors.pii_vault import get_pii_vault

logger = structlog.get_logger()
router = APIRouter()

# Pydantic models for request/response
class AgentBase(BaseModel):
    name: str
    description: str
    system_prompt: str

class AgentCreate(AgentBase):
    brand_id: str
    configuration: dict

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

def validate_agent_configuration(configuration: dict):
    """Validate Shopify configuration if present."""
    if not configuration:
        return
        
    shopify = configuration.get("shopify", {})
    if shopify.get("enabled", False):
        shop_url = shopify.get("shop_url")
        if not shop_url:
             raise HTTPException(status_code=400, detail="Shop URL is required when Shopify is enabled")
        
        # Clean and validate URL
        clean_url = shop_url.strip().lower()
        if not clean_url.endswith(".myshopify.com"):
             raise HTTPException(
                status_code=400, 
                detail="Invalid Shop URL. Must be a '.myshopify.com' domain (e.g., your-store.myshopify.com)."
            )
        
        # Token validation (Shopify tokens are typically > 20 chars)
        storefront_token = shopify.get("storefront_token")
        if not storefront_token or len(storefront_token) < 20:
             raise HTTPException(status_code=400, detail="Valid Storefront Access Token is required (at least 20 characters)")
             
        admin_token = shopify.get("admin_token")
        if admin_token and len(admin_token) < 20:
             raise HTTPException(status_code=400, detail="Admin Access Token is too short (at least 20 characters)")

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
        
        # Decrypt Shopify tokens for UI
        vault = get_pii_vault()
        for agent in agents:
            if "configuration" in agent and "shopify" in agent["configuration"]:
                agent["configuration"]["shopify"] = vault.unveault_dict(
                    agent["configuration"]["shopify"],
                    ["storefront_token", "admin_token"]
                )
        
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
            
        # Decrypt Shopify tokens for UI
        if "configuration" in agent and "shopify" in agent["configuration"]:
            vault = get_pii_vault()
            agent["configuration"]["shopify"] = vault.unveault_dict(
                agent["configuration"]["shopify"],
                ["storefront_token", "admin_token"]
            )
            
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
        # Validate configuration
        validate_agent_configuration(agent.configuration)
        
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
        
        # Disable encryption for now as requested
        config_to_save = agent.configuration

        agent_doc = {
            "id": agent_id,
            "brand_id": agent.brand_id,
            "brand_slug": brand_slug,  # Add brand_slug for database routing
            "slug": slug,
            "name": agent.name,
            "description": agent.description,
            "system_prompt": agent.system_prompt,
            "configuration": config_to_save,
            "status": "draft",
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
        
        # Validate configuration if being updated
        if agent_update.configuration is not None:
            validate_agent_configuration(agent_update.configuration)
            
        # Disable encryption for now as requested
        update_data = agent_update.dict(exclude_unset=True)
        
        # Update slug if name changed
        if "name" in update_data:
            update_data["slug"] = generate_slug(update_data["name"])

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
