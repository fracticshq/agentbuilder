"""
Knowledge Base API Endpoints - Enhanced with Structured Metadata
Supports both document uploads and bulk JSON imports with product/dealer data
"""

import re
import json
from typing import Any, Dict, List, Optional, Literal
from urllib.parse import urlsplit, urlunsplit
from fastapi import APIRouter, UploadFile, File, Form, Depends, Header, HTTPException, Body
from pydantic import BaseModel, Field
import structlog

from ....dependencies import get_ingestion_service, get_settings, get_knowledge_service
from ....auth.dependencies import ensure_brand_access, ensure_permission, require_dashboard_access
from ....auth.models import Permission, User
from ....connections import connection_manager
from ....services.knowledge_service import KnowledgeService
from ....services.ingestion_service import (
    IngestionIdempotencyConflictError,
    IngestionService,
    InvalidIngestionInputError,
)
from ....services.ingestion_payload_store import IngestionPayloadStoreError
from ....services.job_store import JobStoreUnavailableError
from ....security.malware_scanner import MalwareDetectedError, MalwareScannerUnavailableError

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(require_dashboard_access)])


def _authorize_brand(current_user: User | None, brand_id: str, permission: Permission) -> None:
    """Enforce document permission and tenant scope before touching a brand DB."""
    ensure_permission(current_user, permission)
    ensure_brand_access(current_user, brand_id)


async def _canonical_brand_id(system_db: Any, identifier: str) -> str:
    """Resolve a brand ID or slug to its canonical ID for scope comparison."""
    brand = await system_db.brands.find_one({
        "$or": [
            {"id": identifier},
            {"slug": identifier},
        ]
    })
    return str(brand.get("id") or identifier) if brand else identifier


async def _authorize_brand_agent_scope(
    current_user: User | None,
    brand_id: str,
    agent_id: Optional[str],
    permission: Permission,
) -> None:
    """Authorize a brand and, when present, bind the agent to that exact tenant.

    Knowledge APIs retain support for callers that use a brand slug, but the
    agent's canonical brand record remains the authority.  This prevents a
    valid tenant user from using another tenant's agent ID to scope a write or
    read inside their own brand database.
    """
    ensure_permission(current_user, permission)
    if not agent_id:
        ensure_brand_access(current_user, brand_id)
        return

    system_db = connection_manager.get_system_db()
    requested_brand_id = await _canonical_brand_id(system_db, brand_id)
    ensure_brand_access(current_user, requested_brand_id)

    agent = await system_db.agents.find_one({"id": agent_id})
    if not agent or not agent.get("brand_id"):
        raise HTTPException(status_code=404, detail="Agent not found")

    agent_brand_id = await _canonical_brand_id(system_db, str(agent["brand_id"]))
    if agent_brand_id != requested_brand_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Authorize the canonical agent scope as well as the caller-supplied alias.
    ensure_brand_access(current_user, agent_brand_id)


async def _resolve_durable_knowledge_scope(
    current_user: User | None,
    brand_identifier: str,
    agent_id: Optional[str],
    permission: Permission,
) -> dict[str, str | None]:
    """Resolve the immutable brand/agent snapshot needed by a durable job."""
    system_db = connection_manager.get_system_db()
    brand = await system_db.brands.find_one({"$or": [{"id": brand_identifier}, {"slug": brand_identifier}]})
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    brand_id = brand.get("id")
    brand_slug = brand.get("slug")
    if not isinstance(brand_id, str) or not brand_id or not isinstance(brand_slug, str) or not brand_slug:
        raise HTTPException(status_code=400, detail="Brand does not have a complete durable scope")
    ensure_permission(current_user, permission)
    ensure_brand_access(current_user, brand_id)
    if agent_id:
        agent = await system_db.agents.find_one({"id": agent_id}, {"brand_id": 1, "brand_slug": 1})
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if agent.get("brand_id") != brand_id or agent.get("brand_slug") != brand_slug:
            raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent_id": agent_id, "brand_id": brand_id, "brand_slug": brand_slug}


# ============================================================================
# Request/Response Models
# ============================================================================

class ProductData(BaseModel):
    """Structured product metadata."""
    sku: str = Field(..., description="Product SKU/ID (unique identifier)")
    name: str = Field(..., description="Product name/title")
    price: int = Field(..., description="Price in smallest currency unit (e.g., paise, cents)")
    currency: Optional[str] = Field(None, description="Currency code (e.g., INR, USD)")
    currency_source: Optional[Literal["shopify_store", "presentment", "catalog", "configured_default", "missing"]] = None
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
    currency_source: Optional[Literal["shopify_store", "presentment", "catalog", "configured_default", "missing"]] = None
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
    agent_id: Optional[str] = None
    folder_path: Optional[str] = None


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
    file: UploadFile = File(...),
    content_type: str = Form("guide"),
    brand_id: str = Form("default"),
    agent_id: Optional[str] = Form(None),
    folder_path: Optional[str] = Form(None),
    product_data: Optional[str] = Form(None),  # JSON string
    dealer_data: Optional[str] = Form(None),   # JSON string
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    current_user: User | None = Depends(require_dashboard_access),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
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

        if content_type not in {"product", "dealer", "faq", "office", "category", "guide", "document"}:
            raise HTTPException(status_code=422, detail="Unsupported knowledge content type")

        # Resolve and snapshot canonical scope before the source bytes are
        # persisted. No background task is allowed to retain request memory.
        scope = await _resolve_durable_knowledge_scope(
            current_user, brand_id, agent_id, Permission.DOCUMENT_WRITE
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

        normalized_product_data = None
        if parsed_product_data:
            configured_default_currency = await knowledge_service._resolve_configured_default_currency(
                str(scope["brand_id"]), scope
            )
            currency, currency_source = knowledge_service._resolve_item_currency(
                parsed_product_data,
                configured_default_currency,
            )
            normalized_product_data = parsed_product_data.model_dump(exclude_none=True)
            normalized_product_data["currency"] = currency
            normalized_product_data["currency_source"] = currency_source
        context = {
            "kb_content_type": content_type,
            "folder_path": folder_path or "/",
            **({"product_data": normalized_product_data} if normalized_product_data else {}),
            **({"dealer_data": parsed_dealer_data.model_dump(exclude_none=True)} if parsed_dealer_data else {}),
        }
        chunk_size, chunk_overlap = ingestion_service.snapshot_chunking_from_agent(
            {"configuration": {}} if not scope["agent_id"] else await connection_manager.get_system_db().agents.find_one({"id": scope["agent_id"]}) or {}
        )
        job_id = await ingestion_service.submit_durable_job(
            [{
                "content": content,
                "filename": file.filename or "upload",
                "content_type": file.content_type or "application/octet-stream",
                "context": context,
            }],
            agent_id=scope["agent_id"],
            brand_id=str(scope["brand_id"]),
            brand_slug=str(scope["brand_slug"]),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            idempotency_key=idempotency_key,
            job_metadata={"submission_kind": "knowledge_document", "items_count": 1},
        )
        
        logger.info(
            "Document upload started",
            job_id=job_id,
            filename=file.filename,
            content_type=content_type,
            brand_id=scope["brand_id"],
            agent_id=scope["agent_id"],
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
            status="pending"
        )
        
    except HTTPException:
        raise
    except IngestionIdempotencyConflictError:
        raise HTTPException(status_code=409, detail="Idempotency key was already used for a different upload")
    except MalwareDetectedError:
        raise HTTPException(status_code=422, detail="Upload rejected by malware scanning policy")
    except MalwareScannerUnavailableError:
        raise HTTPException(status_code=503, detail="Upload scanning is temporarily unavailable")
    except InvalidIngestionInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (JobStoreUnavailableError, IngestionPayloadStoreError):
        raise HTTPException(status_code=503, detail="Knowledge ingestion is temporarily unavailable")
    except Exception as exc:
        logger.error("knowledge_document_submission_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Document upload failed")


@router.post("/bulk-upload", response_model=UploadResponse)
async def bulk_upload_json(
    request: BulkUploadRequest = Body(...),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
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
        scope = await _resolve_durable_knowledge_scope(
            current_user, request.brand_id, request.agent_id, Permission.DOCUMENT_WRITE
        )
        # Validate items based on content_type
        if request.content_type == "product":
            for i, item in enumerate(request.items):
                missing = []
                # Convert to dict for easier validation
                item_dict = item.model_dump() if hasattr(item, "model_dump") else item
                
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
                item_dict = item.model_dump() if hasattr(item, "model_dump") else item
                
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
        
        configured_default_currency = await knowledge_service._resolve_configured_default_currency(
            str(scope["brand_id"]), scope
        ) if request.content_type == "product" else None
        normalized_items = []
        for item in request.items:
            normalized_item = item.model_dump(exclude_none=True)
            if request.content_type == "product":
                currency, currency_source = knowledge_service._resolve_item_currency(item, configured_default_currency)
                normalized_item["currency"] = currency
                normalized_item["currency_source"] = currency_source
            normalized_items.append(normalized_item)
        serialized_items = json.dumps(
            normalized_items,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        max_file_bytes = get_settings().MAX_FILE_SIZE_MB * 1024 * 1024
        if len(serialized_items) > max_file_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Bulk upload exceeds the {get_settings().MAX_FILE_SIZE_MB}MB upload limit",
            )
        chunk_size, chunk_overlap = ingestion_service.snapshot_chunking_from_agent(
            {"configuration": {}} if not scope["agent_id"] else await connection_manager.get_system_db().agents.find_one({"id": scope["agent_id"]}) or {}
        )
        job_id = await ingestion_service.submit_durable_job(
            [{
                "content": serialized_items,
                "filename": f"bulk-{request.content_type}.json",
                "content_type": "application/json",
                "context": {
                    "kb_content_type": request.content_type,
                    "folder_path": request.folder_path or "/",
                },
            }],
            agent_id=scope["agent_id"],
            brand_id=str(scope["brand_id"]),
            brand_slug=str(scope["brand_slug"]),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            idempotency_key=idempotency_key,
            job_metadata={"submission_kind": "knowledge_bulk", "items_count": len(request.items)},
        )
        
        logger.info(
            "Bulk upload started",
            job_id=job_id,
            content_type=request.content_type,
            items_count=len(request.items),
            brand_id=scope["brand_id"],
        )
        
        return UploadResponse(
            success=True,
            job_id=job_id,
            message=f"Bulk upload started: {len(request.items)} {request.content_type}s",
            items_count=len(request.items),
            status="pending"
        )
        
    except HTTPException:
        raise
    except IngestionIdempotencyConflictError:
        raise HTTPException(status_code=409, detail="Idempotency key was already used for a different upload")
    except MalwareDetectedError:
        raise HTTPException(status_code=422, detail="Upload rejected by malware scanning policy")
    except MalwareScannerUnavailableError:
        raise HTTPException(status_code=503, detail="Upload scanning is temporarily unavailable")
    except InvalidIngestionInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (JobStoreUnavailableError, IngestionPayloadStoreError):
        raise HTTPException(status_code=503, detail="Knowledge ingestion is temporarily unavailable")
    except Exception as exc:
        logger.error("knowledge_bulk_submission_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Bulk upload failed")


@router.get("/tree")
async def get_knowledge_tree(
    brand_id: str,
    agent_id: Optional[str] = None,
    folder: Optional[str] = None,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Return a filesystem-style folder/file tree for the knowledge base."""
    try:
        await _authorize_brand_agent_scope(
            current_user, brand_id, agent_id, Permission.DOCUMENT_READ
        )
        tree = await knowledge_service.list_knowledge_tree(
            brand_id=brand_id,
            agent_id=agent_id,
            folder=folder,
        )
        return {"success": True, **tree}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get knowledge tree", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get knowledge tree: {str(e)}")


@router.post("/folders")
async def create_folder(
    request: FolderCreateRequest,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Create or ensure a knowledge folder."""
    try:
        await _authorize_brand_agent_scope(
            current_user, request.brand_id, request.agent_id, Permission.DOCUMENT_WRITE
        )
        folder = await knowledge_service.create_folder(
            brand_id=request.brand_id,
            path=request.path or knowledge_service.folder_path_from_name(
                name=request.name,
                parent_path=request.parent_path,
            ),
            agent_id=request.agent_id,
        )
        return {"success": True, "folder": folder}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to create knowledge folder", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create folder: {str(e)}")


@router.patch("/items/move")
async def move_knowledge_item_by_body(
    request: KnowledgeMoveRequest,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Move a knowledge item (file or folder) — id carried in the body so folder
    paths with slashes route correctly."""
    if not request.item_id:
        raise HTTPException(status_code=400, detail="item_id is required")
    try:
        await _authorize_brand_agent_scope(
            current_user, request.brand_id, request.agent_id, Permission.DOCUMENT_WRITE
        )
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
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Rename a knowledge item (file or folder) — id carried in the body."""
    if not request.item_id:
        raise HTTPException(status_code=400, detail="item_id is required")
    try:
        await _authorize_brand_agent_scope(
            current_user, request.brand_id, request.agent_id, Permission.DOCUMENT_WRITE
        )
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
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Delete a knowledge item (file or folder) — id in query so folder paths
    with slashes route correctly. Folders reparent their documents to the parent."""
    try:
        await _authorize_brand_agent_scope(
            current_user, brand_id, agent_id, Permission.DOCUMENT_DELETE
        )
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
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Move a knowledge item to another folder (legacy path-param route)."""
    try:
        await _authorize_brand_agent_scope(
            current_user, request.brand_id, request.agent_id, Permission.DOCUMENT_WRITE
        )
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
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Rename a knowledge file or folder."""
    try:
        await _authorize_brand_agent_scope(
            current_user, request.brand_id, request.agent_id, Permission.DOCUMENT_WRITE
        )
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
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Delete a knowledge item and its chunks (legacy path-param route)."""
    try:
        _authorize_brand(current_user, brand_id, Permission.DOCUMENT_DELETE)
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
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Run an admin retrieval preview across all knowledge or a selected folder."""
    try:
        await _authorize_brand_agent_scope(
            current_user, request.brand_id, request.agent_id, Permission.DOCUMENT_READ
        )
        chunks = await knowledge_service.retrieve(
            brand_id=request.brand_id,
            query=request.query,
            folder=request.folder or request.folder_path,
            agent_id=request.agent_id,
            limit=request.top_k or request.limit,
            score_threshold=request.score_threshold,
        )
        return {"success": True, "query": request.query, "chunks": chunks, "results": chunks, "count": len(chunks)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to retrieve knowledge", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to retrieve knowledge: {str(e)}")


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """
    Get the status of an upload job.
    
    Returns:
    - status: pending, processing, completed, error
    - progress: details about what's been processed
    - error: error message if status is 'error'
    """
    try:
        job = await knowledge_service.job_store.get(job_id)
        if not job or not job.get("brand_id"):
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        _authorize_brand(current_user, str(job["brand_id"]), Permission.DOCUMENT_READ)
        if job.get("queue_version") == 2:
            internal_status = str(job.get("status") or "error")
            public_status = {
                "queued": "pending",
                "running": "processing",
                "publishing": "processing",
                "cancelled": "error",
            }.get(internal_status, internal_status)
            items_count = int(job.get("items_count") or job.get("files_count") or 0)
            progress = {
                "type": job.get("submission_kind") or "document",
                # A durable worker stages source files atomically and publishes
                # deterministic chunks. Before completion, items are not yet
                # visible, so do not report partially published product data.
                "processed_items": items_count if public_status == "completed" else 0,
                "total_items": items_count,
                "processed_chunks": 0,
                "total_chunks": 0,
            }
            return JobStatusResponse(
                job_id=job_id,
                status=public_status if public_status in {"pending", "processing", "completed", "error"} else "error",
                progress=progress,
                error="Document processing failed" if public_status == "error" else None,
            )
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
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
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
        _authorize_brand(current_user, brand_id, Permission.DOCUMENT_READ)
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to list documents", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")


@router.get("/documents/{doc_id}/preview")
async def get_document_preview(
    doc_id: str,
    brand_id: str,
    limit: int = 8,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """
    Fetch source metadata and sample chunks/items for preview.

    Query parameters:
    - brand_id: Brand/agent ID or slug for authorization and DB resolution
    - limit: Maximum number of sample chunks/items to return
    """
    try:
        _authorize_brand(current_user, brand_id, Permission.DOCUMENT_READ)
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


@router.post(
    "/documents/{doc_id}/reindex",
    response_model=UploadResponse,
    responses={
        400: {"description": "Invalid durable re-index request"},
        404: {"description": "Brand, agent, or document not found"},
        409: {"description": "Idempotency key conflicts with another re-index request"},
        503: {"description": "Durable job storage is temporarily unavailable"},
    },
)
async def reindex_document(
    doc_id: str,
    brand_id: str,
    agent_id: Optional[str] = None,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    current_user: User | None = Depends(require_dashboard_access),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Queue a durable in-place vector refresh for one document/job batch.

    Re-indexing re-embeds already published chunks under their current logical
    IDs. It does not re-upload source bytes or duplicate the document, and it
    does not report terminal success until every target chunk is refreshed.
    """
    try:
        scope = await _resolve_durable_knowledge_scope(
            current_user, brand_id, agent_id, Permission.DOCUMENT_WRITE
        )
        preview = await knowledge_service.get_document_preview(
            doc_id,
            str(scope["brand_id"]),
            limit=1,
        )
        if not preview:
            raise HTTPException(status_code=404, detail="Document not found")
        chunk_size, chunk_overlap = ingestion_service.snapshot_chunking_from_agent(
            {"configuration": {}}
            if not scope["agent_id"]
            else await connection_manager.get_system_db().agents.find_one({"id": scope["agent_id"]}) or {}
        )
        job_id = await ingestion_service.submit_reindex_job(
            document_id=doc_id,
            agent_id=scope["agent_id"],
            brand_id=str(scope["brand_id"]),
            brand_slug=str(scope["brand_slug"]),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            idempotency_key=idempotency_key,
        )
        return UploadResponse(
            success=True,
            job_id=job_id,
            message="Knowledge re-index queued",
            items_count=1,
            status="pending",
        )
    except HTTPException:
        raise
    except IngestionIdempotencyConflictError:
        raise HTTPException(status_code=409, detail="Idempotency key was already used for a different re-index request")
    except InvalidIngestionInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except JobStoreUnavailableError:
        raise HTTPException(status_code=503, detail="Knowledge re-indexing is temporarily unavailable")
    except Exception as exc:
        logger.error("knowledge_reindex_submission_failed", doc_id=doc_id, error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Knowledge re-index request failed")


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    brand_id: str,
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """
    Delete a document and all its chunks.
    
    Path parameters:
    - doc_id: Document ID to delete
    
    Query parameters:
    - brand_id: Brand/agent ID for authorization
    """
    try:
        _authorize_brand(current_user, brand_id, Permission.DOCUMENT_DELETE)
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
        "price_minor": product_data.get("price_minor", product_data.get("price", 0)),
        "price_unit": "minor",
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
        "price_minor": product.get("price_minor", product.get("price")),
        "price_unit": "minor",
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
            cursor = kb_collection.find({
                "content_type": "product",
                "product_data.source_active": {"$ne": False},
                "metadata.catalog_source.active": {"$ne": False},
                **query,
            })
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
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    current_user: User | None = Depends(require_dashboard_access),
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

        ensure_permission(current_user, Permission.DOCUMENT_READ)
        ensure_brand_access(current_user, agent.get("brand_id"))
        
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
            'product_data.sku': {'$in': request.skus},
            'product_data.source_active': {'$ne': False},
            'metadata.catalog_source.active': {'$ne': False},
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
