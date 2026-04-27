"""
Retrieval Package - Hybrid search with vector, BM25, fusion, and reranking
"""

from .pipeline import RetrievalPipeline
from .types import (
    DocumentChunk,
    SearchResult,
    RetrievalContext,
    PageContext,
    RetrievalConfig
)
from .vector.atlas_search import AtlasVectorSearch
from .vector.voyage_client import VoyageClient
from .bm25.text_search import BM25Search
from .fusion.rrf import RRFFusion
from .fusion.reranker import CrossEncoderReranker
from .boosts.brand_boost import BrandBoost
from .boosts.page_boost import PageBoost

__all__ = [
    # Main pipeline
    "RetrievalPipeline",
    
    # Types
    "DocumentChunk",
    "SearchResult",
    "RetrievalContext",
    "PageContext",
    "RetrievalConfig",
    
    # Search components
    "AtlasVectorSearch",
    "VoyageClient",
    "BM25Search",
    
    # Fusion and reranking
    "RRFFusion",
    "CrossEncoderReranker",
    
    # Boosts
    "BrandBoost",
    "PageBoost",
]

__version__ = "0.1.0"
