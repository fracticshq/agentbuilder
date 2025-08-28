"""
Message Service - Core business logic for processing messages
"""

import asyncio
import uuid
from typing import AsyncGenerator
import structlog

from commons.types.requests import MessageRequest
from commons.types.responses import MessageResponse, StreamingMessageResponse
from memory.managers.memory_manager import MemoryManager
from retrieval.pipeline import RetrievalPipeline
from llm.factory import LLMFactory, create_provider_from_env
from ..config import Settings

logger = structlog.get_logger()


class MessageService:
    """Service for processing chat messages."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.memory_manager = MemoryManager()
        self.retrieval_pipeline = RetrievalPipeline()
        self.llm_provider = create_provider_from_env(
            provider_name=settings.MODEL_PROVIDER,
            api_key=settings.API_KEY,
            model=settings.MODEL_NAME
        )
    
    async def process_message(self, request: MessageRequest) -> MessageResponse:
        """Process a single message and return complete response."""
        try:
            # Generate conversation ID if not provided
            conversation_id = request.conversation_id or str(uuid.uuid4())
            
            # Retrieve relevant context
            context = await self._retrieve_context(request)
            
            # Get memory context
            memory_context = await self.memory_manager.get_context(
                user_id=request.user_id,
                conversation_id=conversation_id
            )
            
            # Generate response using LLM
            response_text = await self._generate_response(
                message=request.message,
                context=context,
                memory_context=memory_context
            )
            
            # Update memory with conversation
            await self.memory_manager.update_memory(
                user_id=request.user_id,
                conversation_id=conversation_id,
                user_message=request.message,
                assistant_response=response_text
            )
            
            # Extract citations from context
            citations = self._extract_citations(context)
            
            return MessageResponse(
                message=response_text,
                conversation_id=conversation_id,
                citations=citations,
                context_used=len(context.get("chunks", [])),
                confidence_score=context.get("confidence", 0.0)
            )
            
        except Exception as e:
            logger.error("Error processing message", error=str(e))
            raise
    
    async def stream_message(self, request: MessageRequest) -> AsyncGenerator[StreamingMessageResponse, None]:
        """Process a message and stream the response."""
        try:
            # Generate conversation ID if not provided
            conversation_id = request.conversation_id or str(uuid.uuid4())
            
            # Retrieve relevant context
            yield StreamingMessageResponse(
                type="status",
                content="Retrieving context...",
                conversation_id=conversation_id
            )
            
            context = await self._retrieve_context(request)
            
            # Get memory context
            yield StreamingMessageResponse(
                type="status",
                content="Loading memory...",
                conversation_id=conversation_id
            )
            
            memory_context = await self.memory_manager.get_context(
                user_id=request.user_id,
                conversation_id=conversation_id
            )
            
            # Stream response generation
            yield StreamingMessageResponse(
                type="status",
                content="Generating response...",
                conversation_id=conversation_id
            )
            
            response_chunks = []
            async for chunk in self._stream_response(
                message=request.message,
                context=context,
                memory_context=memory_context
            ):
                response_chunks.append(chunk)
                yield StreamingMessageResponse(
                    type="content",
                    content=chunk,
                    conversation_id=conversation_id
                )
            
            # Combine full response
            full_response = "".join(response_chunks)
            
            # Update memory
            await self.memory_manager.update_memory(
                user_id=request.user_id,
                conversation_id=conversation_id,
                user_message=request.message,
                assistant_response=full_response
            )
            
            # Send final metadata
            citations = self._extract_citations(context)
            yield StreamingMessageResponse(
                type="metadata",
                content="",
                conversation_id=conversation_id,
                citations=citations,
                context_used=len(context.get("chunks", [])),
                confidence_score=context.get("confidence", 0.0)
            )
            
        except Exception as e:
            logger.error("Error streaming message", error=str(e))
            yield StreamingMessageResponse(
                type="error",
                content=f"Error: {str(e)}",
                conversation_id=conversation_id or str(uuid.uuid4())
            )
    
    async def _retrieve_context(self, request: MessageRequest) -> dict:
        """Retrieve relevant context for the message."""
        try:
            # Use retrieval pipeline to get relevant chunks
            context = await self.retrieval_pipeline.retrieve(
                query=request.message,
                page_context=request.page_context,
                user_id=request.user_id,
                filters=request.filters or {}
            )
            return context
        except Exception as e:
            logger.error("Error retrieving context", error=str(e))
            return {"chunks": [], "confidence": 0.0}
    
    async def _generate_response(self, message: str, context: dict, memory_context: dict) -> str:
        """Generate response using LLM."""
        try:
            # Build prompt with context and memory
            prompt = self._build_prompt(message, context, memory_context)
            
            # Generate response
            response = await self.llm_provider.generate(prompt)
            return response.content
            
        except Exception as e:
            logger.error("Error generating response", error=str(e))
            return "I apologize, but I encountered an error while processing your request."
    
    async def _stream_response(self, message: str, context: dict, memory_context: dict) -> AsyncGenerator[str, None]:
        """Stream response generation using LLM."""
        try:
            # Build prompt with context and memory
            prompt = self._build_prompt(message, context, memory_context)
            
            # Stream response
            async for chunk in self.llm_provider.stream(prompt):
                yield chunk.content
                
        except Exception as e:
            logger.error("Error streaming response", error=str(e))
            yield "I apologize, but I encountered an error while processing your request."
    
    def _build_prompt(self, message: str, context: dict, memory_context: dict) -> str:
        """Build prompt with context and memory."""
        prompt_parts = []
        
        # System instruction
        prompt_parts.append(
            "You are a helpful AI assistant. Use the provided context to answer questions accurately. "
            "If you cannot find relevant information in the context, say so clearly. "
            "Always cite your sources when possible."
        )
        
        # Add context chunks
        if context.get("chunks"):
            prompt_parts.append("\nRelevant Context:")
            for i, chunk in enumerate(context["chunks"]):
                prompt_parts.append(f"[{i+1}] {chunk.get('content', '')}")
        
        # Add memory context
        if memory_context.get("recent_messages"):
            prompt_parts.append("\nRecent Conversation:")
            for msg in memory_context["recent_messages"][-3:]:  # Last 3 messages
                prompt_parts.append(f"User: {msg.get('user_message', '')}")
                prompt_parts.append(f"Assistant: {msg.get('assistant_response', '')}")
        
        # Add current message
        prompt_parts.append(f"\nUser: {message}")
        prompt_parts.append("Assistant:")
        
        return "\n".join(prompt_parts)
    
    def _extract_citations(self, context: dict) -> list:
        """Extract citations from context."""
        citations = []
        for chunk in context.get("chunks", []):
            if chunk.get("doc_id") and chunk.get("title"):
                citations.append({
                    "doc_id": chunk["doc_id"],
                    "title": chunk["title"],
                    "url": chunk.get("url"),
                    "confidence": chunk.get("score", 0.0)
                })
        return citations
