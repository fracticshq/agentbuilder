"""
Reciprocal Rank Fusion (RRF) for combining search results
"""

from typing import List, Dict, Any
from collections import defaultdict
import structlog

from ..types import DocumentChunk, SearchResult

logger = structlog.get_logger()


class RRFFusion:
    """
    Reciprocal Rank Fusion algorithm for combining multiple search results.
    
    RRF Score = sum(1 / (k + rank_i))
    where k is a constant (typically 60) and rank_i is the rank in list i
    """
    
    def __init__(self, k: int = 60):
        """
        Initialize RRF fusion.
        
        Args:
            k: RRF constant (default 60, recommended range 10-100)
        """
        self.k = k
        logger.info("RRF Fusion initialized", k=k)
    
    def fuse(
        self,
        search_results: List[SearchResult],
        top_k: int = 50
    ) -> List[DocumentChunk]:
        """
        Fuse multiple search results using RRF.
        
        Args:
            search_results: List of SearchResult objects to fuse
            top_k: Number of top results to return
        
        Returns:
            List of fused and ranked DocumentChunks
        """
        if not search_results:
            return []
        
        if len(search_results) == 1:
            return search_results[0].chunks[:top_k]
        
        # Calculate RRF scores
        chunk_scores = defaultdict(float)
        chunk_map = {}  # Store chunk objects by chunk_id
        
        for search_result in search_results:
            for rank, chunk in enumerate(search_result.chunks, start=1):
                chunk_id = chunk.chunk_id
                
                # RRF formula: 1 / (k + rank)
                rrf_score = 1.0 / (self.k + rank)
                chunk_scores[chunk_id] += rrf_score
                
                # Store chunk if not already stored
                if chunk_id not in chunk_map:
                    chunk_map[chunk_id] = chunk
        
        # Sort by RRF score
        sorted_chunk_ids = sorted(
            chunk_scores.keys(),
            key=lambda x: chunk_scores[x],
            reverse=True
        )
        
        # Create result chunks with updated scores
        fused_chunks = []
        for chunk_id in sorted_chunk_ids[:top_k]:
            chunk = chunk_map[chunk_id]
            # Update chunk with RRF score
            chunk.score = chunk_scores[chunk_id]
            chunk.metadata["rrf_score"] = chunk_scores[chunk_id]
            chunk.metadata["fusion_method"] = "rrf"
            fused_chunks.append(chunk)
        
        logger.info(
            "RRF fusion completed",
            input_results=len(search_results),
            unique_chunks=len(chunk_map),
            output_chunks=len(fused_chunks)
        )
        
        return fused_chunks
    
    def get_rank_info(
        self,
        chunk_id: str,
        search_results: List[SearchResult]
    ) -> Dict[str, Any]:
        """
        Get ranking information for a specific chunk across all results.
        
        Args:
            chunk_id: ID of the chunk to analyze
            search_results: List of search results
        
        Returns:
            Dictionary with ranking information
        """
        ranks = []
        
        for i, search_result in enumerate(search_results):
            for rank, chunk in enumerate(search_result.chunks, start=1):
                if chunk.chunk_id == chunk_id:
                    ranks.append({
                        "search_type": search_result.search_type,
                        "rank": rank,
                        "score": chunk.score,
                        "rrf_contribution": 1.0 / (self.k + rank)
                    })
                    break
        
        return {
            "chunk_id": chunk_id,
            "found_in": len(ranks),
            "ranks": ranks,
            "total_rrf_score": sum(r["rrf_contribution"] for r in ranks)
        }
