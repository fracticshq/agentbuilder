"""
Request models for the Agent Builder Platform API
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class PageContext(BaseModel):
    """Page context information."""
    url: str
    title: Optional[str] = None
    content: Optional[str] = None
    metadata: Dict[str, Any] = {}


class MessageRequest(BaseModel):
    """Request model for sending a message."""
    message: str = Field(..., min_length=1, max_length=10000)
    user_id: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None
    page_context: Optional[PageContext] = None
    filters: Optional[Dict[str, Any]] = None
    stream: bool = False


class IngestionRequest(BaseModel):
    """Request model for document ingestion."""
    text: str = Field(..., min_length=1)
    doc_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
    chunk_size: Optional[int] = Field(None, ge=100, le=5000)
    chunk_overlap: Optional[int] = Field(None, ge=0, le=500)
