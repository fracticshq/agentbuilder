"""
Knowledge Service - Enhanced document processing with structured metadata
Handles both document uploads and bulk JSON imports for products/dealers
"""

import asyncio
import uuid
import os
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import structlog
import httpx
from pymongo import UpdateOne

from ..config import Settings
from ..connections import connection_manager

logger = structlog.get_logger()


class KnowledgeService:
    """Service for knowledge base operations with structured metadata support."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.active_jobs = {}  # In-memory job tracking (use Redis in production)
        self.voyage_api_key = os.getenv("VOYAGE_API_KEY")
        self.voyage_model = os.getenv("VOYAGE_MODEL", "voyage-large-2-instruct")
        self.mongo_client = None
        self.db_cache = {}  # Cache brand-specific databases
        self.db = None
        self.collection = None
    
    async def _get_brand_database(self, brand_id: str):
        """
        Get brand-specific database.
        
        If brand_id looks like a UUID (agent_id), resolve it to brand_slug first.
        Otherwise, assume it's already a brand_slug.
        """
        # Check if already cached
        if brand_id in self.db_cache:
            return self.db_cache[brand_id]
        
        # Get the MongoDB client from connection manager
        mongo_client = connection_manager.mongodb_client
        if not mongo_client:
            raise RuntimeError("MongoDB not connected")
        
        # Determine if brand_id is agent_id (UUID format) or brand_slug
        brand_slug = brand_id
        
        # If it looks like a UUID, resolve agent -> brand_slug
        if len(brand_id) == 36 and brand_id.count('-') == 4:
            # It's likely an agent_id, resolve to brand_slug
            system_db = connection_manager.get_system_db()
            agent = await system_db.agents.find_one({'id': brand_id})
            if agent and agent.get('brand_slug'):
                brand_slug = agent['brand_slug']
                logger.info("resolved_agent_to_brand", agent_id=brand_id, brand_slug=brand_slug)
            else:
                logger.warning("agent_not_found_or_no_brand_slug", brand_id=brand_id)
                # Fallback to using brand_id as-is (old behavior for backward compat)
        
        # Get brand database using the resolved brand_slug
        db_name = brand_slug.replace('.', '_')[:63]  # MongoDB db name max 63 chars
        self.db_cache[brand_id] = mongo_client[db_name]
        logger.info("brand_database_accessed", brand_id=brand_id, brand_slug=brand_slug, db_name=db_name)
        
        return self.db_cache[brand_id]
    
    async def _ensure_connection(self, brand_id: Optional[str] = None):
        """Ensure MongoDB connection is established for specific brand."""
        # Use brand-specific database for isolation
        if brand_id:
            self.db = await self._get_brand_database(brand_id)
            self.collection = self.db["knowledge_base"]
        else:
            # Fallback to default database
            self.db = connection_manager.get_mongodb_db()
            self.collection = self.db["knowledge_base"]
    
    # ========================================================================
    # Job Management
    # ========================================================================
    
    async def start_document_upload(
        self,
        content: bytes,
        filename: str,
        content_type_header: str,
        kb_content_type: str,
        brand_id: str,
        product_data: Optional[Any] = None,
        dealer_data: Optional[Any] = None
    ) -> str:
        """Start a document upload job."""
        job_id = str(uuid.uuid4())
        
        self.active_jobs[job_id] = {
            "status": "pending",
            "type": "document",
            "filename": filename,
            "content_type": kb_content_type,
            "brand_id": brand_id,
            "processed_chunks": 0,
            "total_chunks": 0,
            "created_at": asyncio.get_event_loop().time(),
            "error": None
        }
        
        return job_id
    
    async def start_bulk_upload(
        self,
        content_type: str,
        items: List[Any],
        brand_id: str
    ) -> str:
        """Start a bulk JSON upload job."""
        job_id = str(uuid.uuid4())
        
        self.active_jobs[job_id] = {
            "status": "pending",
            "type": "bulk",
            "content_type": content_type,
            "brand_id": brand_id,
            "total_items": len(items),
            "processed_items": 0,
            "processed_chunks": 0,
            "created_at": asyncio.get_event_loop().time(),
            "error": None
        }
        
        return job_id
    
    async def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get job status."""
        job = self.active_jobs.get(job_id)
        if not job:
            return None
        
        return {
            "job_id": job_id,
            "status": job["status"],
            "progress": {
                "type": job.get("type"),
                "processed_items": job.get("processed_items", 0),
                "total_items": job.get("total_items", 0),
                "processed_chunks": job.get("processed_chunks", 0),
                "total_chunks": job.get("total_chunks", 0)
            },
            "error": job.get("error")
        }
    
    # ========================================================================
    # Document Upload Processing
    # ========================================================================
    
    async def process_document_upload(
        self,
        job_id: str,
        content: bytes,
        filename: str,
        content_type_header: str,
        kb_content_type: str,
        brand_id: str,
        product_data: Optional[Any] = None,
        dealer_data: Optional[Any] = None
    ):
        """Process a document upload in background."""
        try:
            await self._ensure_connection(brand_id)  # Use brand-specific database
            self.active_jobs[job_id]["status"] = "processing"
            
            # Extract text from document
            text = await self._extract_text(content, content_type_header, filename)
            
            # Chunk the text
            chunks = await self._chunk_text(text, filename)
            self.active_jobs[job_id]["total_chunks"] = len(chunks)
            
            # Generate doc_id
            doc_id = f"{brand_id}_{kb_content_type}_{uuid.uuid4().hex[:8]}"
            
            # Process each chunk
            for i, chunk_text in enumerate(chunks):
                # Generate embedding
                embedding = await self._generate_embeddings([chunk_text])
                
                # Build chunk document
                chunk_doc = {
                    "doc_id": doc_id,
                    "chunk_id": f"{doc_id}_chunk_{i}",
                    "content": chunk_text,
                    "embedding": embedding[0] if embedding else [],
                    "title": filename,
                    
                    # Enhanced metadata
                    "content_type": kb_content_type,  # product, dealer, faq, etc.
                    "metadata": {
                        "brand_id": brand_id,
                        "filename": filename,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "created_at": datetime.utcnow().isoformat()
                    }
                }
                
                # Add structured data if provided
                if product_data:
                    chunk_doc["product_data"] = {
                        "sku": product_data.sku,
                        "name": product_data.name,
                        "price": product_data.price,
                        "currency": product_data.currency,
                        "category": product_data.category,
                        "image_url": product_data.image_url,
                        "product_url": product_data.product_url,
                        "in_stock": product_data.in_stock,
                        "features": product_data.features or []
                    }
                
                if dealer_data:
                    chunk_doc["dealer_data"] = {
                        "dealer_id": dealer_data.dealer_id,
                        "name": dealer_data.name,
                        "city": dealer_data.city,
                        "phone": dealer_data.phone,
                        "state": dealer_data.state,
                        "email": dealer_data.email,
                        "address": dealer_data.address
                    }
                
                # Store in MongoDB
                await self.collection.insert_one(chunk_doc)
                
                # Update progress
                self.active_jobs[job_id]["processed_chunks"] = i + 1
            
            self.active_jobs[job_id]["status"] = "completed"
            logger.info(
                "Document upload completed",
                job_id=job_id,
                doc_id=doc_id,
                chunks=len(chunks)
            )
            
        except Exception as e:
            self.active_jobs[job_id]["status"] = "error"
            self.active_jobs[job_id]["error"] = str(e)
            logger.error("Document upload failed", job_id=job_id, error=str(e))
    
    # ========================================================================
    # Bulk Upload Processing
    # ========================================================================
    
    async def process_bulk_upload(
        self,
        job_id: str,
        content_type: str,
        items: List[Any],
        brand_id: str
    ):
        """Process bulk JSON upload in background."""
        try:
            await self._ensure_connection(brand_id)  # Use brand-specific database
            self.active_jobs[job_id]["status"] = "processing"
            
            for i, item in enumerate(items):
                if content_type == "product":
                    await self._process_product_item(item, brand_id, job_id)
                elif content_type == "dealer":
                    await self._process_dealer_item(item, brand_id, job_id)
                
                # Update progress
                self.active_jobs[job_id]["processed_items"] = i + 1
            
            self.active_jobs[job_id]["status"] = "completed"
            logger.info(
                "Bulk upload completed",
                job_id=job_id,
                items=len(items),
                content_type=content_type
            )
            
        except Exception as e:
            self.active_jobs[job_id]["status"] = "error"
            self.active_jobs[job_id]["error"] = str(e)
            logger.error("Bulk upload failed", job_id=job_id, error=str(e))
    
    async def _process_product_item(self, item: Any, brand_id: str, job_id: str):
        """Process a single product item."""
        # Generate text description for embedding
        text_parts = [
            f"Product: {item.name}",
            f"SKU: {item.sku}",
            f"Category: {item.category}",
            f"Price: {item.price} {item.currency}"
        ]
        
        if item.features:
            text_parts.append(f"Features: {', '.join(item.features)}")
        
        full_text = "\n".join(text_parts)
        
        # Generate chunks (split if text is very long)
        chunks = await self._chunk_text(full_text, item.name)
        
        # Generate doc_id based on SKU
        doc_id = f"{brand_id}_product_{item.sku}"
        
        # Process each chunk
        for i, chunk_text in enumerate(chunks):
            # Generate embedding
            embedding = await self._generate_embeddings([chunk_text])
            
            # Build chunk document
            chunk_doc = {
                "doc_id": doc_id,
                "chunk_id": f"{doc_id}_chunk_{i}",
                "content": chunk_text,
                "embedding": embedding[0] if embedding else [],
                "title": item.name,
                
                # Enhanced metadata
                "content_type": "product",
                "product_data": {
                    "sku": item.sku,
                    "name": item.name,
                    "price": item.price,
                    "currency": item.currency,
                    "category": item.category,
                    "image_url": item.image_url,
                    "product_url": item.product_url,
                    "in_stock": item.in_stock if item.in_stock is not None else True,
                    "features": item.features or []
                },
                "metadata": {
                    "brand_id": brand_id,
                    "job_id": job_id,  # Track which upload batch this belongs to
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "created_at": datetime.utcnow().isoformat()
                }
            }
            
            # Upsert to MongoDB (update if SKU exists, insert if new)
            await self.collection.update_one(
                {"doc_id": doc_id, "chunk_id": chunk_doc["chunk_id"]},
                {"$set": chunk_doc},
                upsert=True
            )
            
            # Update progress
            self.active_jobs[job_id]["processed_chunks"] += 1
    
    async def _process_dealer_item(self, item: Any, brand_id: str, job_id: str):
        """Process a single dealer item."""
        # Generate text description for embedding
        text_parts = [
            f"Dealer: {item.name}",
            f"Dealer ID: {item.dealer_id}",
            f"Location: {item.city}",
            f"Phone: {item.phone}"
        ]
        
        if item.state:
            text_parts.append(f"State: {item.state}")
        if item.email:
            text_parts.append(f"Email: {item.email}")
        if item.address:
            text_parts.append(f"Address: {item.address}")
        
        full_text = "\n".join(text_parts)
        
        # Generate chunks
        chunks = await self._chunk_text(full_text, item.name)
        
        # Generate doc_id based on dealer_id
        doc_id = f"{brand_id}_dealer_{item.dealer_id}"
        
        # Process each chunk
        for i, chunk_text in enumerate(chunks):
            # Generate embedding
            embedding = await self._generate_embeddings([chunk_text])
            
            # Build chunk document
            chunk_doc = {
                "doc_id": doc_id,
                "chunk_id": f"{doc_id}_chunk_{i}",
                "content": chunk_text,
                "embedding": embedding[0] if embedding else [],
                "title": item.name,
                
                # Enhanced metadata
                "content_type": "dealer",
                "dealer_data": {
                    "dealer_id": item.dealer_id,
                    "name": item.name,
                    "city": item.city,
                    "phone": item.phone,
                    "state": item.state,
                    "email": item.email,
                    "address": item.address
                },
                "metadata": {
                    "brand_id": brand_id,
                    "job_id": job_id,  # Track which upload batch this belongs to
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "created_at": datetime.utcnow().isoformat()
                }
            }
            
            # Upsert to MongoDB
            await self.collection.update_one(
                {"doc_id": doc_id, "chunk_id": chunk_doc["chunk_id"]},
                {"$set": chunk_doc},
                upsert=True
            )
            
            # Update progress
            self.active_jobs[job_id]["processed_chunks"] += 1
    
    # ========================================================================
    # Document Management
    # ========================================================================
    
    async def list_documents(
        self,
        brand_id: str,
        content_type: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ) -> List[Dict]:
        """List documents grouped by upload job (not individual products/chunks)."""
        await self._ensure_connection(brand_id)  # Use brand-specific database
        
        # Build query - check both brand_id and brand_slug for compatibility
        brand_filter = {
            "$or": [
                {"metadata.brand_id": brand_id},
                {"metadata.brand_slug": brand_id}
            ]
        }
        
        if content_type:
            query = {
                "$and": [
                    brand_filter,
                    {"content_type": content_type}
                ]
            }
        else:
            query = brand_filter
        
        logger.info("list_documents_query", brand_id=brand_id, query=query, content_type=content_type)
        
        # Aggregate to group by job_id (upload batch)
        # For old documents without job_id, group by doc_id instead
        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": {
                        "$ifNull": [
                            "$metadata.job_id",  # New documents have job_id
                            "$doc_id"            # Old documents fall back to doc_id
                        ]
                    },
                    "content_type": {"$first": "$content_type"},
                    "created_at": {"$first": "$metadata.created_at"},
                    "total_chunks": {"$sum": 1},
                    "item_count": {"$addToSet": "$doc_id"},  # Count unique products/dealers
                    "sample_title": {"$first": "$title"},  # Get first item's title
                    "has_job_id": {"$first": {"$ifNull": ["$metadata.job_id", None]}}
                }
            },
            {
                "$project": {
                    "job_id": "$_id",
                    "content_type": 1,
                    "created_at": 1,
                    "total_chunks": 1,
                    "item_count": {"$size": "$item_count"},  # Number of unique items
                    "has_job_id": 1,
                    "title": {
                        "$cond": {
                            "if": {"$ne": ["$has_job_id", None]},
                            "then": {
                                "$concat": [
                                    {"$toString": {"$size": "$item_count"}},
                                    " ",
                                    "$content_type",
                                    "s uploaded"
                                ]
                            },
                            "else": "$sample_title"  # For old documents, use product/dealer name
                        }
                    }
                }
            },
            {"$sort": {"created_at": -1}},
            {"$skip": skip},
            {"$limit": limit}
        ]
        
        cursor = self.collection.aggregate(pipeline)
        documents = []
        async for doc in cursor:
            documents.append({
                "doc_id": doc["job_id"] or "unknown",  # Use job_id as doc_id
                "title": doc.get("title", "Uploaded items"),
                "content_type": doc.get("content_type"),
                "chunks_count": doc.get("total_chunks", 0),
                "item_count": doc.get("item_count", 0),  # Number of products/dealers in this upload
                "created_at": doc.get("created_at"),
                "is_legacy": doc.get("has_job_id") is None,  # Flag for old documents
            })
        
        return documents
    
    async def delete_document(self, doc_id: str, brand_id: str) -> bool:
        """Delete a document (or job batch) by ID."""
        await self._ensure_connection(brand_id)  # Use brand-specific database
        
        # First try deleting by job_id (new documents)
        result = await self.collection.delete_many({
            "metadata.job_id": doc_id,
            "metadata.brand_id": brand_id
        })
        
        # If nothing was deleted, try doc_id (old documents without job_id)
        if result.deleted_count == 0:
            result = await self.collection.delete_many({
                "doc_id": doc_id,
                "metadata.brand_id": brand_id
            })
        
        return result.deleted_count > 0
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    async def _extract_text(self, content: bytes, content_type: str, filename: str) -> str:
        """Extract text from different file types."""
        try:
            if content_type == "text/plain" or content_type == "text/markdown":
                return content.decode("utf-8")
            
            elif content_type == "text/html":
                # Simple HTML tag stripping (use BeautifulSoup in production)
                import re
                text = content.decode("utf-8")
                text = re.sub(r'<[^>]+>', '', text)
                return text
            
            elif content_type == "application/json":
                # For JSON files, pretty-print the content
                data = json.loads(content.decode("utf-8"))
                return json.dumps(data, indent=2)
            
            elif content_type == "application/pdf":
                # TODO: Implement PDF parsing (use PyPDF2 or pdfplumber)
                logger.warning("PDF parsing not yet implemented", filename=filename)
                return f"PDF content from {filename} (parsing pending)"
            
            elif content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                # TODO: Implement DOCX parsing (use python-docx)
                logger.warning("DOCX parsing not yet implemented", filename=filename)
                return f"DOCX content from {filename} (parsing pending)"
            
            else:
                return content.decode("utf-8", errors="ignore")
                
        except Exception as e:
            logger.error("Text extraction failed", filename=filename, error=str(e))
            raise Exception(f"Failed to extract text from {filename}: {str(e)}")
    
    async def _chunk_text(self, text: str, title: str = "") -> List[str]:
        """Chunk text into smaller pieces."""
        # Simple chunking strategy: split by paragraphs and combine into ~500 token chunks
        # TODO: Implement more sophisticated chunking (recursive character splitter)
        
        chunks = []
        paragraphs = text.split("\n\n")
        current_chunk = []
        current_length = 0
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # Rough token estimate (4 chars = 1 token)
            para_length = len(para) // 4
            
            if current_length + para_length > 500 and current_chunk:
                # Save current chunk
                chunks.append("\n\n".join(current_chunk))
                current_chunk = [para]
                current_length = para_length
            else:
                current_chunk.append(para)
                current_length += para_length
        
        # Add remaining chunk
        if current_chunk:
            chunks.append("\n\n".join(current_chunk))
        
        # If no chunks created, use full text
        if not chunks:
            chunks = [text]
        
        return chunks
    
    async def _generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using Voyage AI."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.voyageai.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.voyage_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "input": texts,
                        "model": self.voyage_model
                    }
                )
                
                response.raise_for_status()
                data = response.json()
                
                # Extract embeddings
                embeddings = [item["embedding"] for item in data["data"]]
                return embeddings
                
        except Exception as e:
            logger.error("Embedding generation failed", error=str(e))
            # Return empty embeddings on failure (for development)
            return [[] for _ in texts]
