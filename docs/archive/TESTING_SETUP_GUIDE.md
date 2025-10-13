# Testing and Setup Guide

Complete guide for setting up and testing the Agent Builder Platform's retrieval system.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Initial Setup](#initial-setup)
3. [MongoDB Configuration](#mongodb-configuration)
4. [Document Ingestion](#document-ingestion)
5. [Testing Retrieval](#testing-retrieval)
6. [Troubleshooting](#troubleshooting)
7. [Performance Benchmarks](#performance-benchmarks)

---

## 1. Prerequisites

### Required Services

- **MongoDB Atlas** (v6.0+) with Vector Search enabled
- **Redis** (v6.0+) for caching (optional but recommended)
- **Python 3.9+**

### Required API Keys

```bash
# Required
MONGODB_URI="mongodb+srv://..."
OPENAI_API_KEY="sk-..."              # For LLM
VOYAGE_API_KEY="pa-..."              # For embeddings

# Optional
REDIS_URL="redis://localhost:6379"   # For caching
QWEN_API_KEY="sk-..."               # Alternative LLM provider
```

### Python Packages

All packages are installed via the monorepo structure:

```bash
# From project root
pip install -e packages/commons
pip install -e packages/retrieval
pip install -e packages/llm
pip install -e packages/memory
pip install -e apps/api

# Or install all at once
./install.sh
```

---

## 2. Initial Setup

### Step 1: Environment Configuration

Create `.env` file in `apps/api/`:

```bash
# apps/api/.env
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/
MONGODB_DATABASE=agent-builder

VOYAGE_API_KEY=pa-your-voyage-key
OPENAI_API_KEY=sk-your-openai-key

# Optional
REDIS_URL=redis://localhost:6379
REDIS_PASSWORD=your-redis-password

# Configuration
MODEL_PROVIDER=openai
EMBEDDINGS_PROVIDER=voyage
API_LOG_LEVEL=info
```

### Step 2: Verify Environment

```bash
python -c "
import os
from dotenv import load_dotenv
load_dotenv('apps/api/.env')

required = ['MONGODB_URI', 'VOYAGE_API_KEY', 'OPENAI_API_KEY']
for key in required:
    value = os.getenv(key)
    status = '✓' if value else '✗'
    print(f'{status} {key}: {\"Set\" if value else \"Missing\"}'
)
"
```

---

## 3. MongoDB Configuration

### Step 1: Create MongoDB Indexes

Run the index creation script:

```bash
# From project root
python scripts/setup_mongodb_indexes.py
```

This will:
1. ✅ Create text search indexes (automated)
2. ✅ Create metadata indexes (automated)
3. ✅ Create conversation indexes (automated)
4. ✅ Create admin collection indexes (automated)
5. ⚠️  Display instructions for vector search index (manual setup required)

### Step 2: Create Vector Search Index Manually

**Important**: Vector search index must be created via MongoDB Atlas UI.

1. Go to MongoDB Atlas Console
2. Navigate to your cluster → "Search" tab
3. Click "Create Search Index"
4. Select "JSON Editor"
5. Paste the following configuration:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embeddings",
      "numDimensions": 1024,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "metadata.brand_id"
    },
    {
      "type": "filter",
      "path": "metadata.content_type"
    },
    {
      "type": "filter",
      "path": "metadata.product_category"
    }
  ]
}
```

6. Name the index: `vector_index`
7. Select database: `agent-builder`
8. Select collection: `knowledge_base`
9. Click "Create Search Index"
10. Wait for index to build (usually 1-5 minutes)

### Step 3: Verify Indexes

```bash
python scripts/setup_mongodb_indexes.py --verify-only
```

Expected output:
```
✅ Text indexes: knowledge_base_text
✅ Metadata indexes: chunk_id_unique, doc_section_idx, metadata_filters_idx
✅ Conversation indexes: conversation_id_session, user_memory_user_brand
✅ Admin indexes: brand_slug_unique, agent_slug_idx
⚠️  Vector index: Verify manually in Atlas UI (must show "Active")
```

---

## 4. Document Ingestion

### Step 1: Ingest Sample Documents

**Without embeddings** (faster, for testing structure):
```bash
python scripts/test_document_ingestion.py
```

**With embeddings** (required for vector search):
```bash
python scripts/test_document_ingestion.py --with-embeddings
```

This ingests 5 sample Essco Bathware documents:
- Kitchen Faucet Installation Guide
- Faucet Troubleshooting - Low Water Pressure
- Faucet Warranty Information
- Shower System Installation
- General Maintenance Tips

### Step 2: Verify Ingestion

Expected output:
```
Cleared 0 existing documents
Inserting 5 sample documents...
Generating embeddings with Voyage AI...
✅ Embeddings generated successfully
✅ Inserted 5 documents

=== Verifying Documents ===
Total Essco documents: 5

Sample document:
  Title: Kitchen Faucet Installation Guide
  Content length: 387 chars
  Has embeddings: True
  Content type: manual

=== Testing Text Search ===
Searching for: 'install faucet'
Found 3 results:
  1. Kitchen Faucet Installation Guide (score: 3.45)
  2. Shower System Installation (score: 2.12)
  3. Faucet Troubleshooting - Low Water Pressure (score: 1.87)

✅ Document ingestion test completed successfully!
```

### Step 3: Ingest Your Own Documents

Use the ingestion API:

```bash
curl -X POST http://localhost:8000/api/v1/ingest/document \
  -H "Content-Type: application/json" \
  -d '{
    "brand_id": "your-brand",
    "doc_id": "unique-doc-id",
    "title": "Document Title",
    "content": "Your document content here...",
    "metadata": {
      "content_type": "manual",
      "product_category": "faucets",
      "sku": "PROD-001"
    }
  }'
```

Or use bulk upload via the admin dashboard (when available).

---

## 5. Testing Retrieval

### Step 1: Test Retrieval Pipeline

Run comprehensive retrieval tests:

```bash
python scripts/test_retrieval_pipeline.py
```

This tests:
- ✅ Vector search component
- ✅ Text search (BM25) component
- ✅ Hybrid fusion (RRF)
- ✅ Cross-encoder reranking
- ✅ Brand and page boosting
- ✅ End-to-end retrieval with 5 test queries

### Step 2: Review Test Results

Expected output for each query:

```
================================================================================
Test 1/5: How do I install a kitchen faucet?
================================================================================

⏱️  Retrieval completed in 0.847s
📊 Retrieved 5 chunks

📄 Top Results:

  1. Kitchen Faucet Installation Guide
     Score: 0.8723
     Type: manual
     Source: https://essco.com/support/faucet-installation
     Preview: To install your Essco kitchen faucet, follow these steps: 1. Turn off the water supply valves under the sink...

  2. Faucet Troubleshooting - Low Water Pressure
     Score: 0.6845
     Type: faq
     Source: https://essco.com/support/troubleshooting/low-pressure
     Preview: If you're experiencing low water pressure from your faucet: Possible Causes: - Clogged aerator screen...

✅ Validation:
   ✓ Found expected content type: manual
   ✓ Found keywords: installation, water supply, mounting
   ✓ High confidence (score: 0.872)

📈 Pipeline Metadata:
   vector_search_results: 10
   text_search_results: 10
   fused_results: 15
   reranked_results: 12
   final_results: 5
```

### Step 3: Test Summary

After all queries complete:

```
================================================================================
Test Summary
================================================================================

📊 Results: 5/5 tests passed
⏱️  Average latency: 0.924s
📄 Average results: 5.0
🎯 Average top score: 0.823
✅ Content type accuracy: 5/5
🔑 Keyword coverage: 93.3% (14/15)

✅ All tests completed!
```

### Step 4: Test via API

Start the API server:

```bash
cd apps/api
uvicorn app.main:app --reload --port 8000
```

Test with curl:

```bash
curl -X POST http://localhost:8000/api/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "essco-agent",
    "session_id": "test-session-123",
    "message": "How do I install a kitchen faucet?",
    "page_context": {
      "url": "https://essco.com/products/faucets",
      "page_type": "product_category"
    }
  }'
```

Expected response:

```json
{
  "response": "To install your Essco kitchen faucet, follow these steps:\n\n1. Turn off the water supply valves under the sink\n2. Remove the old faucet if present...",
  "citations": [
    {
      "title": "Kitchen Faucet Installation Guide",
      "url": "https://essco.com/support/faucet-installation",
      "excerpt": "To install your Essco kitchen faucet..."
    }
  ],
  "context": {
    "chunks_retrieved": 5,
    "top_score": 0.8723,
    "sources": ["manual", "faq"]
  }
}
```

---

## 6. Troubleshooting

### Issue: No Results from Vector Search

**Symptoms:**
- Vector search returns empty results
- Only text search results appear
- Error: "Vector index not found"

**Solutions:**

1. **Verify vector index exists:**
   - Go to Atlas UI → Search tab
   - Check index status is "Active"
   - Verify index name is `vector_index`

2. **Check embeddings:**
   ```bash
   python -c "
   from motor.motor_asyncio import AsyncIOMotorClient
   import asyncio
   import os
   
   async def check():
       client = AsyncIOMotorClient(os.getenv('MONGODB_URI'))
       db = client['agent-builder']
       doc = await db.knowledge_base.find_one({'metadata.brand_id': 'essco-bathware'})
       print(f'Has embeddings: {\"embeddings\" in doc}')
       if 'embeddings' in doc:
           print(f'Embedding dimensions: {len(doc[\"embeddings\"])}')
   
   asyncio.run(check())
   "
   ```
   Expected: `Has embeddings: True`, `Embedding dimensions: 1024`

3. **Regenerate embeddings:**
   ```bash
   python scripts/test_document_ingestion.py --with-embeddings --no-clear
   ```

### Issue: Slow Retrieval (<2s target)

**Symptoms:**
- Retrieval takes >3 seconds
- P95 latency exceeds SLO

**Solutions:**

1. **Check indexes:**
   ```bash
   python scripts/setup_mongodb_indexes.py --verify-only
   ```

2. **Enable Redis caching:**
   ```bash
   # Add to .env
   REDIS_URL=redis://localhost:6379
   ```

3. **Reduce top_k values:**
   ```python
   # In RetrievalConfig
   top_k_vector=5  # Down from 10
   top_k_text=5    # Down from 10
   top_k_final=3   # Down from 5
   ```

4. **Check network latency to MongoDB Atlas:**
   ```bash
   ping your-cluster.mongodb.net
   ```

### Issue: Poor Relevance

**Symptoms:**
- Retrieved documents not relevant
- Wrong content types returned
- Low confidence scores (<0.5)

**Solutions:**

1. **Adjust similarity threshold:**
   ```python
   # In RetrievalConfig
   similarity_threshold=0.6  # Up from 0.5
   ```

2. **Enable all boosting:**
   ```python
   enable_brand_boost=True
   enable_page_boost=True
   ```

3. **Check document metadata:**
   - Ensure `content_type` is set correctly
   - Verify `brand_id` matches
   - Add `product_category` tags

4. **Tune fusion weights:**
   ```python
   # In rrf.py
   k=40  # Down from 60 to favor top results
   ```

### Issue: Import Errors

**Symptoms:**
- `ModuleNotFoundError: No module named 'retrieval'`
- `ImportError: cannot import name 'VoyageClient'`

**Solutions:**

1. **Install packages in editable mode:**
   ```bash
   pip install -e packages/retrieval
   pip install -e packages/commons
   ```

2. **Check Python path:**
   ```bash
   python -c "import sys; print('\n'.join(sys.path))"
   ```
   Should include: `/path/to/agent-builder/packages/retrieval/src`

3. **Reinstall dependencies:**
   ```bash
   cd packages/retrieval
   pip install -r requirements.txt
   ```

---

## 7. Performance Benchmarks

### Target SLOs

| Metric | Target | Critical |
|--------|--------|----------|
| P50 latency | <1.5s | <2.5s |
| P95 latency | <3.0s | <5.0s |
| P99 latency | <5.0s | <10.0s |
| Citation coverage | >95% | >80% |
| Cache hit ratio | >60% | >40% |
| Uptime | >99.9% | >99.0% |

### Benchmark Results (Expected)

**With Redis cache (warm):**
```
P50: 0.342s
P95: 0.687s
P99: 1.234s
Cache hit ratio: 73%
```

**Without cache (cold):**
```
P50: 0.924s
P95: 1.876s
P99: 3.145s
```

**Component breakdown:**
```
Vector search:   ~300ms (with index)
Text search:     ~150ms (with index)
Reranking:       ~200ms (Voyage API)
Fusion + boost:  ~50ms
LLM generation:  ~1,500ms (separate step)
```

### Running Benchmarks

```bash
# Run 100 queries with various patterns
python scripts/benchmark_retrieval.py --queries 100 --concurrency 10

# Test with cache disabled
python scripts/benchmark_retrieval.py --no-cache

# Test specific query patterns
python scripts/benchmark_retrieval.py --pattern installation
```

---

## Next Steps

1. ✅ **Complete setup** following this guide
2. ✅ **Verify all tests pass**
3. 🚧 **Add your own documents** via ingestion API
4. 🚧 **Integrate with widget** for frontend testing
5. 🚧 **Deploy to production** following PRODUCTION_READY.md
6. 🚧 **Monitor metrics** in Grafana/Prometheus
7. 🚧 **Run nightly evals** for quality assurance

---

## Support

- **Documentation**: See `AGENTS.md` files in each package
- **API Reference**: http://localhost:8000/docs (when API running)
- **Troubleshooting**: See section 6 above
- **Issues**: Check logs in `apps/api/server.log`

---

**Last Updated**: Phase 4 - MongoDB Indexes & Testing Setup
**Status**: Ready for testing
**Next Phase**: Memory enhancements (PII vault, TTL, auto-summary)
