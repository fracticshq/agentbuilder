"""
Knowledge Base API Endpoints - Enhanced with Structured Metadata
Supports both document uploads and bulk JSON imports with product/dealer data
"""

from typing import List, Optional, Literal
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks, Body
from pydantic import BaseModel, Field
import structlog

from ....dependencies import get_knowledge_service
from ....auth.dependencies import require_dashboard_access
from ....services.knowledge_service import KnowledgeService

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(require_dashboard_access)])


# ============================================================================
# Request/Response Models
# ============================================================================

class ProductData(BaseModel):
    """Structured product metadata."""
    sku: str = Field(..., description="Product SKU/ID (unique identifier)")
    name: str = Field(..., description="Product name/title")
    price: int = Field(..., description="Price in smallest currency unit (e.g., paise, cents)")
    currency: str = Field(..., description="Currency code (e.g., INR, USD)")
    category: str = Field(..., description="Product category")
    image_url: Optional[str] = Field(None, description="Product image URL")
    product_url: Optional[str] = Field(None, description="Product page URL")
    in_stock: Optional[bool] = Field(True, description="Stock availability")
    features: Optional[List[str]] = Field(default_factory=list, description="Product features/tags")


class DealerData(BaseModel):
    """Structured dealer metadata."""
    dealer_id: str = Field(..., description="Dealer ID (unique identifier)")
    name: str = Field(..., description="Dealer/Store name")
    city: str = Field(..., description="City location")
    phone: str = Field(..., description="Contact phone number")
    state: Optional[str] = Field(None, description="State/Province")
    email: Optional[str] = Field(None, description="Contact email")
    address: Optional[str] = Field(None, description="Full address")


class DocumentUploadRequest(BaseModel):
    """Request for uploading a single document with metadata."""
    content_type: Literal["product", "dealer", "faq", "office", "category", "guide"]
    product_data: Optional[ProductData] = None
    dealer_data: Optional[DealerData] = None
    # file will be uploaded via multipart form data


class BulkUploadItem(BaseModel):
    """Single item in bulk JSON upload."""
    # For products
    sku: Optional[str] = None
    name: Optional[str] = None
    price: Optional[int] = None
    currency: Optional[str] = None
    category: Optional[str] = None
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    in_stock: Optional[bool] = None
    features: Optional[List[str]] = None
    
    # For dealers
    dealer_id: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    state: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class BulkUploadRequest(BaseModel):
    """Request for bulk JSON upload."""
    content_type: Literal["product", "dealer"]
    items: List[BulkUploadItem] = Field(..., min_items=1, max_items=1000)
    brand_id: str = Field(..., description="Brand/Agent ID")


class UploadResponse(BaseModel):
    """Response for upload operations."""
    success: bool
    job_id: str
    message: str
    items_count: int
    status: str = "processing"


class JobStatusResponse(BaseModel):
    """Response for job status check."""
    job_id: str
    status: Literal["pending", "processing", "completed", "error"]
    progress: dict
    error: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    content_type: str = "guide",
    brand_id: str = "default",
    product_data: Optional[str] = None,  # JSON string
    dealer_data: Optional[str] = None,   # JSON string
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """
    Upload a single document with structured metadata.
    
    Supports:
    - PDF, DOCX, TXT, MD, HTML files
    - Content types: product, dealer, faq, office, category, guide
    - Structured metadata for products and dealers
    
    The document will be:
    1. Parsed and chunked
    2. Embedded using Voyage AI
    3. Stored in MongoDB with structured metadata
    """
    try:
        # Validate file type
        allowed_types = {
            "text/plain", "text/markdown", "application/pdf",
            "text/html", "application/json",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        }
        
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file.content_type}. Allowed: PDF, DOCX, TXT, MD, HTML"
            )
        
        # Parse structured metadata if provided
        import json
        parsed_product_data = None
        parsed_dealer_data = None
        
        if product_data:
            try:
                parsed_product_data = ProductData(**json.loads(product_data))
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid product_data JSON: {str(e)}")
        
        if dealer_data:
            try:
                parsed_dealer_data = DealerData(**json.loads(dealer_data))
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid dealer_data JSON: {str(e)}")
        
        # Read file content
        content = await file.read()
        
        # Start ingestion job
        job_id = await knowledge_service.start_document_upload(
            content=content,
            filename=file.filename,
            content_type_header=file.content_type,
            kb_content_type=content_type,
            brand_id=brand_id,
            product_data=parsed_product_data,
            dealer_data=parsed_dealer_data
        )
        
        # Process in background
        background_tasks.add_task(
            knowledge_service.process_document_upload,
            job_id=job_id,
            content=content,
            filename=file.filename,
            content_type_header=file.content_type,
            kb_content_type=content_type,
            brand_id=brand_id,
            product_data=parsed_product_data,
            dealer_data=parsed_dealer_data
        )
        
        logger.info(
            "Document upload started",
            job_id=job_id,
            filename=file.filename,
            content_type=content_type,
            brand_id=brand_id,
            has_product_data=parsed_product_data is not None,
            has_dealer_data=parsed_dealer_data is not None
        )
        
        return UploadResponse(
            success=True,
            job_id=job_id,
            message=f"Document upload started: {file.filename}",
            items_count=1,
            status="processing"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Document upload failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/bulk-upload", response_model=UploadResponse)
async def bulk_upload_json(
    background_tasks: BackgroundTasks,
    request: BulkUploadRequest = Body(...),
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """
    Bulk upload products or dealers from JSON.
    
    Accepts:
    - Up to 1000 items per request
    - Products: Must have sku, name, price, currency, category
    - Dealers: Must have dealer_id, name, city, phone
    
    Each item will be:
    1. Validated for required fields
    2. Converted to text chunks with structured metadata
    3. Embedded using Voyage AI
    4. Stored in MongoDB knowledge_base collection
    
    Example for products:
    ```json
    {
      "content_type": "product",
      "brand_id": "essco-bathware",
      "items": [
        {
          "sku": "FAU-001",
          "name": "Chrome Faucet",
          "price": 3499,
          "currency": "INR",
          "category": "faucets",
          "features": ["chrome", "ceramic disc"]
        }
      ]
    }
    ```
    """
    try:
        # Validate items based on content_type
        if request.content_type == "product":
            for i, item in enumerate(request.items):
                missing = []
                # Convert to dict for easier validation
                item_dict = item.dict() if hasattr(item, 'dict') else item
                
                if not item_dict.get("sku"):
                    missing.append("sku")
                if not item_dict.get("name"):
                    missing.append("name")
                if item_dict.get("price") is None:
                    missing.append("price")
                if not item_dict.get("currency"):
                    missing.append("currency")
                if not item_dict.get("category"):
                    missing.append("category")
                
                if missing:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Item {i + 1}: Missing required product fields: {', '.join(missing)}"
                    )
        
        elif request.content_type == "dealer":
            for i, item in enumerate(request.items):
                missing = []
                # Convert to dict for easier validation
                item_dict = item.dict() if hasattr(item, 'dict') else item
                
                if not item_dict.get("dealer_id"):
                    missing.append("dealer_id")
                if not item_dict.get("name"):
                    missing.append("name")
                if not item_dict.get("city"):
                    missing.append("city")
                if not item_dict.get("phone"):
                    missing.append("phone")
                
                if missing:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Item {i + 1}: Missing required dealer fields: {', '.join(missing)}"
                    )
        
        # Start bulk ingestion job
        job_id = await knowledge_service.start_bulk_upload(
            content_type=request.content_type,
            items=request.items,
            brand_id=request.brand_id
        )
        
        # Process in background
        background_tasks.add_task(
            knowledge_service.process_bulk_upload,
            job_id=job_id,
            content_type=request.content_type,
            items=request.items,
            brand_id=request.brand_id
        )
        
        logger.info(
            "Bulk upload started",
            job_id=job_id,
            content_type=request.content_type,
            items_count=len(request.items),
            brand_id=request.brand_id
        )
        
        return UploadResponse(
            success=True,
            job_id=job_id,
            message=f"Bulk upload started: {len(request.items)} {request.content_type}s",
            items_count=len(request.items),
            status="processing"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Bulk upload failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Bulk upload failed: {str(e)}")


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """
    Get the status of an upload job.
    
    Returns:
    - status: pending, processing, completed, error
    - progress: details about what's been processed
    - error: error message if status is 'error'
    """
    try:
        status_data = await knowledge_service.get_job_status(job_id)
        
        if not status_data:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        
        return JobStatusResponse(**status_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get job status", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")


@router.get("/documents")
async def list_documents(
    brand_id: str,
    content_type: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """
    List documents in knowledge base.
    
    Query parameters:
    - brand_id: Filter by brand/agent ID (required)
    - content_type: Filter by content type (optional)
    - limit: Number of documents to return (default: 50)
    - skip: Number of documents to skip (default: 0)
    """
    try:
        documents = await knowledge_service.list_documents(
            brand_id=brand_id,
            content_type=content_type,
            limit=limit,
            skip=skip
        )
        
        return {
            "success": True,
            "documents": documents,
            "count": len(documents)
        }
        
    except Exception as e:
        logger.error("Failed to list documents", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    brand_id: str,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """
    Delete a document and all its chunks.
    
    Path parameters:
    - doc_id: Document ID to delete
    
    Query parameters:
    - brand_id: Brand/agent ID for authorization
    """
    try:
        deleted_count = await knowledge_service.delete_document(
            doc_id=doc_id,
            brand_id=brand_id
        )
        
        if deleted_count == 0:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")
        
        return {
            "success": True,
            "message": f"Deleted document {doc_id}",
            "chunks_deleted": deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete document", doc_id=doc_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")


class ProductsBySkusRequest(BaseModel):
    """Request for fetching products by SKUs."""
    skus: List[str] = Field(..., description="List of product SKUs to fetch")
    agent_id: str = Field(..., description="Agent ID to determine brand database")


@router.post("/products/by-skus")
async def get_products_by_skus(
    request: ProductsBySkusRequest,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """
    Fetch full product details by SKUs from the knowledge base.
    
    This endpoint is used by the widget to build product cards from
    <product_info> tags that contain only product_sku.
    """
    try:
        from ....connections import connection_manager
        
        # Get agent configuration to find brand
        agents_collection = connection_manager.system_db['agents']
        agent = await agents_collection.find_one({'id': request.agent_id})
        
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent not found: {request.agent_id}")
        
        brand_slug = agent.get('brand_slug')
        if not brand_slug:
            raise HTTPException(status_code=400, detail="Agent has no brand_slug configured")
        
        # Get brand database using connection manager helper
        try:
            # connection_manager.get_brand_db uses cached MongoDB client and returns a Database
            brand_db = connection_manager.get_brand_db(brand_slug)
        except Exception:
            # Fallback to direct mongodb client if available
            mongo_client = getattr(connection_manager, 'mongodb_client', None)
            if mongo_client is None:
                raise HTTPException(status_code=500, detail="MongoDB client not available")
            brand_db = mongo_client[brand_slug]

        kb_collection = brand_db['knowledge_base']
        
        # Fetch products by SKUs
        products = []
        cursor = kb_collection.find({
            'content_type': 'product',
            'product_data.sku': {'$in': request.skus}
        })
        
        async for doc in cursor:
            product_data = doc.get('product_data', {})
            if product_data and product_data.get('sku'):
                products.append({
                    'sku': product_data.get('sku'),
                    'name': product_data.get('name', 'Unknown Product'),
                    'price': product_data.get('price', 0),
                    'currency': product_data.get('currency', 'INR'),
                    'category': product_data.get('category', 'Uncategorized'),
                    'in_stock': product_data.get('in_stock', True),
                    'features': product_data.get('features', []),
                    'image_url': product_data.get('image_url'),
                    'product_url': product_data.get('product_url')
                })
        
        logger.info(
            "Fetched products by SKUs",
            agent_id=request.agent_id,
            brand_slug=brand_slug,
            requested_skus=len(request.skus),
            found_products=len(products)
        )
        
        return {
            "success": True,
            "products": products,
            "count": len(products)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to fetch products by SKUs", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch products: {str(e)}")
