"""
Test Retrieval Pipeline End-to-End
Tests the complete hybrid retrieval system with real queries
"""

import os
import asyncio
from datetime import datetime
import structlog

logger = structlog.get_logger()


# Test queries with expected behavior
TEST_QUERIES = [
    {
        "query": "How do I install a kitchen faucet?",
        "expected_type": "manual",
        "expected_content": ["installation", "water supply", "mounting"],
        "page_context": {
            "url": "https://essco.com/products/faucets/kitchen",
            "page_type": "product_detail",
            "product_sku": "ESSCO-FAUCET-001"
        }
    },
    {
        "query": "My faucet has low water pressure",
        "expected_type": "faq",
        "expected_content": ["aerator", "pressure", "clogged"],
        "page_context": {
            "url": "https://essco.com/support",
            "page_type": "support"
        }
    },
    {
        "query": "What is covered under warranty?",
        "expected_type": "policy",
        "expected_content": ["warranty", "defects", "claim"],
        "page_context": {
            "url": "https://essco.com/warranty",
            "page_type": "policy"
        }
    },
    {
        "query": "shower installation steps",
        "expected_type": "manual",
        "expected_content": ["shower", "install", "valve"],
        "page_context": {
            "url": "https://essco.com/products/showers",
            "page_type": "product_category",
            "category": "showers"
        }
    },
    {
        "query": "cleaning and maintenance tips",
        "expected_type": "article",
        "expected_content": ["clean", "maintain", "care"],
        "page_context": {
            "url": "https://essco.com/blog/maintenance",
            "page_type": "blog"
        }
    }
]


class RetrievalPipelineTest:
    """Test the complete retrieval pipeline."""
    
    def __init__(self):
        from motor.motor_asyncio import AsyncIOMotorClient
        from retrieval.pipeline import RetrievalPipeline
        from retrieval.types import RetrievalConfig, PageContext
        
        self.RetrievalPipeline = RetrievalPipeline
        self.PageContext = PageContext
        
        # Setup MongoDB connection
        mongodb_uri = os.getenv("MONGODB_URI")
        if not mongodb_uri:
            raise ValueError("MONGODB_URI environment variable not set")
        
        db_name = os.getenv("MONGODB_DATABASE", "agent-builder")
        self.client = AsyncIOMotorClient(mongodb_uri)
        self.db = self.client[db_name]
        
        # Initialize retrieval pipeline
        config = RetrievalConfig(
            brand_id="essco-bathware",
            collection_name="knowledge_base",
            vector_enabled=True,
            bm25_enabled=True,
            rerank_enabled=True,
            brand_boost_enabled=True,
            page_boost_enabled=True,
            top_k=5,
            similarity_threshold=0.5
        )
        
        self.pipeline = RetrievalPipeline(config=config, brand_id="essco-bathware")
        logger.info("Retrieval pipeline test initialized")
    
    async def test_query(self, test_case: dict, test_num: int, total: int):
        """Test a single query."""
        logger.info(
            f"\n{'='*80}\nTest {test_num}/{total}: {test_case['query']}\n{'='*80}"
        )
        
        query = test_case["query"]
        page_context = self.PageContext(**test_case["page_context"])
        
        try:
            # Execute retrieval
            start_time = datetime.utcnow()
            result = await self.pipeline.retrieve(query, page_context)
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            
            # Display results
            logger.info(f"\n⏱️  Retrieval completed in {elapsed:.3f}s")
            logger.info(f"📊 Retrieved {len(result.chunks)} chunks")
            
            if result.chunks:
                logger.info(f"\n📄 Top Results:")
                for i, chunk in enumerate(result.chunks[:3], 1):
                    logger.info(f"\n  {i}. {chunk.title}")
                    logger.info(f"     Score: {chunk.score:.4f}")
                    logger.info(f"     Type: {chunk.metadata.get('content_type', 'unknown')}")
                    logger.info(f"     URL: {chunk.url or 'N/A'}")
                    logger.info(f"     Preview: {chunk.content[:120]}...")
                
                # Validate expectations
                logger.info(f"\n✅ Validation:")
                
                # Check content type
                found_types = [c.metadata.get('content_type') for c in result.chunks]
                expected_type = test_case['expected_type']
                if expected_type in found_types:
                    logger.info(f"   ✓ Found expected content type: {expected_type}")
                else:
                    logger.warning(f"   ✗ Expected type '{expected_type}' not in top results")
                    logger.info(f"   Found types: {found_types[:5]}")
                
                # Check content keywords
                all_content = " ".join([c.content.lower() for c in result.chunks])
                found_keywords = []
                missing_keywords = []
                
                for keyword in test_case['expected_content']:
                    if keyword.lower() in all_content:
                        found_keywords.append(keyword)
                    else:
                        missing_keywords.append(keyword)
                
                if found_keywords:
                    logger.info(f"   ✓ Found keywords: {', '.join(found_keywords)}")
                if missing_keywords:
                    logger.warning(f"   ✗ Missing keywords: {', '.join(missing_keywords)}")
                
                # Check scores
                top_score = result.chunks[0].score
                if top_score > 0.7:
                    logger.info(f"   ✓ High confidence (score: {top_score:.3f})")
                elif top_score > 0.5:
                    logger.info(f"   ~ Medium confidence (score: {top_score:.3f})")
                else:
                    logger.warning(f"   ✗ Low confidence (score: {top_score:.3f})")
                
                # Display metadata
                if result.retrieval_metadata:
                    logger.info(f"\n📈 Pipeline Metadata:")
                    for key, value in result.retrieval_metadata.items():
                        logger.info(f"   {key}: {value}")
                
                return {
                    "success": True,
                    "query": query,
                    "num_results": len(result.chunks),
                    "top_score": top_score,
                    "latency": elapsed,
                    "expected_type_found": expected_type in found_types,
                    "keywords_found": len(found_keywords),
                    "keywords_missing": len(missing_keywords)
                }
            else:
                logger.warning("❌ No results returned")
                return {
                    "success": False,
                    "query": query,
                    "num_results": 0,
                    "latency": elapsed,
                    "error": "No results"
                }
        
        except Exception as e:
            logger.error(f"❌ Test failed", error=str(e), exc_info=True)
            return {
                "success": False,
                "query": query,
                "error": str(e)
            }
    
    async def test_pipeline_components(self):
        """Test individual pipeline components."""
        logger.info("\n" + "="*80)
        logger.info("Testing Pipeline Components")
        logger.info("="*80)
        
        from retrieval.types import PageContext
        
        query = "faucet installation"
        page_context = PageContext(
            url="https://essco.com/products/faucets",
            page_type="product_category"
        )
        
        try:
            # Test vector search
            logger.info("\n🔍 Testing Vector Search...")
            if self.pipeline.vector_search:
                vector_results = await self.pipeline.vector_search.search(
                    query=query,
                    top_k=5,
                    filter_dict={"metadata.brand_id": "essco-bathware"}
                )
                logger.info(f"   ✓ Vector search returned {len(vector_results)} results")
            else:
                logger.warning("   ⚠️  Vector search not enabled")
            
            # Test text search
            logger.info("\n📝 Testing Text Search...")
            if self.pipeline.text_search:
                text_results = await self.pipeline.text_search.search(
                    query=query,
                    top_k=5,
                    filter_dict={"metadata.brand_id": "essco-bathware"}
                )
                logger.info(f"   ✓ Text search returned {len(text_results)} results")
            else:
                logger.warning("   ⚠️  Text search not enabled")
            
            logger.info("\n✅ Component tests completed")
            
        except Exception as e:
            logger.error("❌ Component test failed", error=str(e), exc_info=True)
    
    async def run_all_tests(self):
        """Run all test queries."""
        logger.info("\n" + "="*80)
        logger.info("Starting Retrieval Pipeline Tests")
        logger.info("="*80)
        
        # Test components first
        await self.test_pipeline_components()
        
        # Run all test queries
        results = []
        total = len(TEST_QUERIES)
        
        for i, test_case in enumerate(TEST_QUERIES, 1):
            result = await self.test_query(test_case, i, total)
            results.append(result)
            await asyncio.sleep(0.5)  # Brief pause between tests
        
        # Summary
        logger.info("\n" + "="*80)
        logger.info("Test Summary")
        logger.info("="*80)
        
        successful = [r for r in results if r.get("success")]
        failed = [r for r in results if not r.get("success")]
        
        logger.info(f"\n📊 Results: {len(successful)}/{total} tests passed")
        
        if successful:
            avg_latency = sum(r.get("latency", 0) for r in successful) / len(successful)
            avg_results = sum(r.get("num_results", 0) for r in successful) / len(successful)
            avg_score = sum(r.get("top_score", 0) for r in successful if "top_score" in r)
            avg_score = avg_score / len([r for r in successful if "top_score" in r]) if successful else 0
            
            logger.info(f"⏱️  Average latency: {avg_latency:.3f}s")
            logger.info(f"📄 Average results: {avg_results:.1f}")
            logger.info(f"🎯 Average top score: {avg_score:.3f}")
            
            # Type accuracy
            type_matches = sum(r.get("expected_type_found", False) for r in successful)
            logger.info(f"✅ Content type accuracy: {type_matches}/{len(successful)}")
            
            # Keyword coverage
            total_keywords = sum(r.get("keywords_found", 0) for r in successful)
            total_missing = sum(r.get("keywords_missing", 0) for r in successful)
            keyword_rate = total_keywords / (total_keywords + total_missing) if (total_keywords + total_missing) > 0 else 0
            logger.info(f"🔑 Keyword coverage: {keyword_rate:.1%} ({total_keywords}/{total_keywords + total_missing})")
        
        if failed:
            logger.warning(f"\n❌ Failed tests:")
            for r in failed:
                logger.warning(f"   - {r['query']}: {r.get('error', 'Unknown error')}")
        
        logger.info("\n✅ All tests completed!")
        
        return results
    
    async def close(self):
        """Cleanup resources."""
        if hasattr(self.pipeline, 'close'):
            await self.pipeline.close()
        self.client.close()


async def main():
    """Main function."""
    # Configure logging
    structlog.configure(
        processors=[structlog.dev.ConsoleRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    test = None
    try:
        test = RetrievalPipelineTest()
        await test.run_all_tests()
    except Exception as e:
        logger.error("Test suite failed", error=str(e), exc_info=True)
        raise
    finally:
        if test is not None:
            await test.close()


if __name__ == "__main__":
    # Load environment variables
    from pathlib import Path
    env_file = Path(__file__).parent.parent / "apps" / "api" / ".env"
    
    if env_file.exists():
        print(f"Loading environment from {env_file}")
        from dotenv import load_dotenv
        load_dotenv(env_file)
    else:
        print("⚠️  No .env file found, using system environment variables")
    
    # Run tests
    asyncio.run(main())
