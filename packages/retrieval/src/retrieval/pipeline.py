"""
Retrieval Pipeline - Orchestrates hybrid search and context building
"""

from typing import Dict, Any, List, Optional
import asyncio
import structlog

from .vector.atlas_search import AtlasVectorSearch
from .bm25.text_search import BM25Search
from .fusion.rrf import RRFFusion
from .fusion.reranker import CrossEncoderReranker
from .boosts.brand_boost import BrandBoost
from .boosts.page_boost import PageBoost
from .types import DocumentChunk, PageContext, RetrievalContext, RetrievalConfig

logger = structlog.get_logger()


class RetrievalPipeline:
    """
    Main retrieval pipeline that orchestrates:
    - Vector search (embeddings)
    - BM25 text search
    - Reciprocal Rank Fusion (RRF)
    - Cross-encoder reranking
    - Brand/page boosts
    - Deduplication
    """
    
    def __init__(
        self,
        config: Optional[RetrievalConfig] = None,
        brand_id: Optional[str] = None
    ):
        self.config = config or RetrievalConfig()
        self.brand_id = brand_id
        
        # Initialize search components
        try:
            self.vector_search = AtlasVectorSearch() if self.config.vector_enabled else None
        except Exception as e:
            logger.warning("Vector search initialization failed", error=str(e))
            self.vector_search = None
        
        try:
            self.bm25_search = BM25Search() if self.config.bm25_enabled else None
        except Exception as e:
            logger.warning("BM25 search initialization failed", error=str(e))
            self.bm25_search = None
        
        # Initialize fusion and reranking
        self.rrf = RRFFusion(k=self.config.rrf_k)
        self.reranker = CrossEncoderReranker() if self.config.rerank_enabled else None
        
        # Initialize boosts
        self.brand_boost = BrandBoost(brand_id) if brand_id and self.config.brand_boost_enabled else None
        self.page_boost = PageBoost() if self.config.page_boost_enabled else None
        
        logger.info("Retrieval pipeline initialized", config=self.config.dict() if hasattr(self.config, 'dict') else str(self.config))

    
    async def retrieve(
        self, 
        query: str, 
        page_context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        max_chunks: int = 12
    ) -> RetrievalContext:
        """
        Main retrieval method that returns relevant context chunks.
        
        Args:
            query: Search query text
            page_context: Optional page context for boosting
            user_id: Optional user ID for personalization
            filters: Optional metadata filters
            max_chunks: Maximum number of chunks to return (default 12)
        
        Returns:
            RetrievalContext with matched chunks and metadata
        """
        try:
            logger.info("Starting retrieval", query=query[:100], user_id=user_id)
            import time
            start_time = time.time()
            
            # Step 1: Perform parallel searches
            search_results = []
            
            # Vector search
            if self.vector_search and self.config.vector_enabled:
                try:
                    vector_result = await self.vector_search.search(
                        query=query,
                        top_k=self.config.vector_top_k,
                        filters=filters,
                        similarity_threshold=self.config.similarity_threshold
                    )
                    search_results.append(vector_result)
                    logger.debug("Vector search completed", chunks=len(vector_result.chunks))
                except Exception as e:
                    logger.warning("Vector search failed", error=str(e))
            
            # BM25 search
            if self.bm25_search and self.config.bm25_enabled:
                try:
                    bm25_result = await self.bm25_search.search(
                        query=query,
                        top_k=self.config.bm25_top_k,
                        filters=filters
                    )
                    search_results.append(bm25_result)
                    logger.debug("BM25 search completed", chunks=len(bm25_result.chunks))
                except Exception as e:
                    logger.warning("BM25 search failed", error=str(e))
            
            # If no searches succeeded, return empty result
            if not search_results:
                logger.warning("No search results available")
                return RetrievalContext(
                    chunks=[],
                    confidence=0.0,
                    sources=[],
                    query=query,
                    retrieval_metadata={"error": "No search backends available"}
                )
            
            # Step 2: Apply RRF fusion
            fused_chunks = self.rrf.fuse(search_results, top_k=self.config.vector_top_k)
            logger.debug("RRF fusion completed", chunks=len(fused_chunks))
            
            # Step 3: Apply cross-encoder reranking
            if self.reranker and self.config.rerank_enabled and len(fused_chunks) > max_chunks:
                try:
                    reranked_chunks = await self.reranker.rerank(
                        query=query,
                        chunks=fused_chunks,
                        top_k=max_chunks
                    )
                    logger.debug("Reranking completed", chunks=len(reranked_chunks))
                except Exception as e:
                    logger.warning("Reranking failed, using fused results", error=str(e))
                    reranked_chunks = fused_chunks[:max_chunks]
            else:
                reranked_chunks = fused_chunks[:max_chunks]
            
            # Step 4: Apply brand boost
            if self.brand_boost and self.config.brand_boost_enabled:
                reranked_chunks = self.brand_boost.apply_boost(reranked_chunks)
                logger.debug("Brand boost applied")
            
            # Step 5: Apply page context boost
            if self.page_boost and page_context and self.config.page_boost_enabled:
                # Convert dict to PageContext if needed
                page_ctx = PageContext(**page_context) if isinstance(page_context, dict) else page_context
                reranked_chunks = self.page_boost.apply_boost(reranked_chunks, page_ctx)
                logger.debug("Page boost applied")
            
            # Step 6: Deduplicate (simple version based on doc_id + section)
            if self.config.dedup_enabled:
                reranked_chunks = self._deduplicate(reranked_chunks)
                logger.debug("Deduplication completed", chunks=len(reranked_chunks))
            
            # Calculate overall confidence
            confidence = max([chunk.score for chunk in reranked_chunks], default=0.0)
            
            # Extract sources
            sources = list(set(chunk.doc_id for chunk in reranked_chunks))
            
            # Build retrieval context
            execution_time = (time.time() - start_time) * 1000
            
            result = RetrievalContext(
                chunks=reranked_chunks,
                confidence=confidence,
                sources=sources,
                query=query,
                filters_applied=filters,
                boost_info={
                    "page_context_applied": bool(page_context),
                    "brand_boost_applied": bool(self.brand_boost),
                    "filters_applied": bool(filters)
                },
                retrieval_metadata={
                    "search_methods": [r.search_type for r in search_results],
                    "total_candidates": sum(r.total_found for r in search_results),
                    "execution_time_ms": execution_time,
                    "reranked": bool(self.reranker and self.config.rerank_enabled),
                    "deduped": self.config.dedup_enabled
                }
            )
            
            logger.info("Retrieval completed", 
                       chunks_count=len(reranked_chunks), 
                       confidence=confidence,
                       execution_time_ms=execution_time)
            
            return result
            
        except Exception as e:
            logger.error("Error in retrieval pipeline", error=str(e), exc_info=True)
            return RetrievalContext(
                chunks=[],
                confidence=0.0,
                sources=[],
                query=query,
                retrieval_metadata={"error": str(e)}
            )
    
    def _deduplicate(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        """Simple deduplication based on doc_id + section."""
        seen = set()
        deduplicated = []
        
        for chunk in chunks:
            key = (chunk.doc_id, chunk.section or "")
            if key not in seen:
                seen.add(key)
                deduplicated.append(chunk)
        
        return deduplicated

    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of retrieval components."""
        health = {
            "vector_search": "disabled",
            "bm25_search": "disabled",
            "reranker": "disabled",
            "overall": "healthy"
        }
        
        # Check vector search
        if self.vector_search:
            try:
                vs_health = await self.vector_search.health_check()
                health["vector_search"] = vs_health.get("overall", "unknown")
            except Exception as e:
                health["vector_search"] = f"error: {str(e)}"
                health["overall"] = "degraded"
        
        # Check BM25 search
        if self.bm25_search:
            try:
                bm25_health = await self.bm25_search.health_check()
                health["bm25_search"] = bm25_health.get("status", "unknown")
            except Exception as e:
                health["bm25_search"] = f"error: {str(e)}"
                health["overall"] = "degraded"
        
        # Check reranker
        if self.reranker:
            try:
                reranker_healthy = await self.reranker.health_check()
                health["reranker"] = "healthy" if reranker_healthy else "unhealthy"
            except Exception as e:
                health["reranker"] = f"error: {str(e)}"
                # Reranker failure is not critical (has fallback)
        
        return health
    
    async def close(self):
        """Close all connections."""
        if self.vector_search:
            await self.vector_search.close()
        if self.bm25_search:
            await self.bm25_search.close()
        if self.reranker:
            await self.reranker.close()
