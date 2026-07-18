"""
Ingestion Service - Document processing and chunking
"""

import asyncio
import io
import uuid
import json
import math
from typing import List, Optional, Tuple
from datetime import datetime
from fastapi import UploadFile
import structlog
import httpx

from commons.types.requests import IngestionRequest
from commons.types.responses import IngestionResponse, IngestionStatus
from ..config import Settings
from ..connections import connection_manager
from .chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, chunk_text, resolve_agent_chunking
from .job_store import JobStore
from .qdrant_vector_service import QdrantVectorService
from .runtime_settings_service import RuntimeSettingsService

logger = structlog.get_logger()


class IngestionEmbeddingError(RuntimeError):
    """Raised when Voyage cannot produce a valid embedding."""


class IngestionStorageError(RuntimeError):
    """Raised when a chunk cannot be durably stored in every configured backend."""


class IngestionService:
    """Service for document ingestion and processing."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.job_store = JobStore()
        self.runtime_settings_service = RuntimeSettingsService(settings)
        self.qdrant = QdrantVectorService(settings) if settings.VECTOR_BACKEND == "qdrant" else None

    async def _get_voyage_runtime_config(self) -> dict[str, str]:
        config = await self.runtime_settings_service.get_voyage_runtime_config()
        return {
            "api_key": config["api_key"],
            "base_url": config["base_url"],
            "model": config["model"],
        }
    
    async def start_ingestion_job(self, files: List[dict], agent_id: Optional[str] = None) -> str:
        """Start a new ingestion job."""
        job_id = str(uuid.uuid4())

        await self.job_store.set(job_id, {
            "status": "pending",
            "files_count": len(files),
            "processed_count": 0,
            "agent_id": agent_id,
            "created_at": datetime.utcnow().isoformat(),
            "error": None
        })

        logger.info("Started ingestion job", job_id=job_id, files_count=len(files), agent_id=agent_id)
        return job_id

    async def process_documents(self, job_id: str, files: List[dict], agent_id: Optional[str] = None):
        """Process documents in background."""
        try:
            await self.job_store.update(job_id, {"status": "processing"})

            chunk_size, chunk_overlap = await self._resolve_chunking(agent_id)

            for i, file_data in enumerate(files):
                # Extract file information
                content = file_data['content']
                filename = file_data['filename']
                content_type = file_data['content_type']

                # Process based on content type
                chunks = await self._extract_and_chunk(
                    content, content_type, filename,
                    chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                )

                # Store chunks with embeddings
                await self._store_chunks(chunks, job_id, filename, agent_id)

                # Update progress
                await self.job_store.update(job_id, {"processed_count": i + 1})

                logger.info("Processed file", job_id=job_id, filename=filename, chunks_count=len(chunks))

            await self.job_store.update(job_id, {"status": "completed"})
            logger.info("Completed ingestion job", job_id=job_id)

        except Exception as e:
            await self.job_store.update(job_id, {"status": "error", "error": str(e)})
            logger.error("Error processing documents", job_id=job_id, error=str(e))
    
    async def process_chunk(
        self,
        request: IngestionRequest,
        *,
        agent_id: Optional[str] = None,
    ) -> IngestionResponse:
        """Process a single text chunk."""
        try:
            # Generate embeddings
            embeddings = await self._generate_embeddings(request.text)
            
            # Create chunk document
            metadata = dict(request.metadata or {})
            if agent_id:
                # The route has already authorized this agent. Persist that
                # canonical scope rather than trusting caller-supplied metadata.
                metadata["agent_id"] = agent_id

            chunk_doc = {
                "doc_id": request.doc_id or str(uuid.uuid4()),
                "content": request.text,
                "embeddings": embeddings,
                "metadata": metadata,
                "agent_id": agent_id,
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
        job_info = await self.job_store.get(job_id)
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
        job_info = await self.job_store.get(job_id)
        if job_info:
            await self.job_store.update(job_id, {"status": "cancelled"})
            logger.info("Cancelled ingestion job", job_id=job_id)
            return True
        return False
    
    async def get_documents(self, agent_id: Optional[str] = None) -> List[dict]:
        """Get uploaded documents, optionally filtered by agent_id."""
        try:
            # Get brand-specific database
            if agent_id:
                brand_db = await connection_manager.get_brand_db_by_agent_id(agent_id)
            else:
                # Fallback to system database (though documents should be in brand databases)
                brand_db = connection_manager.get_system_db()
            
            chunks_collection = brand_db["knowledge_base"]
            
            # Build query (no need to filter by agent_id since we're in brand-specific DB)
            query = {}
            if agent_id and not hasattr(connection_manager, 'get_brand_db_by_agent_id'):
                # Fallback for legacy compatibility
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

    
    def _extract_product_data(self, json_obj: dict) -> Optional[dict]:
        """Extract product fields from JSON object."""
        try:
            # Check if this looks like product data
            has_product_fields = any(
                field in json_obj 
                for field in ['sku', 'name', 'price', 'product_id', 'product_name']
            )
            
            if not has_product_fields:
                return None
            
            return {
                "sku": json_obj.get("sku") or json_obj.get("product_id"),
                "name": json_obj.get("name") or json_obj.get("product_name"),
                "price": json_obj.get("price"),
                "currency": json_obj.get("currency"),
                "category": json_obj.get("category"),
                "image_url": json_obj.get("image_url"),
                "product_url": json_obj.get("product_url"),
                "in_stock": json_obj.get("in_stock", True),
                "features": json_obj.get("features", [])
            }
        except Exception as e:
            logger.warning("Failed to extract product data", error=str(e))
            return None
    
    def _extract_dealer_data(self, json_obj: dict) -> Optional[dict]:
        """Extract dealer fields from JSON object."""
        try:
            # Check if this looks like dealer data
            has_dealer_fields = any(
                field in json_obj 
                for field in ['dealer_id', 'name', 'city', 'phone']
            )
            
            if not has_dealer_fields:
                return None
            
            return {
                "dealer_id": json_obj.get("dealer_id"),
                "name": json_obj.get("name"),
                "city": json_obj.get("city"),
                "state": json_obj.get("state"),
                "phone": json_obj.get("phone"),
                "email": json_obj.get("email"),
                "address": json_obj.get("address")
            }
        except Exception as e:
            logger.warning("Failed to extract dealer data", error=str(e))
            return None
    
    def _detect_content_type(self, json_obj: dict) -> str:
        """Auto-detect content type from JSON structure."""
        # Check for product fields
        if any(f in json_obj for f in ['sku', 'product_id', 'price']):
            return "product"
        
        # Check for dealer fields
        if any(f in json_obj for f in ['dealer_id', 'city', 'phone']):
            return "dealer"
        
        # Check for FAQ fields
        if 'question' in json_obj or 'answer' in json_obj:
            return "faq"
        
        # Check for office fields
        if 'office_id' in json_obj or 'office_name' in json_obj:
            return "office"
        
        # Check for category fields
        if 'category_id' in json_obj or 'category_name' in json_obj:
            return "category"
        
        # Default to guide
        return "guide"

    async def _resolve_chunking(self, agent_id: Optional[str]) -> Tuple[int, int]:
        """Resolve chunk size/overlap via the shared chunking module."""
        return await resolve_agent_chunking(agent_id)

    def _extract_pdf_text(self, content: bytes) -> str:
        """Extract text from a PDF using pypdf."""
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF extraction requires pypdf to be installed") from exc

        reader = PdfReader(io.BytesIO(content))
        page_text = []
        for page_number, page in enumerate(reader.pages, start=1):
            extracted = (page.extract_text() or "").strip()
            if extracted:
                page_text.append(f"Page {page_number}\n{extracted}")
        return "\n\n".join(page_text)

    def _extract_docx_text(self, content: bytes) -> str:
        """Extract text from a DOCX using python-docx."""
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("DOCX extraction requires python-docx to be installed") from exc

        document = Document(io.BytesIO(content))
        paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        table_rows = []
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    table_rows.append(" | ".join(cells))
        return "\n\n".join(paragraphs + table_rows)

    async def _extract_and_chunk(
        self,
        content: bytes,
        content_type: str,
        filename: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> List[dict]:
        """Extract text and create chunks with structured data extraction."""
        # Extract text based on content type
        json_data = None
        structured_content_type = None
        lower_name = (filename or "").lower()

        if content_type == "application/json":
            text = content.decode('utf-8')
            # For JSON files, try to extract structured data
            try:
                json_data = json.loads(text)
                
                # If it's a list, process each item
                if isinstance(json_data, list):
                    # Process the first item to detect type
                    if json_data and isinstance(json_data[0], dict):
                        structured_content_type = self._detect_content_type(json_data[0])
                        logger.info(
                            "Detected content type from JSON",
                            filename=filename,
                            detected_type=structured_content_type,
                            items_count=len(json_data)
                        )
                
                # Convert JSON to readable text format
                text = self._json_to_text(json_data)
            except json.JSONDecodeError:
                pass  # Treat as plain text
        elif content_type in ("text/plain", "text/markdown", "text/csv", "text/html"):
            text = content.decode('utf-8', errors='replace')
        elif content_type == "application/pdf" or lower_name.endswith(".pdf"):
            text = self._extract_pdf_text(content)
        elif (
            content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            or lower_name.endswith(".docx")
        ):
            text = self._extract_docx_text(content)
        else:
            # For other types, try to decode as text but reject binary garbage
            # instead of embedding unreadable bytes.
            text = content.decode('utf-8', errors='replace')
            if text and (text.count('�') / len(text)) > 0.2:
                raise ValueError(
                    f"File {filename} ({content_type or 'unknown type'}) does not contain extractable text"
                )

        # Chunk the text (bounds are enforced by the shared chunker)
        chunks = []
        
        # If we have structured JSON data (list of items), create one chunk per item
        if json_data and isinstance(json_data, list) and structured_content_type:
            for idx, item in enumerate(json_data):
                if not isinstance(item, dict):
                    continue
                
                # Extract structured data based on content type
                product_data = None
                dealer_data = None
                
                if structured_content_type == "product":
                    product_data = self._extract_product_data(item)
                elif structured_content_type == "dealer":
                    dealer_data = self._extract_dealer_data(item)
                
                # Create readable text for this item
                item_text = self._json_to_text(item)
                
                chunks.append({
                    "content": item_text,
                    "content_type": structured_content_type,
                    "product_data": product_data,
                    "dealer_data": dealer_data,
                    "metadata": {
                        "filename": filename,
                        "chunk_index": idx,
                        "content_type": content_type,
                        "item_index": idx,
                        "structured_type": structured_content_type
                    }
                })
        else:
            # Standard chunking for non-structured content via the shared
            # paragraph-aware chunker (same chunks as the Knowledge Base upload path).
            for chunk_index, piece in enumerate(chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)):
                chunks.append({
                    "content": piece,
                    "content_type": "guide",  # Default content type
                    "product_data": None,
                    "dealer_data": None,
                    "metadata": {
                        "filename": filename,
                        "chunk_index": chunk_index,
                        "content_type": content_type,
                    }
                })

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
        voyage_config = await self._get_voyage_runtime_config()
        api_key = voyage_config["api_key"]
        base_url = voyage_config["base_url"].rstrip("/")
        model = voyage_config["model"]

        if not api_key:
            logger.error("voyage_api_key_not_configured", text_length=len(text))
            raise IngestionEmbeddingError("Voyage embedding API key is not configured")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "input": [text],
                        "model": model
                    },
                    timeout=30.0
                )
        except httpx.HTTPError as exc:
            logger.error("voyage_embedding_request_failed", error_type=type(exc).__name__)
            raise IngestionEmbeddingError("Voyage embedding request failed") from exc

        if response.status_code != 200:
            logger.error("voyage_embedding_request_rejected", status_code=response.status_code)
            raise IngestionEmbeddingError(
                f"Voyage embedding request failed with HTTP {response.status_code}"
            )

        try:
            embeddings = response.json()["data"][0]["embedding"]
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            logger.error("voyage_embedding_response_invalid", error_type=type(exc).__name__)
            raise IngestionEmbeddingError("Voyage returned an invalid embeddings response") from exc

        self._validate_embedding(embeddings)
        logger.debug("Generated embeddings", dimensions=len(embeddings))
        return embeddings

    def _validate_embedding(self, embeddings: object) -> None:
        """Reject malformed or placeholder vectors before any storage write."""
        if not isinstance(embeddings, list):
            raise IngestionEmbeddingError("Voyage returned an embedding with an invalid type")

        if len(embeddings) != self.settings.VECTOR_DIMENSIONS:
            raise IngestionEmbeddingError(
                "Voyage returned an embedding with unexpected dimensions "
                f"({len(embeddings)}; expected {self.settings.VECTOR_DIMENSIONS})"
            )

        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in embeddings
        ):
            raise IngestionEmbeddingError("Voyage returned an embedding with invalid values")

        if not any(embeddings):
            raise IngestionEmbeddingError("Voyage returned an all-zero embedding")
    
    async def _store_chunks(self, chunks: List[dict], job_id: str, filename: str, agent_id: Optional[str] = None):
        """Store chunks in vector database with structured data."""
        for chunk in chunks:
            # Generate embeddings for this chunk
            chunk["embeddings"] = await self._generate_embeddings(chunk["content"])
            chunk["chunk_id"] = str(uuid.uuid4())  # Generate unique chunk ID
            chunk["job_id"] = job_id
            chunk["filename"] = filename
            chunk["agent_id"] = agent_id
            chunk["created_at"] = datetime.utcnow().isoformat()
            
            # content_type, product_data, dealer_data are already in chunk from _extract_and_chunk()
            # Just ensure they exist
            if "content_type" not in chunk:
                chunk["content_type"] = "guide"
            
            if "product_data" not in chunk:
                chunk["product_data"] = None
            
            if "dealer_data" not in chunk:
                chunk["dealer_data"] = None

            # Ensure metadata object exists and include brand info when possible
            if "metadata" not in chunk or not isinstance(chunk["metadata"], dict):
                chunk.setdefault("metadata", {})

            # If agent_id is provided, try to resolve the agent -> brand and include both
            if agent_id:
                try:
                    system_db = connection_manager.get_system_db()
                    agent_doc = await system_db.agents.find_one({"id": agent_id})
                    if agent_doc:
                        # include both brand_id and brand_slug for cross-referencing
                        if agent_doc.get("brand_id"):
                            chunk["metadata"]["brand_id"] = agent_doc.get("brand_id")
                        if agent_doc.get("brand_slug"):
                            chunk["metadata"]["brand_slug"] = agent_doc.get("brand_slug")
                        # Also ensure agent_id present in metadata for convenience
                        chunk["metadata"]["agent_id"] = agent_id
                except Exception:
                    # If resolving fails, continue without brand info (will fallback)
                    logger.debug("Could not resolve agent -> brand for chunk metadata", agent_id=agent_id)

            # Store in MongoDB
            await self._store_chunk(chunk)
    
    async def _store_chunk(self, chunk_doc: dict) -> str:
        """Store a single chunk in brand-specific MongoDB database."""
        try:
            self._validate_embedding(chunk_doc.get("embeddings"))

            # Get brand-specific database
            agent_id = chunk_doc.get("agent_id")
            if agent_id:
                brand_db = await connection_manager.get_brand_db_by_agent_id(agent_id)
            else:
                # Fallback to system database if no agent_id
                brand_db = connection_manager.get_system_db()
            
            # Get or create the chunks collection in brand database  
            chunks_collection = brand_db["knowledge_base"]
            
            # Add unique ID if not present
            if "_id" not in chunk_doc:
                chunk_doc["_id"] = str(uuid.uuid4())
            
            # Insert the chunk
            result = await chunks_collection.insert_one(chunk_doc)
            inserted_id = getattr(result, "inserted_id", None)
            if inserted_id is None:
                raise IngestionStorageError("MongoDB did not return an inserted chunk ID")

            chunk_id = str(inserted_id)
            if self.qdrant:
                brand_slug = (chunk_doc.get("metadata") or {}).get("brand_slug")
                await self.qdrant.upsert_chunk(chunk_doc, brand_slug)
            
            logger.debug("Stored chunk in MongoDB", chunk_id=chunk_id, agent_id=chunk_doc.get("agent_id"))
            return chunk_id

        except IngestionStorageError:
            raise
        except Exception as exc:
            logger.error("chunk_storage_failed", error_type=type(exc).__name__)
            raise IngestionStorageError("Failed to store knowledge-base chunk") from exc
