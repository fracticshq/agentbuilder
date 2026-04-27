"""
Page Boost - Boost content relevant to current page context
"""

from typing import List, Optional
import structlog

from ..types import DocumentChunk, PageContext

logger = structlog.get_logger()


class PageBoost:
    """Apply boosts based on page context (URL, SKU, category)."""
    
    def __init__(self):
        logger.info("Page boost initialized")
    
    def apply_boost(
        self,
        chunks: List[DocumentChunk],
        page_context: Optional[PageContext] = None
    ) -> List[DocumentChunk]:
        """
        Apply page context boosts.
        
        Args:
            chunks: List of chunks to boost
            page_context: Current page context
        
        Returns:
            Chunks with updated scores
        """
        if not page_context:
            return chunks
        
        boosted_count = 0
        
        for chunk in chunks:
            boost_multiplier = 1.0
            boost_reasons = []
            
            # SKU match boost - check if page_context has sku attribute
            if hasattr(page_context, 'sku') and page_context.sku and chunk.metadata.get("sku") == page_context.sku:
                boost_multiplier *= 1.5
                boost_reasons.append("sku_match")
            
            # Category match boost - check if page_context has category attribute
            if hasattr(page_context, 'category') and page_context.category and chunk.metadata.get("category") == page_context.category:
                boost_multiplier *= 1.3
                boost_reasons.append("category_match")
            
            # URL path similarity boost - check if page_context has path attribute
            page_path = getattr(page_context, 'path', None)
            if page_path and chunk.url:
                if page_path in chunk.url or chunk.url in page_path:
                    boost_multiplier *= 1.2
                    boost_reasons.append("url_similarity")
            
            # Page type boost (e.g., FAQ page prioritizes FAQ content)
            page_meta = getattr(page_context, 'meta', {})
            if page_meta and page_meta.get("page_type"):
                page_type = page_meta["page_type"]
                content_type = chunk.metadata.get("content_type")
                if page_type == content_type:
                    boost_multiplier *= 1.25
                    boost_reasons.append("page_type_match")
            
            # Apply boost if any match found
            if boost_multiplier > 1.0:
                original_score = chunk.score
                chunk.score *= boost_multiplier
                chunk.metadata["page_boost"] = boost_multiplier
                chunk.metadata["page_boost_reasons"] = boost_reasons
                chunk.metadata["original_score"] = original_score
                boosted_count += 1
        
        if boosted_count > 0:
            # Re-sort by updated scores
            chunks.sort(key=lambda x: x.score, reverse=True)
        
        logger.debug(
            "Page boost applied",
            total_chunks=len(chunks),
            boosted_count=boosted_count,
            page_url=page_context.url if page_context else None
        )
        
        return chunks
