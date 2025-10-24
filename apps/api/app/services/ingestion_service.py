"""
Ingestion Service - Document processing and chunking
"""

import asyncio
import uuid
import os
import json
from typing import List, Optional
from datetime import datetime
from fastapi import UploadFile
import structlog
import httpx

from commons.types.requests import IngestionRequest
from commons.types.responses import IngestionResponse, IngestionStatus
from ..config import Settings
from ..connections import connection_manager

logger = structlog.get_logger()


class IngestionService:
    """Service for document ingestion and processing."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.active_jobs = {}  # In-memory job tracking (use Redis in production)
        self.voyage_api_key = os.getenv("VOYAGE_API_KEY")
        self.voyage_model = os.getenv("VOYAGE_MODEL", "voyage-large-2-instruct")
    
    async def start_ingestion_job(self, files: List[dict], agent_id: Optional[str] = None) -> str:
        """Start a new ingestion job."""
        job_id = str(uuid.uuid4())
        
        self.active_jobs[job_id] = {
            "status": "pending",
            "files_count": len(files),
            "processed_count": 0,
            "agent_id": agent_id,
            "created_at": asyncio.get_event_loop().time(),
            "error": None
        }
        
        logger.info("Started ingestion job", job_id=job_id, files_count=len(files), agent_id=agent_id)
        return job_id
    
    async def process_documents(self, job_id: str, files: List[dict], agent_id: Optional[str] = None):
        """Process documents in background."""
        try:
            self.active_jobs[job_id]["status"] = "processing"
            
            for i, file_data in enumerate(files):
                # Extract file information
                content = file_data['content']
                filename = file_data['filename']
                content_type = file_data['content_type']
                
                # Process based on content type
                chunks = await self._extract_and_chunk(content, content_type, filename)
                
                # Store chunks with embeddings
                await self._store_chunks(chunks, job_id, filename, agent_id)
                
                # Update progress
                self.active_jobs[job_id]["processed_count"] = i + 1
                
                logger.info("Processed file", job_id=job_id, filename=filename, chunks_count=len(chunks))
            
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
                "created_at": datetime.utcnow().isoformat()
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
    
    async def get_documents(self, agent_id: Optional[str] = None) -> List[dict]:
        """Get uploaded documents, optionally filtered by agent_id."""
        try:
            db = connection_manager.mongodb_db
            if db is None:
                logger.error("MongoDB not connected")
                return []
            
            chunks_collection = db["knowledge_base"]
            
            # Build query
            query = {}
            if agent_id:
                query["agent_id"] = agent_id
            
            # Aggregate to group by filename and get metadata
            pipeline = [
                {"$match": query},
                {
                    "$group": {
                        "_id": "$filename",
                        "agent_id": {"$first": "$agent_id"},
                        "job_id": {"$first": "$job_id"},
                        "chunks_count": {"$sum": 1},
                        "created_at": {"$first": "$created_at"},
                        "content_type": {"$first": "$metadata.content_type"}
                    }
                },
                {"$sort": {"created_at": -1}}
            ]
            
            cursor = chunks_collection.aggregate(pipeline)
            documents = []
            
            async for doc in cursor:
                documents.append({
                    "filename": doc["_id"],
                    "agent_id": doc.get("agent_id"),
                    "job_id": doc.get("job_id"),
                    "chunks_count": doc["chunks_count"],
                    "created_at": doc.get("created_at"),
                    "content_type": doc.get("content_type")
                })
            
            logger.info("Retrieved documents", count=len(documents), agent_id=agent_id)
            return documents
            
        except Exception as e:
            logger.error("Error getting documents from MongoDB", error=str(e))
            return []

    
    async def _extract_and_chunk(self, content: bytes, content_type: str, filename: str) -> List[dict]:
        """Extract text and create chunks."""
        # Extract text based on content type
        if content_type == "application/json":
            text = content.decode('utf-8')
            # For JSON files, try to extract meaningful text
            try:
                json_data = json.loads(text)
                # Convert JSON to readable text format
                text = self._json_to_text(json_data)
            except json.JSONDecodeError:
                pass  # Treat as plain text
        elif content_type == "text/plain" or content_type == "text/markdown":
            text = content.decode('utf-8')
        else:
            # For other types, try to decode as text
            text = content.decode('utf-8', errors='ignore')
        
        # Chunk the text
        chunk_size = 500  # Characters per chunk
        chunk_overlap = 50  # Overlap between chunks
        chunks = []
        
        # Split text into chunks with overlap
        start = 0
        chunk_index = 0
        while start < len(text):
            end = start + chunk_size
            chunk_text = text[start:end]
            
            if chunk_text.strip():  # Only add non-empty chunks
                chunks.append({
                    "content": chunk_text,
                    "metadata": {
                        "filename": filename,
                        "chunk_index": chunk_index,
                        "content_type": content_type,
                        "start_char": start,
                        "end_char": end
                    }
                })
                chunk_index += 1
            
            start = end - chunk_overlap
        
        return chunks
    
    def _json_to_text(self, data, prefix="") -> str:
        """Convert JSON data to readable text."""
        lines = []
        
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    lines.append(f"{prefix}{key}:")
                    lines.append(self._json_to_text(value, prefix + "  "))
                else:
                    lines.append(f"{prefix}{key}: {value}")
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, (dict, list)):
                    lines.append(f"{prefix}[{i}]:")
                    lines.append(self._json_to_text(item, prefix + "  "))
                else:
                    lines.append(f"{prefix}- {item}")
        else:
            lines.append(f"{prefix}{data}")
        
        return "\n".join(lines)
    
    async def _generate_embeddings(self, text: str) -> List[float]:
        """Generate embeddings using Voyage AI."""
        if not self.voyage_api_key:
            logger.warning("VOYAGE_API_KEY not set, returning zero embeddings")
            return [0.0] * 1024  # Voyage uses 1024 dimensions
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.voyageai.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.voyage_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "input": [text],
                        "model": self.voyage_model
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    embeddings = result["data"][0]["embedding"]
                    logger.debug("Generated embeddings", dimensions=len(embeddings))
                    return embeddings
                else:
                    logger.error("Voyage API error", status_code=response.status_code, response=response.text)
                    return [0.0] * 1024
                    
        except Exception as e:
            logger.error("Error generating embeddings", error=str(e))
            return [0.0] * 1024
    
    async def _store_chunks(self, chunks: List[dict], job_id: str, filename: str, agent_id: Optional[str] = None):
        """Store chunks in vector database."""
        for chunk in chunks:
            # Generate embeddings for this chunk
            chunk["embeddings"] = await self._generate_embeddings(chunk["content"])
            chunk["chunk_id"] = str(uuid.uuid4())  # Generate unique chunk ID
            chunk["job_id"] = job_id
            chunk["filename"] = filename
            chunk["agent_id"] = agent_id
            chunk["created_at"] = datetime.utcnow().isoformat()
            
            # Store in MongoDB
            await self._store_chunk(chunk)
    
    async def _store_chunk(self, chunk_doc: dict) -> str:
        """Store a single chunk in MongoDB Atlas."""
        try:
            # Get MongoDB connection
            db = connection_manager.mongodb_db
            if db is None:
                logger.error("MongoDB not connected, cannot store chunk")
                return str(uuid.uuid4())  # Return fake ID
            
            # Get or create the chunks collection
            chunks_collection = db["knowledge_base"]
            
            # Add unique ID if not present
            if "_id" not in chunk_doc:
                chunk_doc["_id"] = str(uuid.uuid4())
            
            # Insert the chunk
            result = await chunks_collection.insert_one(chunk_doc)
            chunk_id = str(result.inserted_id)
            
            logger.debug("Stored chunk in MongoDB", chunk_id=chunk_id, agent_id=chunk_doc.get("agent_id"))
            return chunk_id
            
        except Exception as e:
            logger.error("Error storing chunk in MongoDB", error=str(e))
            return str(uuid.uuid4())  # Return fake ID on error

