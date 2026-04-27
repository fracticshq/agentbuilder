"""
Cross-Encoder Reranker for improving retrieval quality
"""

import os
from typing import List, Optional
import httpx
import structlog

from ..types import DocumentChunk

logger = structlog.get_logger()


class CrossEncoderReranker:
    """
    Cross-encoder reranker using Voyage Rerank API or similar.
    Falls back to simple scoring if API unavailable.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "rerank-1",
        use_api: bool = True
    ):
        self.api_key = api_key or os.getenv("VOYAGE_API_KEY")
        self.model = model
        self.use_api = use_api and bool(self.api_key)
        
        if self.use_api:
            self.client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
            logger.info("Reranker initialized with API", model=model)
        else:
            self.client = None
            logger.info("Reranker initialized in fallback mode")
    
    async def rerank(
        self,
        query: str,
        chunks: List[DocumentChunk],
        top_k: int = 12
    ) -> List[DocumentChunk]:
        """
        Rerank chunks using cross-encoder model.
        
        Args:
            query: Search query
            chunks: List of chunks to rerank
            top_k: Number of top results to return
        
        Returns:
            Reranked list of chunks
        """
        if not chunks:
            return []
        
        if len(chunks) <= top_k:
            return chunks
        
        try:
            if self.use_api and self.client:
                return await self._rerank_with_api(query, chunks, top_k)
            else:
                return await self._rerank_fallback(query, chunks, top_k)
        
        except Exception as e:
            logger.warning("Reranking failed, using fallback", error=str(e))
            return await self._rerank_fallback(query, chunks, top_k)
    
    async def _rerank_with_api(
        self,
        query: str,
        chunks: List[DocumentChunk],
        top_k: int
    ) -> List[DocumentChunk]:
        """Rerank using Voyage Rerank API."""
        try:
            # Prepare documents for reranking
            documents = [chunk.content for chunk in chunks]
            
            # Call rerank API
            response = await self.client.post(
                "https://api.voyageai.com/v1/rerank",
                json={
                    "query": query,
                    "documents": documents,
                    "model": self.model,
                    "top_k": top_k
                }
            )
            response.raise_for_status()
            
            data = response.json()
            results = data.get("data", [])
            
            # Sort chunks based on reranked scores
            reranked_chunks = []
            for result in results:
                index = result["index"]
                score = result["relevance_score"]
                
                chunk = chunks[index]
                chunk.score = score
                chunk.metadata["rerank_score"] = score
                chunk.metadata["reranked"] = True
                reranked_chunks.append(chunk)
            
            logger.info(
                "API reranking completed",
                input_chunks=len(chunks),
                output_chunks=len(reranked_chunks)
            )
            
            return reranked_chunks
            
        except Exception as e:
            logger.error("API reranking error", error=str(e))
            raise
    
    async def _rerank_fallback(
        self,
        query: str,
        chunks: List[DocumentChunk],
        top_k: int
    ) -> List[DocumentChunk]:
        """
        Fallback reranking using simple heuristics.
        Uses combination of original score and query term overlap.
        """
        query_terms = set(query.lower().split())
        
        for chunk in chunks:
            # Calculate term overlap
            content_terms = set(chunk.content.lower().split())
            overlap = len(query_terms & content_terms) / max(len(query_terms), 1)
            
            # Combine with original score (weighted average)
            original_score = chunk.score
            combined_score = (0.7 * original_score) + (0.3 * overlap)
            
            chunk.score = combined_score
            chunk.metadata["rerank_score"] = combined_score
            chunk.metadata["reranked"] = True
            chunk.metadata["rerank_method"] = "fallback"
            chunk.metadata["term_overlap"] = overlap
        
        # Sort by combined score
        reranked = sorted(chunks, key=lambda x: x.score, reverse=True)[:top_k]
        
        logger.info(
            "Fallback reranking completed",
            input_chunks=len(chunks),
            output_chunks=len(reranked)
        )
        
        return reranked
    
    async def health_check(self) -> bool:
        """Check if reranker is operational."""
        if not self.use_api:
            return True  # Fallback mode always works
        
        try:
            # Simple test rerank
            test_docs = ["This is a test document"]
            response = await self.client.post(
                "https://api.voyageai.com/v1/rerank",
                json={
                    "query": "test",
                    "documents": test_docs,
                    "model": self.model,
                    "top_k": 1
                }
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Reranker health check failed", error=str(e))
            return False
    
    async def close(self):
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()
