"""
Brand Boost - Prioritize brand-specific content (manuals, FAQs, policies)
"""

from typing import List
import structlog

from ..types import DocumentChunk

logger = structlog.get_logger()


class BrandBoost:
    """Apply boosts to brand-specific content types."""
    
    # Content type boost multipliers
    BOOST_MULTIPLIERS = {
        "manual": 1.3,
        "faq": 1.25,
        "policy": 1.2,
        "product_spec": 1.15,
        "article": 1.0,
        "blog": 0.9
    }
    
    def __init__(self, brand_id: str):
        self.brand_id = brand_id
        logger.info("Brand boost initialized", brand_id=brand_id)
    
    def apply_boost(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        """
        Apply brand content type boosts.
        
        Args:
            chunks: List of chunks to boost
        
        Returns:
            Chunks with updated scores
        """
        boosted_count = 0
        
        for chunk in chunks:
            content_type = chunk.metadata.get("content_type", "article")
            boost_multiplier = self.BOOST_MULTIPLIERS.get(content_type, 1.0)
            
            if boost_multiplier != 1.0:
                original_score = chunk.score
                chunk.score *= boost_multiplier
                chunk.metadata["brand_boost"] = boost_multiplier
                chunk.metadata["original_score"] = original_score
                boosted_count += 1
        
        if boosted_count > 0:
            # Re-sort by updated scores
            chunks.sort(key=lambda x: x.score, reverse=True)
        
        logger.debug(
            "Brand boost applied",
            total_chunks=len(chunks),
            boosted_count=boosted_count
        )
        
        return chunks
