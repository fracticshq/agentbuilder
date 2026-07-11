"""
Knowledge Base API Endpoints - Enhanced with Structured Metadata
Supports both document uploads and bulk JSON imports with product/dealer data
"""

import re
from typing import Any, Dict, List, Optional, Literal
from urllib.parse import urlsplit, urlunsplit
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks, Body
from pydantic import BaseModel, Field
import structlog

from ....dependencies import get_settings, get_knowledge_service
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
    currency: Optional[str] = Field(None, description="Currency code (e.g., INR, USD)")
    currency_source: Optional[Literal["catalog", "configured_default", "missing"]] = None
    category: str = Field(..., description="Product category")
    image_url: Optional[str] = Field(None, description="Product image URL")
    product_url: Optional[str] = Field(None, description="Product page URL")
    in_stock: Optional[bool] = Field(True, description="Stock availability")
    features: Optional[List[str]] = Field(default_factory=list, description="Product features/tags")
    product_group_id: Optional[str] = None
    handle: Optional[str] = None
    parent_name: Optional[str] = None
    has_variants: Optional[bool] = None
    variant_count: Optional[int] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    default_variant_id: Optional[str] = None
    variant_id: Optional[str] = None
    variant_sku: Optional[str] = None
    variant_title: Optional[str] = None
    variant_options: Optional[dict] = Field(default_factory=dict)
    variant_url: Optional[str] = None


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
    currency_source: Optional[Literal["catalog", "configured_default", "missing"]] = None
    category: Optional[str] = None
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    in_stock: Optional[bool] = None
    features: Optional[List[str]] = None
    product_group_id: Optional[str] = None
    handle: Optional[str] = None
    parent_name: Optional[str] = None
    has_variants: Optional[bool] = None
    variant_count: Optional[int] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    default_variant_id: Optional[str] = None
    variant_id: Optional[str] = None
    variant_sku: Optional[str] = None
    variant_title: Optional[str] = None
    variant_options: Optional[dict] = Field(default_factory=dict)
    variant_url: Optional[str] = None
    
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


class FolderCreateRequest(BaseModel):
    brand_id: str
    path: Optional[str] = None
    name: Optional[str] = None
    parent_path: Optional[str] = None
    agent_id: Optional[str] = None


class KnowledgeMoveRequest(BaseModel):
    brand_id: str
    # item_id may carry a slash (folder paths like "/Guides"), so it travels in
    # the body, not the URL path, to avoid path-param routing breakage.
    item_id: Optional[str] = None
    target_folder: Optional[str] = None
    folder_path: Optional[str] = None
    agent_id: Optional[str] = None


class KnowledgeRenameRequest(BaseModel):
    brand_id: str
    item_id: Optional[str] = None
    name: str
    agent_id: Optional[str] = None


class KnowledgeRetrieveRequest(BaseModel):
    brand_id: str
    query: str = Field(..., min_length=1)
    folder: Optional[str] = None
    folder_path: Optional[str] = None
    agent_id: Optional[str] = None
    limit: int = Field(10, ge=1, le=50)
    top_k: Optional[int] = Field(None, ge=1, le=50)
    score_threshold: float = Field(0.0, ge=0.0, le=1.0)


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    content_type: str = Form("guide"),
    brand_id: str = Form("default"),
    agent_id: Optional[str] = Form(None),
    folder_path: Optional[str] = Form(None),
    product_data: Optional[str] = Form(None),  # JSON string
    dealer_data: Optional[str] = Form(None),   # JSON string
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """
    Upload a single document with structured metadata.
    
    Supports:
    - PDF, DOCX, TXT, MD, HTML, JSON, CSV files
    - Content types: product, dealer, faq, office, category, guide
    - Structured metadata for products and dealers
    
    The document will be:
    1. Parsed and chunked
    2. Embedded using Voyage AI
    3. Stored in MongoDB with structured metadata
    """
    try:
        source_type = knowledge_service.detect_source_type(file.content_type, file.filename or "")

        if not source_type:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported file type: {file.content_type or 'unknown'}. "
                    "Allowed: PDF, DOCX, TXT, MD, HTML, JSON, CSV"
                )
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

        max_file_bytes = get_settings().MAX_FILE_SIZE_MB * 1024 * 1024
        if len(content) > max_file_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File {file.filename} exceeds the {get_settings().MAX_FILE_SIZE_MB}MB upload limit"
            )

        # Start ingestion job
        job_id = await knowledge_service.start_document_upload(
            content=content,
            filename=file.filename,
            content_type_header=file.content_type,
            kb_content_type=content_type,
            brand_id=brand_id,
            agent_id=agent_id,
            product_data=parsed_product_data,
            dealer_data=parsed_dealer_data,
            folder_path=folder_path,
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
            agent_id=agent_id,
            product_data=parsed_product_data,
            dealer_data=parsed_dealer_data,
            folder_path=folder_path,
        )
        
        logger.info(
            "Document upload started",
            job_id=job_id,
            filename=file.filename,
            content_type=content_type,
            brand_id=brand_id,
            agent_id=agent_id,
            folder_path=folder_path,
            source_type=source_type,
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
    - Products: Must have sku, name, price, category. Currency is optional and may come from commerce config.
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
          "currency": "USD",
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


@router.get("/tree")
async def get_knowledge_tree(
    brand_id: str,
    agent_id: Optional[str] = None,
    folder: Optional[str] = None,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """Return a filesystem-style folder/file tree for the knowledge base."""
    try:
        tree = await knowledge_service.list_knowledge_tree(
            brand_id=brand_id,
            agent_id=agent_id,
            folder=folder,
        )
        return {"success": True, **tree}
    except Exception as e:
        logger.error("Failed to get knowledge tree", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get knowledge tree: {str(e)}")


@router.post("/folders")
async def create_folder(
    request: FolderCreateRequest,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """Create or ensure a knowledge folder."""
    try:
        folder = await knowledge_service.create_folder(
            brand_id=request.brand_id,
            path=request.path or knowledge_service.folder_path_from_name(
                name=request.name,
                parent_path=request.parent_path,
            ),
            agent_id=request.agent_id,
        )
        return {"success": True, "folder": folder}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to create knowledge folder", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create folder: {str(e)}")


@router.patch("/items/move")
async def move_knowledge_item_by_body(
    request: KnowledgeMoveRequest,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """Move a knowledge item (file or folder) — id carried in the body so folder
    paths with slashes route correctly."""
    if not request.item_id:
        raise HTTPException(status_code=400, detail="item_id is required")
    try:
        item = await knowledge_service.move_item(
            brand_id=request.brand_id,
            item_id=request.item_id,
            target_folder=request.target_folder or request.folder_path or "/",
            agent_id=request.agent_id,
        )
        if not item:
            raise HTTPException(status_code=404, detail=f"Knowledge item not found: {request.item_id}")
        return {"success": True, "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to move knowledge item", item_id=request.item_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to move item: {str(e)}")


@router.patch("/items/rename")
async def rename_knowledge_item_by_body(
    request: KnowledgeRenameRequest,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """Rename a knowledge item (file or folder) — id carried in the body."""
    if not request.item_id:
        raise HTTPException(status_code=400, detail="item_id is required")
    try:
        item = await knowledge_service.rename_item(
            brand_id=request.brand_id,
            item_id=request.item_id,
            name=request.name,
            agent_id=request.agent_id,
        )
        if not item:
            raise HTTPException(status_code=404, detail=f"Knowledge item not found: {request.item_id}")
        return {"success": True, "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to rename knowledge item", item_id=request.item_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to rename item: {str(e)}")


@router.delete("/items")
async def delete_knowledge_item_by_query(
    item_id: str,
    brand_id: str,
    agent_id: Optional[str] = None,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """Delete a knowledge item (file or folder) — id in query so folder paths
    with slashes route correctly. Folders reparent their documents to the parent."""
    try:
        result = await knowledge_service.delete_item(item_id, brand_id=brand_id, agent_id=agent_id)
        if not result.get("deleted"):
            raise HTTPException(status_code=404, detail=f"Knowledge item not found: {item_id}")
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete knowledge item", item_id=item_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to delete item: {str(e)}")


@router.patch("/items/{item_id}/move")
async def move_knowledge_item(
    item_id: str,
    request: KnowledgeMoveRequest,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """Move a knowledge item to another folder (legacy path-param route)."""
    try:
        item = await knowledge_service.move_item(
            brand_id=request.brand_id,
            item_id=item_id,
            target_folder=request.target_folder or request.folder_path or "/",
            agent_id=request.agent_id,
        )
        if not item:
            raise HTTPException(status_code=404, detail=f"Knowledge item not found: {item_id}")
        return {"success": True, "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to move knowledge item", item_id=item_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to move item: {str(e)}")


@router.patch("/items/{item_id}/rename")
async def rename_knowledge_item(
    item_id: str,
    request: KnowledgeRenameRequest,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """Rename a knowledge file or folder."""
    try:
        item = await knowledge_service.rename_item(
            brand_id=request.brand_id,
            item_id=item_id,
            name=request.name,
            agent_id=request.agent_id,
        )
        if not item:
            raise HTTPException(status_code=404, detail=f"Knowledge item not found: {item_id}")
        return {"success": True, "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to rename knowledge item", item_id=item_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to rename item: {str(e)}")


@router.delete("/items/{item_id}")
async def delete_knowledge_item(
    item_id: str,
    brand_id: str,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """Delete a knowledge item and its chunks (legacy path-param route)."""
    try:
        result = await knowledge_service.delete_item(item_id, brand_id=brand_id)
        if not result.get("deleted"):
            raise HTTPException(status_code=404, detail=f"Knowledge item not found: {item_id}")
        return {"success": True, "message": f"Deleted knowledge item {item_id}", **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete knowledge item", item_id=item_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to delete item: {str(e)}")


@router.post("/retrieve")
async def retrieve_knowledge(
    request: KnowledgeRetrieveRequest,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """Run an admin retrieval preview across all knowledge or a selected folder."""
    try:
        chunks = await knowledge_service.retrieve(
            brand_id=request.brand_id,
            query=request.query,
            folder=request.folder or request.folder_path,
            agent_id=request.agent_id,
            limit=request.top_k or request.limit,
            score_threshold=request.score_threshold,
        )
        return {"success": True, "query": request.query, "chunks": chunks, "results": chunks, "count": len(chunks)}
    except Exception as e:
        logger.error("Failed to retrieve knowledge", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to retrieve knowledge: {str(e)}")


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


@router.get("/documents/{doc_id}/preview")
async def get_document_preview(
    doc_id: str,
    brand_id: str,
    limit: int = 8,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """
    Fetch source metadata and sample chunks/items for preview.

    Query parameters:
    - brand_id: Brand/agent ID or slug for authorization and DB resolution
    - limit: Maximum number of sample chunks/items to return
    """
    try:
        preview = await knowledge_service.get_document_preview(
            doc_id=doc_id,
            brand_id=brand_id,
            limit=limit,
        )

        if not preview:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

        return {
            "success": True,
            "document": preview,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to preview document", doc_id=doc_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to preview document: {str(e)}")


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


def _base_product_url(url: Any) -> Optional[str]:
    if url in (None, ""):
        return None
    try:
        parts = urlsplit(str(url))
        if not parts.scheme or not parts.netloc:
            return re.sub(r"\?.*$", "", str(url)).rstrip("/")
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except Exception:
        return re.sub(r"\?.*$", "", str(url)).rstrip("/")


def _product_group_key(product: Dict[str, Any]) -> Optional[str]:
    for key in ("product_group_id", "product_id", "handle"):
        value = product.get(key)
        if value not in (None, ""):
            return f"{key}:{str(value).strip().lower()}"
    base_url = _base_product_url(product.get("product_url") or product.get("url") or product.get("variant_url"))
    if base_url:
        return f"url:{base_url.lower()}"
    return None


def _variant_identity(product: Dict[str, Any]) -> Optional[str]:
    for key in ("variant_id", "variant_sku", "sku", "variant_url", "id"):
        value = product.get(key)
        if value not in (None, ""):
            return re.sub(r"\s+", " ", str(value).strip().lower())
    return None


def _product_card_from_data(product_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sku": product_data.get("sku"),
        "name": product_data.get("parent_name") or product_data.get("name", "Unknown Product"),
        "price": product_data.get("price", 0),
        "currency": product_data.get("currency"),
        "currency_source": product_data.get("currency_source", "missing"),
        "category": product_data.get("category", "Uncategorized"),
        "in_stock": product_data.get("in_stock", True),
        "features": product_data.get("features", []),
        "image_url": product_data.get("image_url"),
        "image": product_data.get("image"),
        "product_url": product_data.get("product_url") or product_data.get("url"),
        "url": product_data.get("url") or product_data.get("product_url"),
        "product_group_id": product_data.get("product_group_id"),
        "product_id": product_data.get("product_id"),
        "handle": product_data.get("handle"),
        "parent_name": product_data.get("parent_name"),
        "has_variants": product_data.get("has_variants"),
        "variant_count": product_data.get("variant_count"),
        "price_min": product_data.get("price_min"),
        "price_max": product_data.get("price_max"),
        "default_variant_id": product_data.get("default_variant_id"),
        "variant_id": product_data.get("variant_id"),
        "variant_sku": product_data.get("variant_sku"),
        "variant_title": product_data.get("variant_title"),
        "variant_options": product_data.get("variant_options") or {},
        "variant_url": product_data.get("variant_url"),
    }


def _variant_from_product(product: Dict[str, Any], selected: Dict[str, Any]) -> Dict[str, Any]:
    variant_options = product.get("variant_options")
    if not isinstance(variant_options, dict):
        variant_options = {}
    return {
        "id": product.get("variant_id") or product.get("sku"),
        "variant_id": product.get("variant_id") or product.get("sku"),
        "sku": product.get("variant_sku") or product.get("sku"),
        "variant_sku": product.get("variant_sku") or product.get("sku"),
        "name": product.get("name"),
        "title": product.get("variant_title") or product.get("name"),
        "variant_title": product.get("variant_title"),
        "variant_options": variant_options,
        "price": product.get("price"),
        "currency": product.get("currency"),
        "currency_source": product.get("currency_source"),
        "image_url": product.get("image_url") or product.get("image"),
        "image": product.get("image") or product.get("image_url"),
        "product_url": product.get("product_url") or product.get("url"),
        "variant_url": product.get("variant_url") or product.get("product_url") or product.get("url"),
        "in_stock": product.get("in_stock", True),
        "is_default": _variant_identity(product) == _variant_identity(selected),
    }


def _variant_group_queries(product: Dict[str, Any]) -> List[Dict[str, Any]]:
    queries: List[Dict[str, Any]] = []
    for key in ("product_group_id", "product_id", "handle"):
        value = product.get(key)
        if value not in (None, ""):
            queries.append({f"product_data.{key}": value})
    base_url = _base_product_url(product.get("product_url") or product.get("url") or product.get("variant_url"))
    if base_url:
        escaped = re.escape(base_url.rstrip("/"))
        queries.append({
            "$or": [
                {"product_data.product_url": base_url},
                {"product_data.url": base_url},
                {"product_data.variant_url": {"$regex": rf"^{escaped}(?:/)?(?:\?.*)?$"}},
            ]
        })
    return queries


async def _hydrate_product_cards(kb_collection: Any, products: List[Dict[str, Any]], max_variants: int = 100) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for index, product in enumerate(products):
        product["_variant_rank"] = index
        group_key = _product_group_key(product) or _variant_identity(product) or f"product:{index}"
        if group_key not in grouped:
            grouped[group_key] = []
            order.append(group_key)
        grouped[group_key].append(product)

    hydrated_products: List[Dict[str, Any]] = []
    for group_key in order:
        group_products = grouped[group_key]
        selected = sorted(
            group_products,
            key=lambda item: (
                int(item.get("_variant_rank") or 9999),
                0 if item.get("in_stock", True) else 1,
                float(item.get("price") or 10**18),
            ),
        )[0]
        siblings: List[Dict[str, Any]] = []
        for query in _variant_group_queries(selected):
            cursor = kb_collection.find({"content_type": "product", **query})
            async for doc in cursor:
                product_data = doc.get("product_data", {})
                if product_data and product_data.get("sku"):
                    siblings.append(_product_card_from_data(product_data))
                if len(siblings) >= max_variants:
                    break
            if siblings:
                break

        combined: List[Dict[str, Any]] = []
        seen = set()
        for product in [*group_products, *siblings]:
            identity = _variant_identity(product)
            if not identity or identity in seen:
                continue
            seen.add(identity)
            combined.append(product)

        combined = sorted(
            combined,
            key=lambda item: (
                0 if _variant_identity(item) == _variant_identity(selected) else 1,
                int(item.get("_variant_rank") or 9999),
                0 if item.get("in_stock", True) else 1,
                float(item.get("price") or 10**18),
                _variant_identity(item) or "",
            ),
        )
        variants = [_variant_from_product(product, selected) for product in combined]
        prices = [float(variant["price"]) for variant in variants if variant.get("price") not in (None, "")]
        card = dict(selected)
        card["name"] = selected.get("parent_name") or selected.get("name") or "Unknown Product"
        card["has_variants"] = len(variants) > 1 or bool(selected.get("has_variants"))
        card["variant_count"] = max(int(selected.get("variant_count") or 0), len(variants))
        card["variants"] = variants
        card["default_variant_id"] = selected.get("variant_id") or selected.get("default_variant_id") or selected.get("sku")
        if prices:
            card["price_min"] = min(prices)
            card["price_max"] = max(prices)
        card.pop("_variant_rank", None)
        hydrated_products.append(card)

    return hydrated_products


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

        commerce_config = ((agent.get("configuration") or {}).get("commerce") or {})
        retrieval_config = commerce_config.get("retrieval") if isinstance(commerce_config, dict) else {}
        try:
            max_variants = int((retrieval_config or {}).get("max_variants_per_card") or 100)
        except (TypeError, ValueError):
            max_variants = 100
        max_variants = max(1, min(max_variants, 500))
        
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
        matched_products = []
        cursor = kb_collection.find({
            'content_type': 'product',
            'product_data.sku': {'$in': request.skus}
        })
        
        async for doc in cursor:
            product_data = doc.get('product_data', {})
            if product_data and product_data.get('sku'):
                matched_products.append(_product_card_from_data(product_data))

        products = await _hydrate_product_cards(kb_collection, matched_products, max_variants=max_variants)
        
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
