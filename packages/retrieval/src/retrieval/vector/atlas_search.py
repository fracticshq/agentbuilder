"""
MongoDB Atlas Vector Search implementation
"""

import os
from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorClient
import structlog

from .voyage_client import VoyageClient
from ..types import DocumentChunk, SearchResult

logger = structlog.get_logger()


class AtlasVectorSearch:
    """MongoDB Atlas Vector Search with Voyage embeddings."""
    
    def __init__(
        self,
        collection_name: str = "knowledge_base",
        index_name: str = "vector_index",
        voyage_client: Optional[VoyageClient] = None,
        brand_id: Optional[str] = None  # Brand ID for database isolation
    ):
        # MongoDB connection
        mongodb_uri = os.getenv("MONGODB_URI")
        if not mongodb_uri:
            raise ValueError("MONGODB_URI environment variable not set")
        
        # Use brand_id as database name for isolation
        if brand_id:
            db_name = brand_id.replace('.', '_')[:63]  # MongoDB db name max 63 chars
        else:
            db_name = os.getenv("MONGODB_DATABASE", "agent-builder")
        
        self.client = AsyncIOMotorClient(mongodb_uri)
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]
        self.index_name = index_name
        self.brand_id = brand_id
        
        # Voyage embeddings client
        self.voyage = voyage_client or VoyageClient()
        
        logger.info(
            "Atlas Vector Search initialized",
            brand_id=brand_id,
            database=db_name,
            collection=collection_name,
            index=index_name
        )
    
    async def search(
        self,
        query: str,
        top_k: int = 50,
        filters: Optional[Dict[str, Any]] = None,
        similarity_threshold: float = 0.7
    ) -> SearchResult:
        """
        Perform vector similarity search.
        
        Args:
            query: Search query text
            top_k: Number of results to return
            filters: Optional metadata filters
            similarity_threshold: Minimum similarity score
        
        Returns:
            SearchResult with matched chunks
        """
        if getattr(self.voyage, "auth_failed", False):
            logger.warning("vector_search_skipped_voyage_auth_failed", query_length=len(query))
            return SearchResult(
                chunks=[],
                total_found=0,
                query=query,
                search_type="vector",
                execution_time_ms=0.0,
                metadata={"disabled_reason": "voyage_auth_failed"},
                backend_status="unavailable",
                backend_reason="authentication_failed",
            )

        try:
            import time
            start_time = time.time()
            
            # Generate query embedding
            query_embedding = await self.voyage.embed_query(query)
            
            # Build aggregation pipeline
            pipeline = self._build_vector_search_pipeline(
                query_embedding=query_embedding,
                top_k=top_k,
                filters=filters
            )
            
            # Execute search
            cursor = self.collection.aggregate(pipeline)
            results = await cursor.to_list(length=top_k)
            
            # Filter by threshold and convert to chunks
            chunks = []
            for result in results:
                score = result.get("score", 0.0)
                if score >= similarity_threshold:
                    chunk = self._result_to_chunk(result, score)
                    chunks.append(chunk)
            
            execution_time = (time.time() - start_time) * 1000
            
            logger.info(
                "Vector search completed",
                query_length=len(query),
                results_found=len(chunks),
                execution_time_ms=execution_time
            )
            
            return SearchResult(
                chunks=chunks,
                total_found=len(chunks),
                query=query,
                search_type="vector",
                execution_time_ms=execution_time,
                metadata={
                    "top_k": top_k,
                    "threshold": similarity_threshold,
                    "filters": filters or {}
                }
            )
            
        except Exception as e:
            logger.error("Vector search error", error=str(e), query=query[:100])
            raise
    
    def _build_vector_search_pipeline(
        self,
        query_embedding: List[float],
        top_k: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Build MongoDB aggregation pipeline for vector search."""
        
        # Vector search stage
        vector_search = {
            "$vectorSearch": {
                "index": self.index_name,
                "path": "embeddings",
                "queryVector": query_embedding,
                "numCandidates": min(top_k * 10, 1000),  # Oversampling
                "limit": top_k
            }
        }
        
        # Add filters if provided
        if filters:
            vector_search["$vectorSearch"]["filter"] = filters
        
        # Pipeline stages
        pipeline = [
            vector_search,
            {
                "$addFields": {
                    "score": {"$meta": "vectorSearchScore"}
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "chunk_id": 1,
                    "doc_id": 1,
                    "content": 1,
                    "title": 1,
                    "url": 1,
                    "section": 1,
                    "metadata": 1,
                    "score": 1,
                    "created_at": 1,
                    # Phase 2: Include structured data fields
                    "content_type": 1,
                    "product_data": 1,
                    "dealer_data": 1
                }
            }
        ]
        
        return pipeline
    
    def _result_to_chunk(self, result: Dict[str, Any], score: float) -> DocumentChunk:
        """Convert MongoDB result to DocumentChunk."""
        return DocumentChunk(
            chunk_id=result.get("chunk_id", str(result.get("_id"))),
            doc_id=result.get("doc_id", "unknown"),
            content=result.get("content", ""),
            title=result.get("title"),
            url=result.get("url"),
            section=result.get("section"),
            score=score,
            metadata=result.get("metadata", {}),
            created_at=result.get("created_at"),
            # Phase 2: Add structured data fields
            content_type=result.get("content_type"),
            product_data=result.get("product_data"),
            dealer_data=result.get("dealer_data")
        )
    
    async def index_documents(
        self,
        documents: List[Dict[str, Any]],
        batch_size: int = 100
    ) -> int:
        """
        Index documents with embeddings.
        
        Args:
            documents: List of documents to index (must have 'content' field)
            batch_size: Batch size for embedding generation
        
        Returns:
            Number of documents indexed
        """
        try:
            indexed_count = 0
            
            # Process in batches
            for i in range(0, len(documents), batch_size):
                batch = documents[i:i + batch_size]
                
                # Extract content for embedding
                texts = [doc.get("content", "") for doc in batch]
                
                # Generate embeddings
                embeddings = await self.voyage.embed_documents(texts)
                
                # Add embeddings to documents
                docs_to_insert = []
                for doc, embedding in zip(batch, embeddings):
                    doc_with_embedding = {**doc, "embeddings": embedding}
                    docs_to_insert.append(doc_with_embedding)
                
                # Insert into MongoDB
                if docs_to_insert:
                    result = await self.collection.insert_many(docs_to_insert)
                    indexed_count += len(result.inserted_ids)
                
                logger.debug(
                    "Indexed batch",
                    batch_number=i // batch_size + 1,
                    batch_size=len(batch)
                )
            
            logger.info("Document indexing completed", total_indexed=indexed_count)
            return indexed_count
            
        except Exception as e:
            logger.error("Error indexing documents", error=str(e))
            raise
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of Atlas and Voyage connections."""
        try:
            # Test MongoDB connection
            await self.client.admin.command('ping')
            mongo_healthy = True
        except Exception as e:
            logger.warning("MongoDB health check failed", error=str(e))
            mongo_healthy = False
        
        # Test Voyage connection
        voyage_healthy = await self.voyage.health_check()
        
        return {
            "mongodb": "healthy" if mongo_healthy else "unhealthy",
            "voyage": "healthy" if voyage_healthy else "unhealthy",
            "overall": "healthy" if (mongo_healthy and voyage_healthy) else "unhealthy"
        }
    
    async def close(self):
        """Close connections."""
        await self.voyage.close()
        self.client.close()
