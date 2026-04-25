from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import uuid
from datetime import datetime
import structlog

from app.connections import connection_manager, get_system_db
from app.auth.dependencies import require_dashboard_access

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(require_dashboard_access)])

# Pydantic models for request/response
class BrandBase(BaseModel):
    name: str
    description: str
    industry: str
    website: Optional[str] = None
    logo_url: Optional[str] = None
    colors: Optional[dict] = None

class BrandCreate(BrandBase):
    pass

class BrandUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    colors: Optional[dict] = None

class Brand(BrandBase):
    id: str
    slug: str
    contact_info: Optional[dict] = None
    brand_voice: Optional[dict] = None
    colors: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

def generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from the brand name."""
    return name.lower().replace(' ', '-').replace('&', 'and')

def get_brands_collection():
    """Get MongoDB brands collection from system database."""
    if connection_manager.system_db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return connection_manager.system_db.brands

@router.get("/", response_model=List[Brand])
async def list_brands():
    """Get all brands."""
    try:
        collection = get_brands_collection()
        brands = await collection.find().to_list(length=None)
        return [Brand(**{**brand, "_id": str(brand["_id"])}) for brand in brands]
    except Exception as e:
        logger.error("Failed to list brands", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to list brands: {str(e)}")

@router.get("/{brand_id}", response_model=Brand)
async def get_brand(brand_id: str):
    """Get a specific brand by ID."""
    try:
        collection = get_brands_collection()
        brand = await collection.find_one({"id": brand_id})
        if not brand:
            raise HTTPException(status_code=404, detail="Brand not found")
        return Brand(**{**brand, "_id": str(brand["_id"])})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get brand", brand_id=brand_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get brand: {str(e)}")

@router.post("/", response_model=Brand)
async def create_brand(brand: BrandCreate):
    """Create a new brand."""
    try:
        collection = get_brands_collection()
        brand_id = str(uuid.uuid4())
        slug = generate_slug(brand.name)
        
        # Check if slug already exists
        existing = await collection.find_one({"slug": slug})
        if existing:
            slug = f"{slug}-{brand_id[:8]}"
        
        now = datetime.utcnow()
        brand_doc = {
            "id": brand_id,
            "slug": slug,
            "name": brand.name,
            "description": brand.description,
            "industry": brand.industry,
            "website": brand.website,
            "logo_url": brand.logo_url,
            "contact_info": {},
            "brand_voice": {},
            "colors": brand.colors or {},
            "created_at": now,
            "updated_at": now
        }
        
        await collection.insert_one(brand_doc)
        logger.info("Brand created", brand_id=brand_id, name=brand.name)
        
        return Brand(**brand_doc)
    except Exception as e:
        logger.error("Failed to create brand", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create brand: {str(e)}")

@router.put("/{brand_id}", response_model=Brand)
async def update_brand(brand_id: str, brand_update: BrandUpdate):
    """Update an existing brand."""
    try:
        collection = get_brands_collection()
        
        # Check if brand exists
        existing_brand = await collection.find_one({"id": brand_id})
        if not existing_brand:
            raise HTTPException(status_code=404, detail="Brand not found")
        
        update_data = brand_update.dict(exclude_unset=True)
        
        # Update slug if name changed
        if "name" in update_data:
            update_data["slug"] = generate_slug(update_data["name"])
        
        update_data["updated_at"] = datetime.utcnow()
        
        # Update in MongoDB
        await collection.update_one(
            {"id": brand_id},
            {"$set": update_data}
        )
        
        # Fetch updated brand
        updated_brand = await collection.find_one({"id": brand_id})
        logger.info("Brand updated", brand_id=brand_id)
        
        return Brand(**{**updated_brand, "_id": str(updated_brand["_id"])})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update brand", brand_id=brand_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to update brand: {str(e)}")

@router.delete("/{brand_id}")
async def delete_brand(brand_id: str):
    """Delete a brand."""
    try:
        collection = get_brands_collection()
        
        # Check if brand exists
        existing_brand = await collection.find_one({"id": brand_id})
        if not existing_brand:
            raise HTTPException(status_code=404, detail="Brand not found")
        
        # Delete from MongoDB
        await collection.delete_one({"id": brand_id})
        logger.info("Brand deleted", brand_id=brand_id)
        
        return {"message": "Brand deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete brand", brand_id=brand_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to delete brand: {str(e)}")
