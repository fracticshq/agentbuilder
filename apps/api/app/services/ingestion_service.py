"""
Ingestion Service - Document processing and chunking
"""

import asyncio
import uuid
from typing import List, Optional
from fastapi import UploadFile
import structlog

from commons.types.requests import IngestionRequest
from commons.types.responses import IngestionResponse, IngestionStatus
from ..config import Settings

logger = structlog.get_logger()


class IngestionService:
    """Service for document ingestion and processing."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.active_jobs = {}  # In-memory job tracking (use Redis in production)
    
    async def start_ingestion_job(self, files: List[UploadFile]) -> str:
        """Start a new ingestion job."""
        job_id = str(uuid.uuid4())
        
        self.active_jobs[job_id] = {
            "status": "pending",
            "files_count": len(files),
            "processed_count": 0,
            "created_at": asyncio.get_event_loop().time(),
            "error": None
        }
        
        logger.info("Started ingestion job", job_id=job_id, files_count=len(files))
        return job_id
    
    async def process_documents(self, job_id: str, files: List[UploadFile]):
        """Process documents in background."""
        try:
            self.active_jobs[job_id]["status"] = "processing"
            
            for i, file in enumerate(files):
                # Read file content
                content = await file.read()
                
                # Process based on content type
                chunks = await self._extract_and_chunk(content, file.content_type, file.filename)
                
                # Store chunks
                await self._store_chunks(chunks, job_id, file.filename)
                
                # Update progress
                self.active_jobs[job_id]["processed_count"] = i + 1
                
                logger.info("Processed file", job_id=job_id, filename=file.filename, chunks_count=len(chunks))
            
            self.active_jobs[job_id]["status"] = "completed"
            logger.info("Completed ingestion job", job_id=job_id)
            
        except Exception as e:
            self.active_jobs[job_id]["status"] = "error"
            self.active_jobs[job_id]["error"] = str(e)
            logger.error("Error processing documents", job_id=job_id, error=str(e))
    
    async def process_chunk(self, request: IngestionRequest) -> IngestionResponse:
        """Process a single text chunk."""
        try:
            # Generate embeddings
            embeddings = await self._generate_embeddings(request.text)
            
            # Create chunk document
            chunk_doc = {
                "doc_id": request.doc_id or str(uuid.uuid4()),
                "content": request.text,
                "embeddings": embeddings,
                "metadata": request.metadata,
                "created_at": asyncio.get_event_loop().time()
            }
            
            # Store in vector database
            chunk_id = await self._store_chunk(chunk_doc)
            
            return IngestionResponse(
                success=True,
                chunk_id=chunk_id,
                message="Chunk processed successfully"
            )
            
        except Exception as e:
            logger.error("Error processing chunk", error=str(e))
            return IngestionResponse(
                success=False,
                chunk_id=None,
                message=f"Error processing chunk: {str(e)}"
            )
    
    async def get_job_status(self, job_id: str) -> Optional[IngestionStatus]:
        """Get the status of an ingestion job."""
        job_info = self.active_jobs.get(job_id)
        if not job_info:
            return None
        
        return IngestionStatus(
            job_id=job_id,
            status=job_info["status"],
            files_count=job_info["files_count"],
            processed_count=job_info["processed_count"],
            error=job_info.get("error")
        )
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel an ingestion job."""
        if job_id in self.active_jobs:
            self.active_jobs[job_id]["status"] = "cancelled"
            logger.info("Cancelled ingestion job", job_id=job_id)
            return True
        return False
    
    async def _extract_and_chunk(self, content: bytes, content_type: str, filename: str) -> List[dict]:
        """Extract text and create chunks."""
        # Simple text extraction (extend for different file types)
        if content_type == "text/plain":
            text = content.decode('utf-8')
        else:
            # For now, treat everything as text
            text = content.decode('utf-8', errors='ignore')
        
        # Simple chunking (implement more sophisticated chunking later)
        chunk_size = 1000
        chunks = []
        
        for i in range(0, len(text), chunk_size):
            chunk_text = text[i:i + chunk_size]
            chunks.append({
                "content": chunk_text,
                "metadata": {
                    "filename": filename,
                    "chunk_index": i // chunk_size,
                    "content_type": content_type
                }
            })
        
        return chunks
    
    async def _generate_embeddings(self, text: str) -> List[float]:
        """Generate embeddings for text."""
        # Placeholder - implement actual embedding generation
        # This would use the Voyage API or other embedding service
        return [0.0] * 768  # Mock 768-dimensional embeddings
    
    async def _store_chunks(self, chunks: List[dict], job_id: str, filename: str):
        """Store chunks in vector database."""
        for chunk in chunks:
            chunk["embeddings"] = await self._generate_embeddings(chunk["content"])
            chunk["job_id"] = job_id
            chunk["filename"] = filename
            await self._store_chunk(chunk)
    
    async def _store_chunk(self, chunk_doc: dict) -> str:
        """Store a single chunk in the database."""
        # Placeholder - implement actual database storage
        # This would use MongoDB Atlas with vector search
        chunk_id = str(uuid.uuid4())
        logger.debug("Stored chunk", chunk_id=chunk_id)
        return chunk_id
