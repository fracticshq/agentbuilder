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
                    metadata={
                        "confidence": 0.0,
                        "products": [],
                        "dealers": []
                    }
                )
            
            # Extract structured data from chunks
            products = self._extract_products(context.chunks)
            dealers = self._extract_dealers(context.chunks)
                
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
                    "chunks_count": len(context.chunks),
                    "products": products,
                    "dealers": dealers
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                data=None,
                error=str(e),
                metadata={
                    "products": [],
                    "dealers": []
                }
            )
    
    def _extract_products(self, chunks: List[Any]) -> List[Dict[str, Any]]:
        """Extract product data from retrieval chunks."""
        products = []
        seen_ids = set()
        
        for chunk in chunks:
            metadata = getattr(chunk, 'metadata', {})
            if 'product_data' in metadata:
                product = metadata['product_data']
                product_id = product.get('id') or product.get('product_id')
                
                if product_id and product_id not in seen_ids:
                    seen_ids.add(product_id)
                    products.append({
                        "id": product_id,
                        "name": product.get('name'),
                        "description": product.get('description'),
                        "price": product.get('price'),
                        "image": product.get('image_url'),
                        "url": product.get('url')
                    })
        
        return products
    
    def _extract_dealers(self, chunks: List[Any]) -> List[Dict[str, Any]]:
        """Extract dealer data from retrieval chunks."""
        dealers = []
        seen_ids = set()
        
        for chunk in chunks:
            metadata = getattr(chunk, 'metadata', {})
            if 'dealer_data' in metadata:
                dealer = metadata['dealer_data']
                dealer_id = dealer.get('id') or dealer.get('dealer_id')
                
                if dealer_id and dealer_id not in seen_ids:
                    seen_ids.add(dealer_id)
                    dealers.append({
                        "id": dealer_id,
                        "name": dealer.get('name'),
                        "address": dealer.get('address'),
                        "phone": dealer.get('phone'),
                        "location": dealer.get('location')
                    })
        
        return dealers
