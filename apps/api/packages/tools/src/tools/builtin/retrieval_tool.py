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
        """Extract product data from retrieval chunks.
        
        DocumentChunk has product_data as a top-level attribute, not inside metadata.
        """
        products = []
        seen_ids = set()
        
        for chunk in chunks:
            # product_data is a top-level attribute on DocumentChunk
            product_data = getattr(chunk, 'product_data', None)
            
            if product_data and isinstance(product_data, dict):
                # Use SKU as the unique ID for deduplication
                product_id = product_data.get('sku') or product_data.get('product_id') or product_data.get('id')
                
                if product_id and product_id not in seen_ids:
                    seen_ids.add(product_id)
                    # Start with all product data
                    product_item = product_data.copy()
                    
                    # Update with normalized keys expected by frontend
                    product_item.update({
                        "id": product_id,
                        "sku": product_id,  # Ensure SKU is explicit
                        "name": product_data.get('name'),
                        "description": product_data.get('category', ''),
                        "price": product_data.get('price'),
                        "image": product_data.get('image_url'),
                        "url": product_data.get('product_url')
                    })
                    products.append(product_item)
        
        return products
    
    def _extract_dealers(self, chunks: List[Any]) -> List[Dict[str, Any]]:
        """Extract dealer data from retrieval chunks.
        
        DocumentChunk has dealer_data as a top-level attribute, not inside metadata.
        """
        dealers = []
        seen_ids = set()
        
        for chunk in chunks:
            # dealer_data is a top-level attribute on DocumentChunk
            dealer_data = getattr(chunk, 'dealer_data', None)
            
            if dealer_data and isinstance(dealer_data, dict):
                dealer_id = dealer_data.get('dealer_id') or dealer_data.get('id')
                
                if dealer_id and dealer_id not in seen_ids:
                    seen_ids.add(dealer_id)
                    
                    # Start with all dealer data
                    dealer_item = dealer_data.copy()
                    
                    # Update with normalized keys
                    dealer_item.update({
                        "id": dealer_id,
                        "name": dealer_data.get('name'),
                        "address": dealer_data.get('address'),
                        "phone": dealer_data.get('phone'),
                        "location": dealer_data.get('city')
                    })
                    dealers.append(dealer_item)
        
        return dealers
