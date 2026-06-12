"""
Knowledge Service - Enhanced document processing with structured metadata
Handles both document uploads and bulk JSON imports for products/dealers
"""

import csv
import html
import io
import uuid
import json
import re
from typing import List, Optional, Dict, Any
from datetime import datetime
import structlog
import httpx
from pymongo import UpdateOne

from ..config import Settings
from ..connections import connection_manager
from .chunking import chunk_text, resolve_agent_chunking
from .job_store import JobStore
from .qdrant_vector_service import QdrantVectorService
from .runtime_settings_service import RuntimeSettingsService

logger = structlog.get_logger()


class KnowledgeService:
    """Service for knowledge base operations with structured metadata support."""

    MIME_SOURCE_TYPES = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "text/plain": "txt",
        "text/markdown": "md",
        "text/x-markdown": "md",
        "text/html": "html",
        "application/xhtml+xml": "html",
        "application/json": "json",
        "text/json": "json",
        "text/csv": "csv",
        "application/csv": "csv",
        "application/vnd.ms-excel": "csv",
    }

    EXTENSION_SOURCE_TYPES = {
        ".pdf": "pdf",
        ".docx": "docx",
        ".txt": "txt",
        ".md": "md",
        ".markdown": "md",
        ".html": "html",
        ".htm": "html",
        ".json": "json",
        ".csv": "csv",
    }
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.job_store = JobStore()
        self.runtime_settings_service = RuntimeSettingsService(settings)
        self.qdrant = QdrantVectorService(settings) if settings.VECTOR_BACKEND == "qdrant" else None
        self.mongo_client = None
        self.db_cache = {}  # Cache brand-specific databases
        self.brand_scope_cache = {}
        self.db = None
        self.collection = None

    def _normalize_folder_path(self, path: Optional[str]) -> str:
        raw_path = (path or "/").strip()
        if not raw_path:
            raw_path = "/"
        if not raw_path.startswith("/"):
            raw_path = f"/{raw_path}"
        normalized = re.sub(r"/+", "/", raw_path).rstrip("/")
        return normalized or "/"

    def _normalize_item_path(self, folder: Optional[str], name: Optional[str]) -> tuple[str, str, str]:
        clean_folder = self._normalize_folder_path(folder)
        clean_name = (name or "untitled").strip().strip("/") or "untitled"
        return clean_folder, clean_name, f"{clean_folder.rstrip('/')}/{clean_name}" if clean_folder != "/" else f"/{clean_name}"

    def folder_path_from_name(self, name: Optional[str], parent_path: Optional[str] = None) -> str:
        _, clean_name, path = self._normalize_item_path(parent_path, name)
        return path if clean_name else self._normalize_folder_path(parent_path)

    async def _get_knowledge_folders_collection(self, brand_id: str):
        db = await self._get_brand_database(brand_id)
        return db["knowledge_folders"]

    async def _get_voyage_runtime_config(self) -> Dict[str, str]:
        config = await self.runtime_settings_service.get_voyage_runtime_config()
        return {
            "api_key": config["api_key"],
            "base_url": config["base_url"],
            "model": config["model"],
        }
    
    async def _resolve_brand_scope(self, identifier: str) -> Dict[str, Any]:
        """Resolve a brand UUID, brand slug, or agent ID into DB name and query aliases."""
        if identifier in self.brand_scope_cache:
            return self.brand_scope_cache[identifier]

        aliases: List[str] = []

        def add_alias(value: Optional[str]) -> None:
            if value and value not in aliases:
                aliases.append(value)

        add_alias(identifier)
        brand_slug: Optional[str] = None
        canonical_brand_id: Optional[str] = None

        try:
            system_db = connection_manager.get_system_db()

            brand = await system_db.brands.find_one({
                "$or": [
                    {"id": identifier},
                    {"slug": identifier},
                ]
            })
            if brand:
                canonical_brand_id = brand.get("id")
                brand_slug = brand.get("slug") or brand.get("id")
                add_alias(canonical_brand_id)
                add_alias(brand_slug)

            agent = await system_db.agents.find_one({"id": identifier})
            if agent:
                add_alias(agent.get("id"))
                add_alias(agent.get("brand_id"))
                add_alias(agent.get("brand_slug"))
                if not canonical_brand_id:
                    canonical_brand_id = agent.get("brand_id")
                if not brand_slug:
                    brand_slug = agent.get("brand_slug")

                if agent.get("brand_id") or agent.get("brand_slug"):
                    agent_brand = await system_db.brands.find_one({
                        "$or": [
                            {"id": agent.get("brand_id")},
                            {"slug": agent.get("brand_slug")},
                        ]
                    })
                    if agent_brand:
                        canonical_brand_id = agent_brand.get("id") or canonical_brand_id
                        brand_slug = agent_brand.get("slug") or brand_slug
                        add_alias(canonical_brand_id)
                        add_alias(brand_slug)
        except Exception as exc:
            logger.warning("brand_scope_resolution_failed", identifier=identifier, error=str(exc))

        primary_db_key = brand_slug or identifier
        scope = {
            "identifier": identifier,
            "brand_id": canonical_brand_id or identifier,
            "brand_slug": brand_slug,
            "aliases": aliases,
            "db_name": primary_db_key.replace('.', '_')[:63],
        }

        for alias in aliases:
            self.brand_scope_cache[alias] = scope
        self.brand_scope_cache[identifier] = scope
        return scope

    async def _get_brand_database(self, brand_id: str):
        """
        Get brand-specific database.
        
        Accepts a brand UUID, brand slug, or agent ID and resolves to the
        canonical brand database. This keeps old rows visible even when callers
        switch between UUID and slug identifiers.
        """
        # Check if already cached
        if brand_id in self.db_cache:
            return self.db_cache[brand_id]
        
        # Get the MongoDB client from connection manager
        mongo_client = connection_manager.mongodb_client
        if not mongo_client:
            raise RuntimeError("MongoDB not connected")
        
        scope = await self._resolve_brand_scope(brand_id)
        db_name = scope["db_name"]
        self.db_cache[brand_id] = mongo_client[db_name]
        logger.info(
            "brand_database_accessed",
            brand_id=brand_id,
            brand_slug=scope.get("brand_slug"),
            aliases=scope.get("aliases"),
            db_name=db_name,
        )
        
        return self.db_cache[brand_id]

    async def _get_brand_knowledge_collections(self, brand_id: str):
        """Return canonical and legacy knowledge collections for a brand scope."""
        mongo_client = connection_manager.mongodb_client
        if not mongo_client:
            raise RuntimeError("MongoDB not connected")

        scope = await self._resolve_brand_scope(brand_id)
        db_names: List[str] = []

        def add_db_name(value: Optional[str]) -> None:
            if not value:
                return
            db_name = value.replace('.', '_')[:63]
            if db_name not in db_names:
                db_names.append(db_name)

        add_db_name(scope.get("db_name"))
        for alias in scope.get("aliases", []):
            add_db_name(alias)

        return [mongo_client[db_name]["knowledge_base"] for db_name in db_names]
    
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
        agent_id: Optional[str] = None,
        product_data: Optional[Any] = None,
        dealer_data: Optional[Any] = None,
        folder_path: Optional[str] = None,
    ) -> str:
        """Start a document upload job."""
        job_id = str(uuid.uuid4())
        source_type = self.detect_source_type(content_type_header, filename)
        
        await self.job_store.set(job_id, {
            "status": "pending",
            "type": "document",
            "filename": filename,
            "source_type": source_type,
            "content_type_header": content_type_header,
            "content_type": kb_content_type,
            "brand_id": brand_id,
            "agent_id": agent_id,
            "folder": self._normalize_folder_path(folder_path),
            "processed_chunks": 0,
            "total_chunks": 0,
            "created_at": datetime.utcnow().isoformat(),
            "error": None
        })

        return job_id
    
    async def start_bulk_upload(
        self,
        content_type: str,
        items: List[Any],
        brand_id: str
    ) -> str:
        """Start a bulk JSON upload job."""
        job_id = str(uuid.uuid4())
        
        await self.job_store.set(job_id, {
            "status": "pending",
            "type": "bulk",
            "content_type": content_type,
            "brand_id": brand_id,
            "total_items": len(items),
            "processed_items": 0,
            "processed_chunks": 0,
            "created_at": datetime.utcnow().isoformat(),
            "error": None
        })

        return job_id
    
    async def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get job status."""
        job = await self.job_store.get(job_id)
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
        agent_id: Optional[str] = None,
        product_data: Optional[Any] = None,
        dealer_data: Optional[Any] = None,
        folder_path: Optional[str] = None,
    ):
        """Process a document upload in background."""
        try:
            await self._ensure_connection(brand_id)  # Use brand-specific database
            brand_scope = await self._resolve_brand_scope(brand_id)
            await self.job_store.update(job_id, {"status": "processing"})

            # Extract text from document
            text = await self._extract_text(content, content_type_header, filename)
            source_type = self.detect_source_type(content_type_header, filename) or "unknown"

            # Chunk the text (per-agent chunking config applies when agent_id is set)
            chunks = await self._chunk_text(text, filename, agent_id=agent_id)
            await self.job_store.update(job_id, {"total_chunks": len(chunks)})
            
            # Generate doc_id
            doc_id = f"{brand_id}_{kb_content_type}_{uuid.uuid4().hex[:8]}"
            folder, name, path = self._normalize_item_path(folder_path, filename)
            
            # Process each chunk
            for i, chunk_text in enumerate(chunks):
                # Generate embedding
                embedding = await self._generate_embeddings([chunk_text])
                
                # Build chunk document
                chunk_doc = {
                    "doc_id": doc_id,
                    "chunk_id": f"{doc_id}_chunk_{i}",
                    "content": chunk_text,
                    "embeddings": embedding[0] if embedding else [],
                    "title": filename,
                    
                    # Enhanced metadata
                    "content_type": kb_content_type,  # product, dealer, faq, etc.
                    "metadata": {
                        "brand_id": brand_scope.get("brand_id") or brand_id,
                        "brand_slug": brand_scope.get("brand_slug"),
                        "agent_id": agent_id,
                        "filename": filename,
                        "name": name,
                        "folder": folder,
                        "path": path,
                        "content_type_header": content_type_header,
                        "source_type": source_type,
                        "job_id": job_id,
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
                if self.qdrant:
                    await self.qdrant.upsert_chunk(chunk_doc, brand_scope.get("brand_slug") or brand_id)
                
                # Update progress
                await self.job_store.update(job_id, {"processed_chunks": i + 1})

            await self.job_store.update(job_id, {"status": "completed"})
            logger.info(
                "Document upload completed",
                job_id=job_id,
                doc_id=doc_id,
                chunks=len(chunks)
            )

        except Exception as e:
            await self.job_store.update(job_id, {"status": "error", "error": str(e)})
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
            brand_scope = await self._resolve_brand_scope(brand_id)
            await self.job_store.update(job_id, {"status": "processing"})

            for i, item in enumerate(items):
                if content_type == "product":
                    await self._process_product_item(item, brand_id, job_id, brand_scope)
                elif content_type == "dealer":
                    await self._process_dealer_item(item, brand_id, job_id, brand_scope)

                # Update progress
                await self.job_store.update(job_id, {"processed_items": i + 1})

            await self.job_store.update(job_id, {"status": "completed"})
            logger.info(
                "Bulk upload completed",
                job_id=job_id,
                items=len(items),
                content_type=content_type
            )

        except Exception as e:
            await self.job_store.update(job_id, {"status": "error", "error": str(e)})
            logger.error("Bulk upload failed", job_id=job_id, error=str(e))
    
    async def _process_product_item(self, item: Any, brand_id: str, job_id: str, brand_scope: Optional[Dict[str, Any]] = None):
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
                "embeddings": embedding[0] if embedding else [],
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
                    "brand_id": (brand_scope or {}).get("brand_id") or brand_id,
                    "brand_slug": (brand_scope or {}).get("brand_slug"),
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
            if self.qdrant:
                await self.qdrant.upsert_chunk(chunk_doc, (brand_scope or {}).get("brand_slug") or brand_id)
            
            # Update progress (fire-and-forget increment)
            job = await self.job_store.get(job_id) or {}
            await self.job_store.update(job_id, {"processed_chunks": job.get("processed_chunks", 0) + 1})
    
    async def _process_dealer_item(self, item: Any, brand_id: str, job_id: str, brand_scope: Optional[Dict[str, Any]] = None):
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
                "embeddings": embedding[0] if embedding else [],
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
                    "brand_id": (brand_scope or {}).get("brand_id") or brand_id,
                    "brand_slug": (brand_scope or {}).get("brand_slug"),
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
            if self.qdrant:
                await self.qdrant.upsert_chunk(chunk_doc, (brand_scope or {}).get("brand_slug") or brand_id)
            
            # Update progress (fire-and-forget increment)
            job = await self.job_store.get(job_id) or {}
            await self.job_store.update(job_id, {"processed_chunks": job.get("processed_chunks", 0) + 1})
    
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
        brand_scope = await self._resolve_brand_scope(brand_id)
        brand_aliases = brand_scope.get("aliases") or [brand_id]
        
        # Build query - check both brand_id and brand_slug for compatibility
        brand_filter = {
            "$or": [
                {"metadata.brand_id": {"$in": brand_aliases}},
                {"metadata.brand_slug": {"$in": brand_aliases}},
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
        
        # Aggregate to group by job_id (upload batch).
        # For old documents without job_id, group by doc_id instead.
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
        ]
        
        documents_by_id: Dict[str, Dict[str, Any]] = {}
        for collection in await self._get_brand_knowledge_collections(brand_id):
            cursor = collection.aggregate(pipeline)
            async for doc in cursor:
                doc_id = doc["job_id"] or "unknown"
                existing = documents_by_id.get(doc_id)
                if existing and existing.get("chunks_count", 0) >= doc.get("total_chunks", 0):
                    continue

                documents_by_id[doc_id] = {
                    "doc_id": doc["job_id"] or "unknown",  # Use job_id as doc_id
                    "title": doc.get("title", "Uploaded items"),
                    "content_type": doc.get("content_type"),
                    "chunks_count": doc.get("total_chunks", 0),
                    "item_count": doc.get("item_count", 0),  # Number of products/dealers in this upload
                    "created_at": doc.get("created_at"),
                    "is_legacy": doc.get("has_job_id") is None,  # Flag for old documents
                }
        
        documents = sorted(
            documents_by_id.values(),
            key=lambda doc: doc.get("created_at") or "",
            reverse=True,
        )
        
        return documents[skip:skip + limit]

    async def list_knowledge_tree(
        self,
        brand_id: str,
        agent_id: Optional[str] = None,
        folder: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return folder and document nodes with filesystem-like paths."""
        brand_scope = await self._resolve_brand_scope(brand_id)
        brand_aliases = brand_scope.get("aliases") or [brand_id]
        selected_folder = self._normalize_folder_path(folder)
        brand_filter: Dict[str, Any] = {
            "$or": [
                {"metadata.brand_id": {"$in": brand_aliases}},
                {"metadata.brand_slug": {"$in": brand_aliases}},
            ]
        }
        if agent_id:
            brand_filter = {"$and": [brand_filter, {"metadata.agent_id": agent_id}]}

        folder_query: Dict[str, Any] = {"brand_id": brand_scope.get("brand_id") or brand_id}
        if agent_id:
            folder_query["agent_id"] = agent_id

        folders_collection = await self._get_knowledge_folders_collection(brand_id)
        folders = [{
            "id": "/",
            "type": "folder",
            "name": "/",
            "path": "/",
            "parent_path": None,
            "created_at": None,
            "updated_at": None,
        }]
        async for folder_doc in folders_collection.find(folder_query).sort("path", 1):
            folders.append({
                "id": folder_doc.get("id") or folder_doc.get("path"),
                "type": "folder",
                "name": folder_doc.get("name"),
                "path": folder_doc.get("path"),
                "parent_path": folder_doc.get("parent_path") or "/",
                "created_at": folder_doc.get("created_at"),
                "updated_at": folder_doc.get("updated_at"),
            })

        documents_by_id: Dict[str, Dict[str, Any]] = {}
        pipeline = [
            {"$match": brand_filter},
            {
                "$group": {
                    "_id": {"$ifNull": ["$metadata.job_id", "$doc_id"]},
                    "doc_id": {"$first": "$doc_id"},
                    "content_type": {"$first": "$content_type"},
                    "title": {"$first": "$title"},
                    "created_at": {"$first": "$metadata.created_at"},
                    "updated_at": {"$max": "$metadata.updated_at"},
                    "folder": {"$first": "$metadata.folder"},
                    "path": {"$first": "$metadata.path"},
                    "name": {"$first": "$metadata.name"},
                    "source_type": {"$first": "$metadata.source_type"},
                    "content_type_header": {"$first": "$metadata.content_type_header"},
                    "agent_id": {"$first": "$metadata.agent_id"},
                    "chunks_count": {"$sum": 1},
                    "item_ids": {"$addToSet": "$doc_id"},
                }
            },
        ]
        for collection in await self._get_brand_knowledge_collections(brand_id):
            async for doc in collection.aggregate(pipeline):
                item_id = doc.get("_id") or doc.get("doc_id")
                if not item_id:
                    continue
                folder_path = self._normalize_folder_path(doc.get("folder"))
                name = doc.get("name") or doc.get("title") or item_id
                path = doc.get("path") or self._normalize_item_path(folder_path, name)[2]
                documents_by_id[str(item_id)] = {
                    "id": str(item_id),
                    "type": "file",
                    "doc_id": str(item_id),
                    "name": name,
                    "title": doc.get("title") or name,
                    "path": path,
                    "folder": folder_path,
                    "parent_path": folder_path,
                    "content_type": doc.get("content_type"),
                    "source_type": doc.get("source_type"),
                    "content_type_header": doc.get("content_type_header"),
                    "agent_id": doc.get("agent_id"),
                    "chunks_count": doc.get("chunks_count", 0),
                    "item_count": len(doc.get("item_ids") or []),
                    "created_at": doc.get("created_at"),
                    "updated_at": doc.get("updated_at") or doc.get("created_at"),
                    "status": "ready",
                }

        all_folders = {folder["path"] for folder in folders if folder.get("path")}
        for document in documents_by_id.values():
            current = document.get("folder") or "/"
            while current and current not in all_folders:
                parent = self._normalize_folder_path("/".join(current.rstrip("/").split("/")[:-1]) or "/")
                folders.append({
                    "id": current,
                    "type": "folder",
                    "name": current.rstrip("/").split("/")[-1] or "/",
                    "path": current,
                    "parent_path": None if current == "/" else parent,
                    "created_at": None,
                    "updated_at": None,
                    "virtual": True,
                })
                all_folders.add(current)
                if current == "/":
                    break
                current = parent

        folder_nodes: Dict[str, Dict[str, Any]] = {}
        for folder_item in folders:
            path = folder_item.get("path") or "/"
            folder_nodes[path] = {
                "id": folder_item.get("id"),
                "name": folder_item.get("name") or (path.rstrip("/").split("/")[-1] or "Knowledge Base"),
                "path": path,
                "parent_id": folder_item.get("parent_path"),
                "parent_path": folder_item.get("parent_path"),
                "children": [],
                "items": [],
                "documents": [],
            }
        folder_nodes.setdefault("/", {
            "id": None,
            "name": "Knowledge Base",
            "path": "/",
            "parent_id": None,
            "parent_path": None,
            "children": [],
            "items": [],
            "documents": [],
        })

        for path, folder_item in sorted(folder_nodes.items(), key=lambda item: item[0]):
            if path == "/":
                continue
            parent_path = folder_item.get("parent_path") or self._normalize_folder_path("/".join(path.rstrip("/").split("/")[:-1]) or "/")
            parent = folder_nodes.setdefault(parent_path, {
                "id": None if parent_path == "/" else parent_path,
                "name": "Knowledge Base" if parent_path == "/" else parent_path.rstrip("/").split("/")[-1],
                "path": parent_path,
                "parent_id": None,
                "parent_path": None,
                "children": [],
                "items": [],
                "documents": [],
            })
            if not any(child.get("path") == path for child in parent["children"]):
                parent["children"].append(folder_item)

        file_items = []
        for document in documents_by_id.values():
            item = {
                **document,
                "kind": "document",
                "id": document.get("id"),
                "source_doc_id": document.get("doc_id"),
                "parent_id": document.get("parent_path"),
            }
            file_items.append(item)
            folder_nodes.setdefault(document.get("folder") or "/", folder_nodes["/"])["items"].append(item)

        children = [
            item for item in [*folder_nodes.get(selected_folder, {}).get("children", []), *folder_nodes.get(selected_folder, {}).get("items", [])]
        ]

        return {
            "root": folder_nodes["/"],
            "selected_folder": selected_folder,
            "folders": sorted(folders, key=lambda item: item.get("path") or ""),
            "files": sorted(file_items, key=lambda item: item.get("updated_at") or "", reverse=True),
            "items": folder_nodes["/"].get("items", []),
            "children": children,
        }

    async def create_folder(
        self,
        brand_id: str,
        path: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        folder_path = self._normalize_folder_path(path)
        if folder_path == "/":
            raise ValueError("Root folder already exists")
        parent_path = self._normalize_folder_path("/".join(folder_path.rstrip("/").split("/")[:-1]) or "/")
        now = datetime.utcnow().isoformat()
        brand_scope = await self._resolve_brand_scope(brand_id)
        folder_doc = {
            "id": folder_path,
            "brand_id": brand_scope.get("brand_id") or brand_id,
            "brand_slug": brand_scope.get("brand_slug"),
            "agent_id": agent_id,
            "name": folder_path.rstrip("/").split("/")[-1],
            "path": folder_path,
            "parent_path": parent_path,
            "created_at": now,
            "updated_at": now,
        }
        collection = await self._get_knowledge_folders_collection(brand_id)
        await collection.update_one(
            {"brand_id": folder_doc["brand_id"], "agent_id": agent_id, "path": folder_path},
            {"$setOnInsert": folder_doc, "$set": {"updated_at": now}},
            upsert=True,
        )
        return {**folder_doc, "type": "folder"}

    async def move_item(
        self,
        brand_id: str,
        item_id: str,
        target_folder: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        target_folder = self._normalize_folder_path(target_folder)
        brand_scope = await self._resolve_brand_scope(brand_id)
        brand_aliases = brand_scope.get("aliases") or [brand_id]
        updated = 0
        item_name = None

        for collection in await self._get_brand_knowledge_collections(brand_id):
            query = {
                "$and": [
                    {
                        "$or": [
                            {"metadata.job_id": item_id},
                            {"doc_id": item_id},
                        ]
                    },
                    {
                        "$or": [
                            {"metadata.brand_id": {"$in": brand_aliases}},
                            {"metadata.brand_slug": {"$in": brand_aliases}},
                        ]
                    },
                ]
            }
            if agent_id:
                query["$and"].append({"metadata.agent_id": agent_id})
            first = await collection.find_one(query)
            if first and not item_name:
                item_name = (first.get("metadata") or {}).get("name") or first.get("title") or item_id
            folder, name, path = self._normalize_item_path(target_folder, item_name or item_id)
            result = await collection.update_many(
                query,
                {"$set": {
                    "metadata.folder": folder,
                    "metadata.name": name,
                    "metadata.path": path,
                    "metadata.updated_at": datetime.utcnow().isoformat(),
                }},
            )
            updated += result.modified_count

        if updated == 0:
            return {}
        return {"id": item_id, "folder": target_folder, "path": self._normalize_item_path(target_folder, item_name or item_id)[2]}

    async def rename_item(
        self,
        brand_id: str,
        item_id: str,
        name: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_name = name.strip().strip("/")
        if not clean_name:
            raise ValueError("Name is required")
        brand_scope = await self._resolve_brand_scope(brand_id)
        brand_aliases = brand_scope.get("aliases") or [brand_id]

        folders_collection = await self._get_knowledge_folders_collection(brand_id)
        folder_query = {"brand_id": brand_scope.get("brand_id") or brand_id, "path": item_id}
        if agent_id:
            folder_query["agent_id"] = agent_id
        folder_doc = await folders_collection.find_one(folder_query)
        if folder_doc:
            parent = folder_doc.get("parent_path") or "/"
            new_path = self._normalize_item_path(parent, clean_name)[2]
            await folders_collection.update_one(folder_query, {"$set": {"name": clean_name, "path": new_path, "id": new_path, "updated_at": datetime.utcnow().isoformat()}})
            return {"id": new_path, "type": "folder", "name": clean_name, "path": new_path, "parent_path": parent}

        updated = 0
        next_path = None
        for collection in await self._get_brand_knowledge_collections(brand_id):
            query = {
                "$and": [
                    {
                        "$or": [
                            {"metadata.job_id": item_id},
                            {"doc_id": item_id},
                        ]
                    },
                    {
                        "$or": [
                            {"metadata.brand_id": {"$in": brand_aliases}},
                            {"metadata.brand_slug": {"$in": brand_aliases}},
                        ]
                    },
                ]
            }
            if agent_id:
                query["$and"].append({"metadata.agent_id": agent_id})
            first = await collection.find_one(query)
            folder = self._normalize_folder_path((first or {}).get("metadata", {}).get("folder") if first else "/")
            _, _, path = self._normalize_item_path(folder, clean_name)
            next_path = path
            result = await collection.update_many(
                query,
                {"$set": {
                    "title": clean_name,
                    "metadata.filename": clean_name,
                    "metadata.name": clean_name,
                    "metadata.path": path,
                    "metadata.updated_at": datetime.utcnow().isoformat(),
                }},
            )
            updated += result.modified_count

        if updated == 0:
            return {}
        return {"id": item_id, "type": "file", "name": clean_name, "path": next_path}

    async def retrieve(
        self,
        brand_id: str,
        query: str,
        folder: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 10,
        score_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Lightweight admin retrieval preview over stored chunks."""
        brand_scope = await self._resolve_brand_scope(brand_id)
        brand_aliases = brand_scope.get("aliases") or [brand_id]
        query_text = query.strip()
        if not query_text:
            return []

        filters: List[Dict[str, Any]] = [{
            "$or": [
                {"metadata.brand_id": {"$in": brand_aliases}},
                {"metadata.brand_slug": {"$in": brand_aliases}},
            ]
        }]
        if agent_id:
            filters.append({"metadata.agent_id": agent_id})
        if folder:
            folder_path = self._normalize_folder_path(folder)
            filters.append({"metadata.folder": {"$regex": f"^{re.escape(folder_path)}(/|$)"}})

        mongo_query = {"$and": filters}
        tokens = [token.lower() for token in re.findall(r"\w+", query_text) if len(token) > 2]
        results: List[Dict[str, Any]] = []
        seen_chunks = set()

        for collection in await self._get_brand_knowledge_collections(brand_id):
            cursor = collection.find(mongo_query).limit(500)
            async for doc in cursor:
                chunk_id = doc.get("chunk_id") or str(doc.get("_id"))
                if chunk_id in seen_chunks:
                    continue
                seen_chunks.add(chunk_id)
                content = doc.get("content") or ""
                lower_content = content.lower()
                score = 0.0
                if tokens:
                    score = sum(lower_content.count(token) for token in tokens) / max(len(tokens), 1)
                if query_text.lower() in lower_content:
                    score += 3.0
                normalized_score = min(score / 5.0, 1.0)
                if normalized_score < score_threshold:
                    continue
                results.append({
                    "chunk_id": chunk_id,
                    "doc_id": doc.get("doc_id"),
                    "title": doc.get("title"),
                    "content": content,
                    "score": normalized_score,
                    "content_type": doc.get("content_type"),
                    "metadata": {
                        key: value
                        for key, value in (doc.get("metadata") or {}).items()
                        if key not in {"brand_id", "brand_slug"}
                    },
                })

        results.sort(key=lambda item: item.get("score", 0), reverse=True)
        return results[:limit]

    async def get_document_preview(
        self,
        doc_id: str,
        brand_id: str,
        limit: int = 8,
    ) -> Dict[str, Any]:
        """Fetch source metadata plus representative chunks/items for preview."""
        brand_scope = await self._resolve_brand_scope(brand_id)
        brand_aliases = brand_scope.get("aliases") or [brand_id]
        brand_match = {
            "$or": [
                {"metadata.brand_id": {"$in": brand_aliases}},
                {"metadata.brand_slug": {"$in": brand_aliases}},
            ]
        }
        source_match = {
            "$or": [
                {"metadata.job_id": doc_id},
                {"doc_id": doc_id},
            ]
        }
        query = {"$and": [brand_match, source_match]}

        chunks: List[Dict[str, Any]] = []
        seen_chunk_ids = set()
        item_keys = set()
        total_chunks = 0
        collections = await self._get_brand_knowledge_collections(brand_id)

        for collection in collections:
            total_chunks += await collection.count_documents(query)
            for item_key in await collection.distinct("doc_id", query):
                if item_key:
                    item_keys.add(item_key)

        for collection in collections:
            cursor = collection.find(query).sort("metadata.chunk_index", 1).limit(limit)
            async for doc in cursor:
                chunk_id = doc.get("chunk_id") or str(doc.get("_id"))
                if chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk_id)
                chunks.append(doc)
                if len(chunks) >= limit:
                    break
            if len(chunks) >= limit:
                break

        if not chunks:
            return {}

        first = chunks[0]
        samples = []
        for chunk in chunks:
            sample: Dict[str, Any] = {
                "chunk_id": chunk.get("chunk_id"),
                "title": chunk.get("title"),
                "content": chunk.get("content"),
                "content_type": chunk.get("content_type"),
                "metadata": {
                    key: value
                    for key, value in (chunk.get("metadata") or {}).items()
                    if key not in {"brand_id", "brand_slug"}
                },
            }
            if chunk.get("product_data"):
                sample["product_data"] = chunk.get("product_data")
            if chunk.get("dealer_data"):
                sample["dealer_data"] = chunk.get("dealer_data")
            samples.append(sample)

        return {
            "doc_id": doc_id,
            "title": first.get("title") or doc_id,
            "content_type": first.get("content_type"),
            "item_count": len(item_keys) or len(samples),
            "chunks_count": total_chunks or len(seen_chunk_ids),
            "created_at": (first.get("metadata") or {}).get("created_at"),
            "status": "ready",
            "samples": samples,
        }
    
    async def delete_document(self, doc_id: str, brand_id: str) -> bool:
        """Delete a document (or job batch) by ID."""
        await self._ensure_connection(brand_id)  # Use brand-specific database
        brand_scope = await self._resolve_brand_scope(brand_id)
        brand_aliases = brand_scope.get("aliases") or [brand_id]
        
        deleted_count = 0
        for collection in await self._get_brand_knowledge_collections(brand_id):
            # First try deleting by job_id (new documents)
            result = await collection.delete_many({
                "metadata.job_id": doc_id,
                "$or": [
                    {"metadata.brand_id": {"$in": brand_aliases}},
                    {"metadata.brand_slug": {"$in": brand_aliases}},
                ]
            })
            deleted_count += result.deleted_count
        
            # If nothing was deleted, try doc_id (old documents without job_id)
            if result.deleted_count == 0:
                result = await collection.delete_many({
                    "doc_id": doc_id,
                    "$or": [
                        {"metadata.brand_id": {"$in": brand_aliases}},
                        {"metadata.brand_slug": {"$in": brand_aliases}},
                    ]
                })
                deleted_count += result.deleted_count
        
        return deleted_count > 0
    
    # ========================================================================
    # Helper Methods
    # ========================================================================

    def detect_source_type(self, content_type: Optional[str], filename: Optional[str]) -> Optional[str]:
        """Normalize an uploaded file type from MIME header or filename extension."""
        normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
        if normalized_content_type in self.MIME_SOURCE_TYPES:
            return self.MIME_SOURCE_TYPES[normalized_content_type]

        normalized_filename = (filename or "").lower()
        for extension, source_type in self.EXTENSION_SOURCE_TYPES.items():
            if normalized_filename.endswith(extension):
                return source_type

        return None
    
    async def _extract_text(self, content: bytes, content_type: str, filename: str) -> str:
        """Extract text from different file types."""
        try:
            source_type = self.detect_source_type(content_type, filename)

            if source_type in {"txt", "md"}:
                return self._decode_text(content)
            
            elif source_type == "html":
                return self._extract_html_text(content)
            
            elif source_type == "json":
                # For JSON files, pretty-print the content
                data = json.loads(self._decode_text(content))
                return json.dumps(data, indent=2)
            
            elif source_type == "csv":
                return self._extract_csv_text(content)

            elif source_type == "pdf":
                return self._extract_pdf_text(content)
            
            elif source_type == "docx":
                return self._extract_docx_text(content)
            
            else:
                return self._decode_text(content)
                
        except Exception as e:
            logger.error("Text extraction failed", filename=filename, error=str(e))
            raise Exception(f"Failed to extract text from {filename}: {str(e)}")

    def _decode_text(self, content: bytes) -> str:
        """Decode uploaded text content with a forgiving UTF-8 default."""
        return content.decode("utf-8-sig", errors="replace")

    def _extract_html_text(self, content: bytes) -> str:
        """Extract readable text from lightweight HTML without adding a parser dependency."""
        text = self._decode_text(content)
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<br\s*/?>", "\n", text)
        text = re.sub(r"(?s)</(p|div|section|article|li|tr|h[1-6])>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        return re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", text)).strip()

    def _extract_csv_text(self, content: bytes) -> str:
        """Convert CSV rows into labeled plain text for chunking and retrieval."""
        text = self._decode_text(content)
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return ""

        headers = [header.strip() for header in rows[0]]
        try:
            has_headers = csv.Sniffer().has_header(text[:2048])
        except csv.Error:
            has_headers = any(headers) and len(rows) > 1
        if len(rows) == 1:
            has_headers = False
        extracted_rows = []

        for index, row in enumerate(rows[1:] if has_headers else rows, start=1):
            if has_headers:
                values = []
                for column_index, value in enumerate(row):
                    header = headers[column_index] if column_index < len(headers) and headers[column_index] else f"Column {column_index + 1}"
                    values.append(f"{header}: {value.strip()}")
                extracted_rows.append(f"Row {index}\n" + "\n".join(values))
            else:
                extracted_rows.append(f"Row {index}: " + ", ".join(value.strip() for value in row))

        return "\n\n".join(extracted_rows)

    def _extract_pdf_text(self, content: bytes) -> str:
        """Extract text from a PDF using pypdf."""
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF extraction requires pypdf to be installed") from exc

        reader = PdfReader(io.BytesIO(content))
        page_text = []
        for page_number, page in enumerate(reader.pages, start=1):
            extracted = page.extract_text() or ""
            extracted = extracted.strip()
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
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]

        table_rows = []
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    table_rows.append(" | ".join(cells))

        return "\n\n".join(paragraphs + table_rows)
    
    async def _chunk_text(self, text: str, title: str = "", agent_id: Optional[str] = None) -> List[str]:
        """Chunk text via the shared chunker, honoring the agent's rag.chunking config."""
        chunk_size, chunk_overlap = await resolve_agent_chunking(agent_id)
        return chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    
    async def _generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using Voyage AI."""
        voyage_config = await self._get_voyage_runtime_config()
        api_key = voyage_config["api_key"]
        base_url = voyage_config["base_url"].rstrip("/")
        model = voyage_config["model"]
        if not api_key:
            logger.warning("voyage_api_key_not_configured", texts_count=len(texts))
            return [[] for _ in texts]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "input": texts,
                        "model": model
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
