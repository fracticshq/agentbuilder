"""
Ingestion API Endpoints
"""

from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
import structlog

from commons.types.requests import IngestionRequest
from commons.types.responses import IngestionResponse, IngestionStatus
from ....dependencies import get_settings, get_ingestion_service
from ....services.ingestion_service import IngestionService
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
    agent_id = job.get("agent_id")
    if not agent_id:
        # Historical unscoped jobs cannot be safely exposed to a tenant user.
        raise HTTPException(status_code=404, detail="Job not found")
    await _authorize_agent(current_user, agent_id, permission)
    return job


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    agent_id: str = ...,
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    current_user: User | None = Depends(require_dashboard_access),
):
    """Upload and process documents for ingestion.
    
    Args:
        background_tasks: FastAPI background tasks
        files: List of files to upload
        agent_id: Optional agent ID to associate with documents (query parameter)
        ingestion_service: Injected ingestion service
    """
    try:
        await _authorize_agent(current_user, agent_id, Permission.DOCUMENT_WRITE)
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
        max_file_bytes = get_settings().MAX_FILE_SIZE_MB * 1024 * 1024
        file_contents = []
        for file in files:
            content = await file.read()
            if len(content) > max_file_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File {file.filename} exceeds the {get_settings().MAX_FILE_SIZE_MB}MB upload limit"
                )
            file_contents.append({
                'content': content,
                'filename': file.filename,
                'content_type': file.content_type
            })
        
        # Start background ingestion job with agent_id
        job_id = await ingestion_service.start_ingestion_job(file_contents, agent_id)
        background_tasks.add_task(ingestion_service.process_documents, job_id, file_contents, agent_id)
        
        logger.info("Document upload started", job_id=job_id, files_count=len(files), agent_id=agent_id)
        
        return DocumentUploadResponse(
            job_id=job_id,
            status="processing",
            message="Documents uploaded and processing started",
            documents_count=len(files)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error uploading documents", error=str(e))
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
    except Exception as e:
        logger.error("Error processing chunk", error=str(e))
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
    except Exception as e:
        logger.error("Error getting job status", job_id=job_id, error=str(e))
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
    except Exception as e:
        logger.error("Error cancelling job", job_id=job_id, error=str(e))
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
    except Exception as e:
        logger.error("Error retrieving documents", agent_id=agent_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error retrieving documents")
