"""
Retrieval Tool - Wraps the RetrievalPipeline for agent use.
"""

from typing import Optional, Dict, Any, List
from tools.types import BaseTool, ToolResult
from retrieval.pipeline import RetrievalPipeline
from retrieval.types import RetrievalContext

class RetrievalTool(BaseTool):
    """
    Tool that grants agents access to the RAG retrieval pipeline.
    """
    
    name = "knowledge_search"
    description = "Searches the internal knowledge base for relevant information about products, support, policies, or other facts."
    
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to find information. Be specific."
            },
            "filters": {
                "type": "object",
                "description": "Optional filters like {'content_type': 'product'}"
            }
        },
        "required": ["query"]
    }
    
    def __init__(self, retrieval_pipeline: RetrievalPipeline):
        self.pipeline = retrieval_pipeline
        
    async def run(self, query: str, filters: Optional[Dict[str, Any]] = None, **kwargs) -> ToolResult:
        """Run the retrieval pipeline."""
        try:
            context: RetrievalContext = await self.pipeline.retrieve(
                query=query,
                filters=filters or {},
                max_chunks=5  # Tool usage usually needs concise top results
            )
            
            # Format the output for the agent
            if not context.chunks:
                return ToolResult(
                    success=True, 
                    data="No relevant information found in the knowledge base.",
                    metadata={"confidence": 0.0}
                )
                
            # Create a string representation of the chunks
            results_text = "Found the following information:\n\n"
            for i, chunk in enumerate(context.chunks, 1):
                content = getattr(chunk, 'text', '') or getattr(chunk, 'content', '')
                source = chunk.doc_id
                results_text += f"[{i}] source_id: {source}\n{content[:500]}...\n\n"
                
            return ToolResult(
                success=True,
                data=results_text,
                metadata={
                    "confidence": context.confidence,
                    "sources": context.sources,
                    "chunks_count": len(context.chunks)
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                data=None,
                error=str(e)
            )
