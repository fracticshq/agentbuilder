"""
Retrieval Pipeline - Orchestrates hybrid search and context building
"""

from typing import Dict, Any, List, Optional
import asyncio
import os
import re
import structlog

from .vector.atlas_search import AtlasVectorSearch
from .vector.qdrant_search import QdrantVectorSearch
from .vector.voyage_client import VoyageClient
from .bm25.text_search import BM25Search
from .fusion.rrf import RRFFusion
from .fusion.reranker import CrossEncoderReranker
from .boosts.brand_boost import BrandBoost
from .boosts.page_boost import PageBoost
from .types import DocumentChunk, PageContext, RetrievalContext, RetrievalConfig

logger = structlog.get_logger()


NEUTRAL_PRODUCT_KEYWORDS = {
    "price", "cost", "buy", "purchase", "product", "model", "under",
    "budget", "features", "specifications", "sku",
}

VERTICAL_PRODUCT_KEYWORDS = {
    "bathware": {
        "faucet", "shower", "sink", "tap", "basin", "toilet", "bath",
        "diverter", "mixer", "lever", "spout", "valve", "cock",
        "wash basin", "bathtub", "commode", "urinal", "bidet",
        "flush", "cistern", "seat cover", "accessories", "wall mounted",
        "floor mounted", "single bowl", "double bowl", "chrome", "brass",
        "stainless steel", "ceramic",
    },
}


class RetrievalPipeline:
    """
    Main retrieval pipeline that orchestrates:
    - Vector search (embeddings)
    - BM25 text search
    - Reciprocal Rank Fusion (RRF)
    - Cross-encoder reranking
    - Brand/page boosts
    - Deduplication
    """
    
    def __init__(
        self,
        config: Optional[RetrievalConfig] = None,
        brand_id: Optional[str] = None,
        voyage_api_key: Optional[str] = None,
        voyage_model: str = "voyage-3-large",
        voyage_base_url: str = "https://api.voyageai.com/v1",
        rerank_api_key: Optional[str] = None,
        rerank_model: str = "rerank-2.5",
        rerank_base_url: str = "https://api.voyageai.com/v1",
        verticals: Optional[List[str]] = None,
    ):
        self.config = config or RetrievalConfig()
        self.brand_id = brand_id
        self.verticals = {
            str(vertical).strip().lower()
            for vertical in (verticals or [])
            if str(vertical).strip().lower() in VERTICAL_PRODUCT_KEYWORDS
        }
        self.vector_backend = os.getenv("VECTOR_BACKEND", "atlas").lower()
        
        # Initialize search components with brand_id for database isolation
        try:
            voyage_client = (
                VoyageClient(api_key=voyage_api_key, model=voyage_model, base_url=voyage_base_url)
                if voyage_api_key
                else None
            )
            if not self.config.vector_enabled:
                self.vector_search = None
            elif self.vector_backend == "qdrant":
                self.vector_search = QdrantVectorSearch(brand_id=brand_id, voyage_client=voyage_client)
            else:
                self.vector_search = AtlasVectorSearch(brand_id=brand_id, voyage_client=voyage_client)
        except Exception as e:
            logger.warning("Vector search initialization failed", error=str(e))
            self.vector_search = None
        
        try:
            self.bm25_search = BM25Search(brand_id=brand_id) if self.config.bm25_enabled else None
        except Exception as e:
            logger.warning("BM25 search initialization failed", error=str(e))
            self.bm25_search = None
        
        # Initialize fusion and reranking
        self.rrf = RRFFusion(k=self.config.rrf_k)
        self.reranker = (
            CrossEncoderReranker(
                api_key=rerank_api_key or voyage_api_key,
                model=rerank_model,
                base_url=rerank_base_url,
            )
            if self.config.rerank_enabled
            else None
        )
        
        # Initialize boosts
        self.brand_boost = BrandBoost(brand_id) if brand_id and self.config.brand_boost_enabled else None
        self.page_boost = PageBoost() if self.config.page_boost_enabled else None
        
        logger.info(
            "Retrieval pipeline initialized",
            config=self.config.model_dump() if hasattr(self.config, "model_dump") else str(self.config),
            vector_backend=self.vector_backend,
        )

    
    async def retrieve(
        self, 
        query: str, 
        page_context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        max_chunks: int = 12,
        content_types: Optional[List[str]] = None  # Phase 2: Content-type filtering
    ) -> RetrievalContext:
        """
        Main retrieval method that returns relevant context chunks.
        
        Args:
            query: Search query text
            page_context: Optional page context for boosting
            user_id: Optional user ID for personalization
            filters: Optional metadata filters
            max_chunks: Maximum number of chunks to return (default 12)
            content_types: Optional list of content types to filter by (Phase 2)
        
        Returns:
            RetrievalContext with matched chunks and metadata
        """
        backend_status: Dict[str, Dict[str, str]] = {}
        search_results = []

        try:
            logger.info("Starting retrieval", query=query[:100], user_id=user_id)
            import time
            start_time = time.time()
            
            # Phase 2: Detect query intent
            query_intent = self._detect_query_intent(query, page_context)
            logger.debug("Query intent detected", intent=query_intent)
            
            # Phase 2: Auto-determine content types if not provided
            if content_types is None and query_intent != "general":
                content_types = self._intent_to_content_types(query_intent)
                logger.debug("Auto-determined content types", content_types=content_types)
            
            # Phase 2: Add content_type filter if specified
            if filters is None:
                filters = {}
            
            if content_types:
                filters["content_type"] = {"$in": content_types}
                logger.debug("Content type filter applied", content_types=content_types)
            
            # Step 1: Perform vector and BM25 searches concurrently.  Keep a
            # separate backend state so an outage cannot be mistaken for a
            # successful search that found no documents.
            search_tasks = []

            if self.config.vector_enabled:
                if self.vector_search:
                    search_tasks.append((
                        "vector",
                        self.vector_search.search(
                            query=query,
                            top_k=self.config.vector_top_k,
                            filters=filters,
                            similarity_threshold=self.config.similarity_threshold
                        )
                    ))
                else:
                    backend_status["vector"] = self._unavailable_backend_status()
            else:
                backend_status["vector"] = {"status": "disabled"}

            if self.config.bm25_enabled:
                if self.bm25_search:
                    search_tasks.append((
                        "bm25",
                        self.bm25_search.search(
                            query=query,
                            top_k=self.config.bm25_top_k,
                            filters=filters
                        )
                    ))
                else:
                    backend_status["bm25"] = self._unavailable_backend_status()
            else:
                backend_status["bm25"] = {"status": "disabled"}

            if search_tasks:
                results = await asyncio.gather(
                    *(task for _, task in search_tasks),
                    return_exceptions=True
                )

                for (search_name, _), result in zip(search_tasks, results):
                    if isinstance(result, Exception):
                        # The exception is retained in internal logs only.  It
                        # is deliberately not copied to response metadata,
                        # where it could expose provider or connection detail.
                        logger.warning("Retrieval search failed", search_type=search_name, error=str(result))
                        backend_status[search_name] = {
                            "status": "error",
                            "reason": "backend_error",
                        }
                    elif self._search_result_is_unavailable(result):
                        backend_status[search_name] = {
                            "status": "unavailable",
                            "reason": self._safe_backend_reason(result),
                        }
                    else:
                        search_results.append(result)
                        backend_status[search_name] = {"status": "success"}
                        logger.debug("Retrieval search completed", search_type=search_name, chunks=len(result.chunks))

            # A response without any successful backend has no evidence on
            # which to ground an answer.  It is an operational error, not a
            # valid empty retrieval result.
            if not search_results:
                logger.warning("No retrieval backends succeeded", backends=backend_status)
                return RetrievalContext(
                    chunks=[],
                    confidence=0.0,
                    sources=[],
                    query=query,
                    filters_applied=filters,
                    query_intent=query_intent,
                    content_types_found=[],
                    retrieval_metadata=self._retrieval_metadata(
                        status="error",
                        backend_status=backend_status,
                        search_results=[],
                        execution_time_ms=(time.time() - start_time) * 1000,
                        query_intent=query_intent,
                        content_types=content_types,
                        reason="no_search_backend_succeeded",
                    ),
                )
            
            # Step 2: Apply RRF fusion
            fused_chunks = self.rrf.fuse(search_results, top_k=self.config.vector_top_k)
            logger.debug("RRF fusion completed", chunks=len(fused_chunks))

            # Step 3: Deduplicate before reranking so rerank slots are not wasted.
            if self.config.dedup_enabled:
                fused_chunks = self._deduplicate(fused_chunks)
                logger.debug("Deduplication completed", chunks=len(fused_chunks))
            
            # Step 4: Apply cross-encoder reranking
            if self.reranker and self.config.rerank_enabled and len(fused_chunks) > max_chunks:
                try:
                    reranked_chunks = await self.reranker.rerank(
                        query=query,
                        chunks=fused_chunks,
                        top_k=max_chunks
                    )
                    logger.debug("Reranking completed", chunks=len(reranked_chunks))
                except Exception as e:
                    logger.warning("Reranking failed, using fused results", error=str(e))
                    reranked_chunks = fused_chunks[:max_chunks]
            else:
                reranked_chunks = fused_chunks[:max_chunks]
            
            # Step 5: Apply brand boost
            if self.brand_boost and self.config.brand_boost_enabled:
                reranked_chunks = self.brand_boost.apply_boost(reranked_chunks)
                logger.debug("Brand boost applied")
            
            # Step 6: Apply page context boost
            if self.page_boost and page_context and self.config.page_boost_enabled:
                # Convert dict to PageContext if needed
                if isinstance(page_context, dict):
                    normalized_page_context = dict(page_context)
                    if "meta" not in normalized_page_context and isinstance(normalized_page_context.get("metadata"), dict):
                        normalized_page_context["meta"] = normalized_page_context["metadata"]
                    page_ctx = PageContext(**normalized_page_context)
                else:
                    page_ctx = page_context
                reranked_chunks = self.page_boost.apply_boost(reranked_chunks, page_ctx)
                logger.debug("Page boost applied")

            # Phase 2: Enrich chunks with structured data
            reranked_chunks = self._enrich_with_structured_data(reranked_chunks)
            logger.debug("Structured data enrichment completed")
            
            # Calculate overall confidence
            confidence = max([chunk.score for chunk in reranked_chunks], default=0.0)
            
            # Extract sources
            sources = list(set(chunk.doc_id for chunk in reranked_chunks))
            
            # Phase 2: Extract content types found in results
            content_types_found = list(set(
                chunk.content_type for chunk in reranked_chunks 
                if chunk.content_type
            ))
            
            # Build retrieval context
            execution_time = (time.time() - start_time) * 1000
            retrieval_status = self._overall_retrieval_status(
                chunks=reranked_chunks,
                backend_status=backend_status,
            )
            retrieval_metadata = self._retrieval_metadata(
                status=retrieval_status,
                backend_status=backend_status,
                search_results=search_results,
                execution_time_ms=execution_time,
                query_intent=query_intent,
                content_types=content_types,
            )
            retrieval_metadata.update({
                "reranked": bool(self.reranker and self.config.rerank_enabled),
                "deduped": self.config.dedup_enabled,
            })
            
            result = RetrievalContext(
                chunks=reranked_chunks,
                confidence=confidence,
                sources=sources,
                query=query,
                filters_applied=filters,
                query_intent=query_intent,  # Phase 2
                content_types_found=content_types_found,  # Phase 2
                boost_info={
                    "page_context_applied": bool(page_context),
                    "brand_boost_applied": bool(self.brand_boost),
                    "filters_applied": bool(filters),
                    "content_type_filtering": bool(content_types)  # Phase 2
                },
                retrieval_metadata=retrieval_metadata,
            )
            
            logger.info("Retrieval completed", 
                       chunks_count=len(reranked_chunks), 
                       confidence=confidence,
                       execution_time_ms=execution_time)
            
            return result
            
        except Exception as e:
            logger.error("Error in retrieval pipeline", error=str(e), exc_info=True)
            return RetrievalContext(
                chunks=[],
                confidence=0.0,
                sources=[],
                query=query,
                retrieval_metadata=self._retrieval_metadata(
                    status="error",
                    backend_status=backend_status,
                    search_results=search_results,
                    reason="pipeline_error",
                ),
            )

    @staticmethod
    def _unavailable_backend_status() -> Dict[str, str]:
        """Return a safe status for a backend that could not be initialized."""
        return {"status": "unavailable", "reason": "backend_unavailable"}

    @staticmethod
    def _search_result_is_unavailable(result: Any) -> bool:
        """Whether a backend intentionally returned no executable result."""
        if getattr(result, "backend_status", "success") != "success":
            return True

        # ``disabled_reason`` predates the explicit SearchResult contract.
        # Continue honoring it so older implementations cannot silently turn
        # an unavailable backend into a no-evidence result.
        metadata = getattr(result, "metadata", {})
        return isinstance(metadata, dict) and bool(metadata.get("disabled_reason"))

    @staticmethod
    def _safe_backend_reason(result: Any) -> str:
        """Map backend diagnostics to the small public-safe reason vocabulary."""
        reason = getattr(result, "backend_reason", None)
        if reason in {"authentication_failed", "backend_unavailable", "collection_unavailable"}:
            return reason

        metadata = getattr(result, "metadata", {})
        if isinstance(metadata, dict) and metadata.get("disabled_reason") == "voyage_auth_failed":
            return "authentication_failed"
        return "backend_unavailable"

    @staticmethod
    def _overall_retrieval_status(
        chunks: List[DocumentChunk],
        backend_status: Dict[str, Dict[str, str]],
    ) -> str:
        """Classify retrieval without equating backend failure to no evidence."""
        states = [state.get("status") for state in backend_status.values()]
        has_success = "success" in states
        has_failure = any(state in {"error", "unavailable"} for state in states)

        if not has_success:
            return "error"
        if has_failure:
            return "degraded"
        return "evidence" if chunks else "no_evidence"

    @staticmethod
    def _retrieval_metadata(
        *,
        status: str,
        backend_status: Dict[str, Dict[str, str]],
        search_results: List[Any],
        execution_time_ms: Optional[float] = None,
        query_intent: Optional[str] = None,
        content_types: Optional[List[str]] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build stable, provider-safe metadata for callers of the pipeline."""
        safe_backend_status = {
            backend: dict(details)
            for backend, details in backend_status.items()
        }
        successful_backends = [
            backend
            for backend, details in safe_backend_status.items()
            if details.get("status") == "success"
        ]
        failed_backends = [
            backend
            for backend, details in safe_backend_status.items()
            if details.get("status") in {"error", "unavailable"}
        ]

        metadata: Dict[str, Any] = {
            "status": status,
            "backend_status": safe_backend_status,
            "successful_backends": successful_backends,
            "failed_backends": failed_backends,
            "search_methods": [result.search_type for result in search_results],
            "total_candidates": sum(result.total_found for result in search_results),
            "intent_detected": query_intent,
            "content_types_requested": content_types,
        }
        if execution_time_ms is not None:
            metadata["execution_time_ms"] = execution_time_ms
        if status == "degraded":
            metadata["reason"] = reason or "partial_backend_failure"
        elif status == "error":
            metadata["reason"] = reason or "retrieval_error"
            # Preserve the existing error key without surfacing exception text.
            metadata["error"] = "retrieval_unavailable" if reason == "no_search_backend_succeeded" else "retrieval_error"

        return metadata
    
    def _deduplicate(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        """Deduplicate chunks using structured entity identity before content fallback."""
        seen = set()
        deduplicated = []
        
        for chunk in chunks:
            key = self._dedup_key(chunk)
            if key not in seen:
                seen.add(key)
                deduplicated.append(chunk)
        
        return deduplicated

    def _dedup_key(self, chunk: DocumentChunk) -> tuple:
        metadata = chunk.metadata or {}
        product_data = chunk.product_data or metadata.get("product_data") or {}
        dealer_data = chunk.dealer_data or metadata.get("dealer_data") or {}
        content_type = chunk.content_type or metadata.get("content_type")

        if content_type == "product":
            product_id = self._first_value(
                [product_data, metadata],
                ["sku", "id", "product_id", "variant_id", "code"],
            )
            if product_id:
                return ("product", self._normalize_identity(product_id))

        if content_type == "dealer":
            dealer_id = self._first_value(
                [dealer_data, metadata],
                ["id", "dealer_id", "code", "name"],
            )
            city = self._first_value([dealer_data, metadata], ["city", "state", "pincode"])
            if dealer_id:
                return ("dealer", self._normalize_identity(dealer_id), self._normalize_identity(city))

        url = self._first_value([metadata, {"url": chunk.url}], ["url", "source_url"])
        if url:
            return ("url", self._normalize_identity(url), self._normalize_identity(chunk.section))

        if chunk.doc_id:
            return ("doc", self._normalize_identity(chunk.doc_id), self._normalize_identity(chunk.section))

        title = self._first_value([metadata, {"title": chunk.title}], ["title", "name"])
        if title:
            return ("title", self._normalize_identity(title), self._normalize_identity(chunk.section))

        return ("content", self._normalize_content(chunk.content))

    @staticmethod
    def _first_value(sources: List[Dict[str, Any]], keys: List[str]) -> Optional[Any]:
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    return value
        return None

    @staticmethod
    def _normalize_identity(value: Any) -> str:
        if value is None:
            return ""
        return re.sub(r"\s+", " ", str(value).strip().lower())

    @classmethod
    def _normalize_content(cls, value: str) -> str:
        return cls._normalize_identity(value)[:600]
    
    def _detect_query_intent(self, query: str, page_context: Optional[Dict[str, Any]] = None) -> str:
        """
        Detect the intent of the user's query.
        
        Returns:
            "product_search" | "dealer_search" | "faq" | "office" | "category" | "general"
        """
        query_lower = query.lower()
        
        # Product search indicators. Vertical vocabulary is explicit rather
        # than silently inherited by every Hybrid RAG agent.
        product_keywords = set(NEUTRAL_PRODUCT_KEYWORDS)
        for vertical in self.verticals:
            product_keywords.update(VERTICAL_PRODUCT_KEYWORDS[vertical])
        
        # Dealer search indicators
        dealer_keywords = [
            'store', 'dealer', 'showroom', 'retailer', 'shop',
            'near', 'location', 'city', 'address', 'contact',
            'where to buy', 'nearest', 'close to', 'find dealer'
        ]
        
        # FAQ indicators
        faq_keywords = [
            'how to', 'why', 'what is', 'can i', 'should i',
            'install', 'installation', 'warranty', 'return',
            'maintenance', 'clean', 'repair', 'troubleshoot'
        ]
        
        # Office/contact indicators
        office_keywords = [
            'office', 'headquarters', 'corporate', 'head office',
            'customer service', 'support', 'helpline', 'contact us'
        ]
        
        # Category browsing indicators
        category_keywords = [
            'types of', 'categories', 'range', 'collection',
            'all products', 'browse', 'catalog', 'catalogue'
        ]
        
        # Check page context for SKU/product page
        if page_context:
            # Access Pydantic model attributes directly, not with .get()
            if (hasattr(page_context, 'sku') and page_context.sku) or \
               (hasattr(page_context, 'path') and page_context.path and 'product' in page_context.path.lower()):
                return "product_search"
        
        # Count keyword matches
        product_score = sum(1 for kw in product_keywords if kw in query_lower)
        dealer_score = sum(1 for kw in dealer_keywords if kw in query_lower)
        faq_score = sum(1 for kw in faq_keywords if kw in query_lower)
        office_score = sum(1 for kw in office_keywords if kw in query_lower)
        category_score = sum(1 for kw in category_keywords if kw in query_lower)
        
        # Return intent with highest score
        scores = {
            "product_search": product_score,
            "dealer_search": dealer_score,
            "faq": faq_score,
            "office": office_score,
            "category": category_score
        }
        
        max_score = max(scores.values())
        if max_score > 0:
            # Find intent with highest score
            for intent, score in scores.items():
                if score == max_score:
                    return intent
        
        return "general"
    
    def _intent_to_content_types(self, intent: str) -> Optional[List[str]]:
        """
        Map query intent to content types for filtering.
        
        Args:
            intent: Detected query intent
            
        Returns:
            List of content types to filter by, or None for no filtering
        """
        intent_mapping = {
            "product_search": ["product", "category"],  # Include category for product browsing
            "dealer_search": ["dealer", "office"],      # Dealers and office locations
            "faq": ["faq", "guide"],                    # FAQs and how-to guides
            "office": ["office"],                        # Office/headquarters info
            "category": ["category", "product"],         # Category browsing
            "general": None                              # No filtering for general queries
        }
        
        return intent_mapping.get(intent)
    
    def _enrich_with_structured_data(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        """
        Enrich chunks with product_data and dealer_data from metadata.
        
        This extracts structured data fields that were stored during ingestion
        and makes them directly accessible on the chunk object.
        
        Args:
            chunks: List of document chunks
            
        Returns:
            Enriched chunks with product_data and dealer_data populated
        """
        for chunk in chunks:
            # Extract content_type from metadata if not already set
            if not chunk.content_type and "content_type" in chunk.metadata:
                chunk.content_type = chunk.metadata["content_type"]
            
            # Extract product_data if this is a product chunk
            if chunk.content_type == "product" and "product_data" in chunk.metadata:
                chunk.product_data = chunk.metadata["product_data"]
            
            # Extract dealer_data if this is a dealer chunk
            elif chunk.content_type == "dealer" and "dealer_data" in chunk.metadata:
                chunk.dealer_data = chunk.metadata["dealer_data"]
        
        return chunks

    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of retrieval components."""
        health = {
            "vector_search": "disabled",
            "bm25_search": "disabled",
            "reranker": "disabled",
            "overall": "healthy"
        }
        
        # Check vector search
        if self.vector_search:
            try:
                vs_health = await self.vector_search.health_check()
                health["vector_search"] = vs_health.get("overall", "unknown")
            except Exception as e:
                health["vector_search"] = f"error: {str(e)}"
                health["overall"] = "degraded"
        
        # Check BM25 search
        if self.bm25_search:
            try:
                bm25_health = await self.bm25_search.health_check()
                health["bm25_search"] = bm25_health.get("status", "unknown")
            except Exception as e:
                health["bm25_search"] = f"error: {str(e)}"
                health["overall"] = "degraded"
        
        # Check reranker
        if self.reranker:
            try:
                reranker_healthy = await self.reranker.health_check()
                health["reranker"] = "healthy" if reranker_healthy else "unhealthy"
            except Exception as e:
                health["reranker"] = f"error: {str(e)}"
                # Reranker failure is not critical (has fallback)
        
        return health
    
    async def close(self):
        """Close all connections."""
        if self.vector_search:
            await self.vector_search.close()
        if self.bm25_search:
            await self.bm25_search.close()
        if self.reranker:
            await self.reranker.close()
