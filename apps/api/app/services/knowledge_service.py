"""
Knowledge Service - Enhanced document processing with structured metadata
Handles both document uploads and bulk JSON imports for products/dealers
"""

import asyncio
import uuid
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import structlog
import httpx
from pymongo import UpdateOne

from ..config import Settings
from ..connections import connection_manager
from .job_store import JobStore
from .qdrant_vector_service import QdrantVectorService
from .runtime_settings_service import RuntimeSettingsService

logger = structlog.get_logger()


class KnowledgeService:
    """Service for knowledge base operations with structured metadata support."""
    
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
        product_data: Optional[Any] = None,
        dealer_data: Optional[Any] = None
    ) -> str:
        """Start a document upload job."""
        job_id = str(uuid.uuid4())
        
        await self.job_store.set(job_id, {
            "status": "pending",
            "type": "document",
            "filename": filename,
            "content_type": kb_content_type,
            "brand_id": brand_id,
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
        product_data: Optional[Any] = None,
        dealer_data: Optional[Any] = None
    ):
        """Process a document upload in background."""
        try:
            await self._ensure_connection(brand_id)  # Use brand-specific database
            brand_scope = await self._resolve_brand_scope(brand_id)
            await self.job_store.update(job_id, {"status": "processing"})

            # Extract text from document
            text = await self._extract_text(content, content_type_header, filename)

            # Chunk the text
            chunks = await self._chunk_text(text, filename)
            await self.job_store.update(job_id, {"total_chunks": len(chunks)})
            
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
                    "embeddings": embedding[0] if embedding else [],
                    "title": filename,
                    
                    # Enhanced metadata
                    "content_type": kb_content_type,  # product, dealer, faq, etc.
                    "metadata": {
                        "brand_id": brand_scope.get("brand_id") or brand_id,
                        "brand_slug": brand_scope.get("brand_slug"),
                        "filename": filename,
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
        """Process bulk JSON upload in background using batch processing for efficiency."""
        BATCH_SIZE = 20
        try:
            await self._ensure_connection(brand_id)  # Use brand-specific database
            brand_scope = await self._resolve_brand_scope(brand_id)
            await self.job_store.update(job_id, {"status": "processing"})

            # Process items in batches
            for i in range(0, len(items), BATCH_SIZE):
                batch_items = items[i : i + BATCH_SIZE]
                batch_texts = []
                batch_docs_metadata = []

                # Phase 1: Prepare texts for the entire batch
                for item in batch_items:
                    text_parts = []
                    if content_type == "product":
                        text_parts = [
                            f"Product: {item.name}",
                            f"SKU: {item.sku}",
                            f"Category: {item.category}",
                            f"Price: {item.price} {item.currency}"
                        ]
                        if getattr(item, 'features', None):
                            text_parts.append(f"Features: {', '.join(item.features)}")
                        doc_id = f"{brand_id}_product_{item.sku}"
                    elif content_type == "dealer":
                        text_parts = [
                            f"Dealer: {item.name}",
                            f"Location: {item.city}",
                            f"Phone: {item.phone}"
                        ]
                        doc_id = f"{brand_id}_dealer_{item.dealer_id}"
                    
                    full_text = "\n".join(text_parts)
                    # We assume single chunk for batching efficiency, or we could chunk here
                    batch_texts.append(full_text)
                    batch_docs_metadata.append({"item": item, "doc_id": doc_id, "text": full_text})

                # Phase 2: Generate embeddings for the whole batch in ONE call
                logger.info("generating_batch_embeddings", batch_size=len(batch_texts), start_index=i)
                batch_embeddings = await self._generate_embeddings(batch_texts)

                # Phase 3: Save results to MongoDB
                for idx, embedding in enumerate(batch_embeddings):
                    metadata = batch_docs_metadata[idx]
                    item = metadata["item"]
                    doc_id = metadata["doc_id"]
                    
                    chunk_doc = {
                        "doc_id": doc_id,
                        "chunk_id": f"{doc_id}_chunk_0",
                        "content": metadata["text"],
                        "embeddings": embedding,
                        "title": item.name,
                        "content_type": content_type,
                        "metadata": {
                            "brand_id": (brand_scope or {}).get("brand_id") or brand_id,
                            "brand_slug": (brand_scope or {}).get("brand_slug"),
                            "job_id": job_id,
                            "chunk_index": 0,
                            "total_chunks": 1,
                            "created_at": datetime.utcnow().isoformat()
                        }
                    }

                    if content_type == "product":
                        chunk_doc["product_data"] = {
                            "sku": item.sku,
                            "name": item.name,
                            "price": item.price,
                            "currency": item.currency,
                            "category": item.category,
                            "image_url": getattr(item, 'image_url', None),
                            "product_url": getattr(item, 'product_url', None),
                            "in_stock": getattr(item, 'in_stock', True),
                            "features": getattr(item, 'features', [])
                        }
                    elif content_type == "dealer":
                        chunk_doc["dealer_data"] = {
                            "dealer_id": item.dealer_id,
                            "name": item.name,
                            "city": item.city,
                            "phone": item.phone,
                            "state": getattr(item, 'state', None),
                            "email": getattr(item, 'email', None),
                            "address": getattr(item, 'address', None)
                        }

                    # Upsert to MongoDB
                    await self.collection.update_one(
                        {"doc_id": doc_id, "chunk_id": chunk_doc["chunk_id"]},
                        {"$set": chunk_doc},
                        upsert=True
                    )
                    if self.qdrant:
                        await self.qdrant.upsert_chunk(chunk_doc, (brand_scope or {}).get("brand_slug") or brand_id)

                # Update progress
                processed_so_far = min(i + BATCH_SIZE, len(items))
                await self.job_store.update(job_id, {
                    "processed_items": processed_so_far,
                    "processed_chunks": processed_so_far # Each item is 1 chunk in batch mode
                })
                
                # BREATHE: Even with batching, wait between batches to be safe
                if processed_so_far < len(items):
                    await asyncio.sleep(2.0)
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
        """Generate embeddings using Voyage AI with exponential backoff for 429 errors."""
        voyage_config = await self._get_voyage_runtime_config()
        api_key = voyage_config["api_key"]
        base_url = voyage_config["base_url"].rstrip("/")
        model = voyage_config["model"]
        
        if not api_key:
            logger.warning("voyage_api_key_not_configured", texts_count=len(texts))
            return [[] for _ in texts]

        max_retries = 10
        base_delay = 10.0  # seconds
        logger.info("starting_embedding_generation", texts_count=len(texts), base_delay=base_delay, max_retries=max_retries)
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
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
                    
                    if response.status_code == 429:
                        if attempt < max_retries - 1:
                            wait_time = base_delay * (2 ** attempt)
                            logger.warning("embedding_rate_limited_retrying", attempt=attempt+1, wait_time=wait_time)
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error("embedding_rate_limit_exhausted", max_retries=max_retries)
                            raise RuntimeError(f"Voyage AI rate limit exhausted after {max_retries} retries")
                        
                    response.raise_for_status()
                    data = response.json()
                    
                    # Extract embeddings
                    embeddings = [item["embedding"] for item in data["data"]]
                    return embeddings
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    logger.warning("embedding_generation_retry", attempt=attempt+1, error=str(e), wait_time=wait_time)
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error("Embedding generation failed after retries", error=str(e))
                    raise
        
        raise RuntimeError("Embedding generation failed due to unknown loop termination")
