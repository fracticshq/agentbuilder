"""
BM25 Text Search implementation
"""

import os
from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorClient
import structlog

from ..types import DocumentChunk, SearchResult

logger = structlog.get_logger()


class BM25Search:
    """BM25 text search using MongoDB text indexes."""
    
    def __init__(
        self,
        collection_name: str = "knowledge_base",
        text_index_name: str = "text_index",
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
        self.text_index_name = text_index_name
        self.brand_id = brand_id
        
        logger.info(
            "BM25 Search initialized",
            brand_id=brand_id,
            database=db_name,
            collection=collection_name
        )
    
    async def search(
        self,
        query: str,
        top_k: int = 50,
        filters: Optional[Dict[str, Any]] = None
    ) -> SearchResult:
        """
        Perform BM25 text search.
        
        Args:
            query: Search query text
            top_k: Number of results to return
            filters: Optional metadata filters
        
        Returns:
            SearchResult with matched chunks
        """
        try:
            import time
            start_time = time.time()
            
            # Build search query
            search_query = {"$text": {"$search": query}}
            
            # Add filters if provided
            if filters:
                search_query.update(filters)
            
            # Project with text score
            projection = {
                "chunk_id": 1,
                "doc_id": 1,
                "content": 1,
                "title": 1,
                "url": 1,
                "section": 1,
                "metadata": 1,
                "created_at": 1,
                "content_type": 1,  # Added for Phase 2
                "product_data": 1,  # Added for Phase 2
                "dealer_data": 1,   # Added for Phase 2
                "score": {"$meta": "textScore"}
            }
            
            # Execute search
            cursor = self.collection.find(
                search_query,
                projection
            ).sort([("score", {"$meta": "textScore"})]).limit(top_k)
            
            results = await cursor.to_list(length=top_k)
            
            # Convert to chunks
            chunks = [self._result_to_chunk(result) for result in results]
            
            execution_time = (time.time() - start_time) * 1000
            
            logger.info(
                "BM25 search completed",
                query_length=len(query),
                results_found=len(chunks),
                execution_time_ms=execution_time
            )
            
            return SearchResult(
                chunks=chunks,
                total_found=len(chunks),
                query=query,
                search_type="bm25",
                execution_time_ms=execution_time,
                metadata={
                    "top_k": top_k,
                    "filters": filters or {}
                }
            )
            
        except Exception as e:
            logger.error("BM25 search error", error=str(e), query=query[:100])
            raise
    
    def _result_to_chunk(self, result: Dict[str, Any]) -> DocumentChunk:
        """Convert MongoDB result to DocumentChunk."""
        return DocumentChunk(
            chunk_id=result.get("chunk_id", str(result.get("_id"))),
            doc_id=result.get("doc_id", "unknown"),
            content=result.get("content", ""),
            title=result.get("title"),
            url=result.get("url"),
            section=result.get("section"),
            score=result.get("score", 0.0),
            metadata=result.get("metadata", {}),
            created_at=result.get("created_at"),
            # Phase 2: Add structured data fields
            content_type=result.get("content_type"),
            product_data=result.get("product_data"),
            dealer_data=result.get("dealer_data")
        )
    
    async def create_text_index(self):
        """Create text index on content and title fields."""
        try:
            await self.collection.create_index(
                [
                    ("content", "text"),
                    ("title", "text"),
                    ("section", "text")
                ],
                name=self.text_index_name,
                weights={
                    "title": 10,
                    "section": 5,
                    "content": 1
                }
            )
            logger.info("Text index created", index_name=self.text_index_name)
        except Exception as e:
            logger.warning("Text index creation failed", error=str(e))
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of MongoDB connection."""
        try:
            await self.client.admin.command('ping')
            return {"status": "healthy"}
        except Exception as e:
            logger.warning("MongoDB health check failed", error=str(e))
            return {"status": "unhealthy", "error": str(e)}
    
    async def close(self):
        """Close MongoDB connection."""
        self.client.close()
