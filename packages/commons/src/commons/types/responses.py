"""
Response models for the Agent Builder Platform API
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class Citation(BaseModel):
    """Citation information."""
    doc_id: str
    title: Optional[str] = None
    url: Optional[str] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    snippet: Optional[str] = None


class MessageResponse(BaseModel):
    """Response model for message processing."""
    message: str
    conversation_id: str
    citations: List[Citation] = []
    context_used: int = 0
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    processing_time_ms: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class StreamingMessageResponse(BaseModel):
    """Response model for streaming messages."""
    type: str = Field(..., description="Type of chunk: 'status', 'content', 'metadata', 'error'")
    content: str = ""
    conversation_id: str
    citations: List[Citation] = []
    context_used: Optional[int] = None
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    products: Optional[List[Dict[str, Any]]] = None  # Phase 5: Product cards
    dealers: Optional[List[Dict[str, Any]]] = None   # Phase 5: Dealer cards
    metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class IngestionResponse(BaseModel):
    """Response model for ingestion operations."""
    success: bool
    chunk_id: Optional[str] = None
    message: str
    chunks_created: Optional[int] = None
    processing_time_ms: Optional[int] = None


class IngestionStatus(BaseModel):
    """Status model for ingestion jobs."""
    job_id: str
    status: str = Field(..., description="Status: 'pending', 'processing', 'completed', 'error', 'cancelled'")
    files_count: int = 0
    processed_count: int = 0
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
