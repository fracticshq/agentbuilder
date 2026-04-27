"""
Type definitions for retrieval package
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class DocumentChunk(BaseModel):
    """A chunk of a document with metadata."""
    
    chunk_id: str
    doc_id: str
    content: str
    title: Optional[str] = None
    url: Optional[str] = None
    section: Optional[str] = None
    score: float = 0.0
    
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embeddings: Optional[List[float]] = None
    
    # Phase 2: Structured data for product cards
    content_type: Optional[str] = None  # "product" | "dealer" | "faq" | "office" | "category" | "guide"
    product_data: Optional[Dict[str, Any]] = None  # SKU, name, price, category, etc.
    dealer_data: Optional[Dict[str, Any]] = None   # dealer_id, name, city, phone, etc.
    
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SearchResult(BaseModel):
    """Result from a search operation."""
    
    chunks: List[DocumentChunk]
    total_found: int
    query: str
    search_type: str  # 'vector', 'bm25', 'hybrid'
    
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievalContext(BaseModel):
    """Complete retrieval context for LLM."""
    
    chunks: List[DocumentChunk]
    confidence: float
    sources: List[str]
    
    boost_info: Dict[str, Any] = Field(default_factory=dict)
    retrieval_metadata: Dict[str, Any] = Field(default_factory=dict)
    
    query: str
    filters_applied: Optional[Dict[str, Any]] = None
    
    # Phase 2: Query intent and content type awareness
    query_intent: Optional[str] = None  # "product_search" | "dealer_search" | "faq" | "general"
    content_types_found: Optional[List[str]] = None  # Content types in results


class PageContext(BaseModel):
    """Context from the page where chat widget is embedded."""
    
    url: str
    path: Optional[str] = None
    title: Optional[str] = None
    lang: Optional[str] = None
    
    meta: Dict[str, str] = Field(default_factory=dict)
    schema_org: Optional[Dict[str, Any]] = None
    nearby_text: Optional[str] = None
    
    sku: Optional[str] = None
    category: Optional[str] = None


class RetrievalConfig(BaseModel):
    """Configuration for retrieval pipeline."""
    
    # Vector search
    vector_enabled: bool = True
    vector_top_k: int = 50
    similarity_threshold: float = 0.7
    
    # BM25 search
    bm25_enabled: bool = True
    bm25_top_k: int = 50
    
    # Fusion
    rrf_k: int = 60  # RRF constant
    
    # Reranking
    rerank_enabled: bool = True
    rerank_top_k: int = 12
    
    # Boosts
    brand_boost_enabled: bool = True
    page_boost_enabled: bool = True
    
    # Deduplication
    dedup_enabled: bool = True
    dedup_threshold: float = 0.95  # MinHash similarity threshold
