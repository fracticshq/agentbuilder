"""
Voyage AI Embeddings Client
"""

import os
from typing import List, Optional
import httpx
import structlog

logger = structlog.get_logger()


class VoyageClient:
    """Client for Voyage AI embeddings API."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "voyage-3-large",
        base_url: str = "https://api.voyageai.com/v1"
    ):
        self.api_key = api_key or os.getenv("VOYAGE_API_KEY")
        if not self.api_key:
            raise ValueError("Voyage API key not found. Set VOYAGE_API_KEY environment variable.")
        
        self.model = model
        self.base_url = base_url
        self.auth_failed = False
        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )
        logger.info("Voyage client initialized", model=model)
    
    async def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a search query."""
        if self.auth_failed:
            raise RuntimeError("Voyage API disabled after authentication failure")
        embeddings = await self._embed([query], input_type="query")
        return embeddings[0]  # Get first (and only) embedding from the list
    
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple documents."""
        if self.auth_failed:
            raise RuntimeError("Voyage API disabled after authentication failure")
        embeddings = await self._embed(texts, input_type="document")
        return embeddings  # Already a list of embeddings
    
    async def _embed(
        self,
        texts: List[str],
        input_type: str = "document"
    ) -> List[List[float]]:
        """
        Generate embeddings using Voyage API.
        
        Args:
            texts: List of texts to embed
            input_type: 'query' or 'document' for optimized embeddings
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/embeddings",
                json={
                    "input": texts,
                    "model": self.model,
                    "input_type": input_type
                }
            )
            response.raise_for_status()
            
            data = response.json()
            embeddings = [item["embedding"] for item in data["data"]]
            
            logger.debug(
                "Generated embeddings",
                count=len(embeddings),
                model=self.model,
                input_type=input_type,
                first_embedding_type=type(embeddings[0]).__name__ if embeddings else None,
                first_embedding_length=len(embeddings[0]) if embeddings and isinstance(embeddings[0], list) else None
            )
            
            # Always return list of embeddings (list of lists)
            return embeddings
            
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            if status_code in {401, 403}:
                self.auth_failed = True
                logger.warning("voyage_api_auth_failed_disabling_client", status=status_code)
            else:
                logger.error("Voyage API error", status=status_code, detail=e.response.text)
            raise
        except Exception as e:
            logger.error("Error generating embeddings", error=str(e))
            raise
    
    async def health_check(self) -> bool:
        """Check if Voyage API is accessible."""
        try:
            # Simple test embedding
            await self.embed_query("test")
            return True
        except Exception as e:
            logger.warning("Voyage health check failed", error=str(e))
            return False
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
