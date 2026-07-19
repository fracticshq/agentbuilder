"""
Ingestion API Endpoints
"""

from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Depends, Header, HTTPException
from pydantic import BaseModel
import structlog

from commons.types.requests import IngestionRequest
from commons.types.responses import IngestionResponse, IngestionStatus
from ....dependencies import get_settings, get_ingestion_service
from ....services.ingestion_service import (
    IngestionIdempotencyConflictError,
    IngestionService,
    InvalidIngestionInputError,
)
from ....services.ingestion_payload_store import IngestionPayloadStoreError
from ....services.job_store import JobStoreUnavailableError
from ....auth.dependencies import ensure_brand_access, ensure_permission, require_dashboard_access
from ....auth.models import Permission, User
from ....connections import connection_manager

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(require_dashboard_access)])


class DocumentUploadResponse(BaseModel):
    """Response for document upload."""
    job_id: str
    status: str
    message: str
    documents_count: int


class ChunkRequest(BaseModel):
    """Request for manual chunk processing."""
    text: str
    metadata: dict = {}
    doc_id: Optional[str] = None
    agent_id: str


async def _authorize_agent(
    current_user: User | None,
    agent_id: str,
    permission: Permission,
) -> dict:
    """Resolve an agent before authorizing so tenant scope uses its canonical brand ID."""
    ensure_permission(current_user, permission)
    agent = await connection_manager.get_system_db().agents.find_one({"id": agent_id})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    ensure_brand_access(current_user, agent.get("brand_id"))
    return agent


async def _authorize_job(
    current_user: User | None,
    job_id: str,
    ingestion_service: IngestionService,
    permission: Permission,
) -> dict:
    """Authorize access to a job before returning or mutating its state."""
    job = await ingestion_service.job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job_brand_id = job.get("brand_id")
    if job_brand_id:
        # New jobs retain their creation-time tenant scope so an agent transfer
        # cannot grant a tenant access to another brand's historical jobs.
        ensure_permission(current_user, permission)
        ensure_brand_access(current_user, job_brand_id)
        return job
    agent_id = job.get("agent_id")
    if not agent_id:
        # Historical unscoped jobs cannot be safely exposed to a tenant user.
        raise HTTPException(status_code=404, detail="Job not found")
    await _authorize_agent(current_user, agent_id, permission)
    return job


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_documents(
    files: List[UploadFile] = File(...),
    agent_id: str = ...,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Upload and process documents for ingestion.
    
    Args:
        files: List of files to upload
        agent_id: Optional agent ID to associate with documents (query parameter)
        ingestion_service: Injected ingestion service
    """
    try:
        agent = await _authorize_agent(current_user, agent_id, Permission.DOCUMENT_WRITE)
        # Validate file types
        allowed_types = {
            "text/plain", "text/markdown", "application/pdf",
            "text/html", "application/json", "text/csv",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

        for file in files:
            if file.content_type not in allowed_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {file.content_type}"
                )

        # Read file contents before starting background task
        settings = get_settings()
        if len(files) > settings.MAX_UPLOAD_FILES:
            raise HTTPException(
                status_code=413,
                detail=f"Document upload exceeds the {settings.MAX_UPLOAD_FILES} file limit",
            )
        max_file_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        max_total_bytes = settings.MAX_UPLOAD_TOTAL_SIZE_MB * 1024 * 1024
        total_bytes = 0
        file_contents = []
        for file in files:
            content = await file.read()
            if len(content) > max_file_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File {file.filename} exceeds the {settings.MAX_FILE_SIZE_MB}MB upload limit"
                )
            total_bytes += len(content)
            if total_bytes > max_total_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Document upload exceeds the {settings.MAX_UPLOAD_TOTAL_SIZE_MB}MB aggregate limit",
                )
            file_contents.append({
                'content': content,
                'filename': file.filename,
                'content_type': file.content_type
            })
        
        brand_id = agent.get("brand_id")
        brand_slug = agent.get("brand_slug")
        if not isinstance(brand_id, str) or not brand_id or not isinstance(brand_slug, str) or not brand_slug:
            raise HTTPException(status_code=400, detail="Agent has no complete brand scope")
        # The authorized agent's brand and chunking configuration are snapshotted
        # at submission. No FastAPI background task retains request memory.
        chunk_size, chunk_overlap = ingestion_service.snapshot_chunking_from_agent(agent)
        job_id = await ingestion_service.submit_durable_job(
            file_contents,
            agent_id=agent_id,
            brand_id=brand_id,
            brand_slug=brand_slug,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            idempotency_key=idempotency_key,
        )
        logger.info("durable_document_upload_queued", job_id=job_id, files_count=len(files))
        
        return DocumentUploadResponse(
            job_id=job_id,
            status="pending",
            message="Documents uploaded and queued for processing",
            documents_count=len(files)
        )
        
    except HTTPException:
        raise
    except IngestionIdempotencyConflictError:
        raise HTTPException(status_code=409, detail="Idempotency key was already used for a different document upload")
    except InvalidIngestionInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (JobStoreUnavailableError, IngestionPayloadStoreError):
        raise HTTPException(status_code=503, detail="Document ingestion is temporarily unavailable")
    except Exception as e:
        # Never log parser/provider exceptions here: they can include portions
        # of an uploaded source. The worker logs only type and opaque job ID.
        logger.error("document_upload_submission_failed", error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail="Error uploading documents")


@router.post("/chunks", response_model=IngestionResponse)
async def process_chunk(
    request: ChunkRequest,
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Process a single text chunk."""
    try:
        await _authorize_agent(current_user, request.agent_id, Permission.DOCUMENT_WRITE)
        ingestion_request = IngestionRequest(
            text=request.text,
            metadata=request.metadata,
            doc_id=request.doc_id,
            chunk_size=None,
            chunk_overlap=None
        )
        
        response = await ingestion_service.process_chunk(ingestion_request, agent_id=request.agent_id)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ingestion_chunk_request_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Error processing chunk")


@router.get("/status/{job_id}", response_model=IngestionStatus)
async def get_ingestion_status(
    job_id: str,
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Get the status of an ingestion job."""
    try:
        await _authorize_job(current_user, job_id, ingestion_service, Permission.DOCUMENT_READ)
        status = await ingestion_service.get_job_status(job_id)
        if not status:
            raise HTTPException(status_code=404, detail="Job not found")
        return status
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ingestion_status_request_failed", job_id=job_id, error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Error getting job status")


@router.delete("/jobs/{job_id}")
async def cancel_ingestion_job(
    job_id: str,
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Cancel an ingestion job."""
    try:
        await _authorize_job(current_user, job_id, ingestion_service, Permission.DOCUMENT_DELETE)
        result = await ingestion_service.cancel_job(job_id)
        if not result:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"message": "Job cancelled successfully"}
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ingestion_cancel_request_failed", job_id=job_id, error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Error cancelling job")


@router.get("/documents")
async def get_documents(
    agent_id: str = ...,
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Get uploaded documents, optionally filtered by agent_id."""
    try:
        await _authorize_agent(current_user, agent_id, Permission.DOCUMENT_READ)
        documents = await ingestion_service.get_documents(agent_id)
        return {
            "documents": documents,
            "count": len(documents)
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ingestion_documents_request_failed", agent_id=agent_id, error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Error retrieving documents")
