"""
Ingestion API Endpoints
"""

from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
import structlog

from commons.types.requests import IngestionRequest
from commons.types.responses import IngestionResponse, IngestionStatus
from ....dependencies import get_ingestion_service
from ....services.ingestion_service import IngestionService
from ....auth.admin_key import require_admin_key

logger = structlog.get_logger()
router = APIRouter()


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


@router.post("/documents", response_model=DocumentUploadResponse, dependencies=[Depends(require_admin_key)])
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    agent_id: Optional[str] = None,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Upload and process documents for ingestion.
    
    Args:
        background_tasks: FastAPI background tasks
        files: List of files to upload
        agent_id: Optional agent ID to associate with documents (query parameter)
        ingestion_service: Injected ingestion service
    """
    try:
        # Validate file types
        allowed_types = {
            "text/plain", "text/markdown", "application/pdf",
            "text/html", "application/json"
        }
        
        for file in files:
            if file.content_type not in allowed_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {file.content_type}"
                )
        
        # Read file contents before starting background task
        file_contents = []
        for file in files:
            content = await file.read()
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


@router.post("/chunks", response_model=IngestionResponse, dependencies=[Depends(require_admin_key)])
async def process_chunk(
    request: ChunkRequest,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Process a single text chunk."""
    try:
        ingestion_request = IngestionRequest(
            text=request.text,
            metadata=request.metadata,
            doc_id=request.doc_id,
            chunk_size=None,
            chunk_overlap=None
        )
        
        response = await ingestion_service.process_chunk(ingestion_request)
        return response
        
    except Exception as e:
        logger.error("Error processing chunk", error=str(e))
        raise HTTPException(status_code=500, detail="Error processing chunk")


@router.get("/status/{job_id}", response_model=IngestionStatus, dependencies=[Depends(require_admin_key)])
async def get_ingestion_status(
    job_id: str,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Get the status of an ingestion job."""
    try:
        status = await ingestion_service.get_job_status(job_id)
        if not status:
            raise HTTPException(status_code=404, detail="Job not found")
        return status
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting job status", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error getting job status")


@router.delete("/jobs/{job_id}", dependencies=[Depends(require_admin_key)])
async def cancel_ingestion_job(
    job_id: str,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Cancel an ingestion job."""
    try:
        result = await ingestion_service.cancel_job(job_id)
        if not result:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"message": "Job cancelled successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error cancelling job", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error cancelling job")


@router.get("/documents", dependencies=[Depends(require_admin_key)])
async def get_documents(
    agent_id: Optional[str] = None,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Get uploaded documents, optionally filtered by agent_id."""
    try:
        documents = await ingestion_service.get_documents(agent_id)
        return {
            "documents": documents,
            "count": len(documents)
        }
        
    except Exception as e:
        logger.error("Error retrieving documents", agent_id=agent_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error retrieving documents")
