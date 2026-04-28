# Hybrid RAG Workflow - Complete Implementation Guide

This document describes the **actual implementation** of the Hybrid Retrieval-Augmented Generation (RAG) workflow in the Agent Builder platform, from user query to final answer.

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture Components](#architecture-components)
3. [Complete Workflow](#complete-workflow)
4. [Step-by-Step Process](#step-by-step-process)
5. [Query Intent Detection](#query-intent-detection)
6. [Vector Search (Step 1a)](#vector-search-step-1a)
7. [BM25 Text Search (Step 1b)](#bm25-text-search-step-1b)
8. [RRF Fusion (Step 2)](#rrf-fusion-step-2)
9. [Cross-Encoder Reranking (Step 3)](#cross-encoder-reranking-step-3)
10. [Boost Application (Steps 4-5)](#boost-application-steps-4-5)
11. [Deduplication (Step 6)](#deduplication-step-6)
12. [Response Generation](#response-generation)
13. [Response Validation](#response-validation)
14. [Configuration](#configuration)
15. [Performance Metrics](#performance-metrics)

---

## 🎯 Overview

The Agent Builder implements a **sophisticated hybrid RAG pipeline** that combines:

- **Vector Search** (semantic similarity via Voyage embeddings + MongoDB Atlas Vector Search)
- **BM25 Text Search** (keyword matching via MongoDB text indexes)
- **Reciprocal Rank Fusion (RRF)** for combining results
- **Cross-Encoder Reranking** for precision improvement
- **Brand & Page Boosts** for context-aware ranking
- **Deduplication** for clean results
- **Response Validation** to prevent hallucinations

**File Location**: `packages/retrieval/src/retrieval/pipeline.py`

---

## 🏗️ Architecture Components

### Core Classes

```
RetrievalPipeline (pipeline.py)
├── AtlasVectorSearch (vector/atlas_search.py)
├── BM25Search (bm25/text_search.py)
├── RRFFusion (fusion/rrf.py)
├── CrossEncoderReranker (fusion/reranker.py)
├── BrandBoost (boosts/brand_boost.py)
└── PageBoost (boosts/page_boost.py)
```

### Supporting Services

```
MessageService (apps/api/app/services/message_service.py)
├── RetrievalPipeline
├── MemorySystem (Short-term, Episodic, Graph)
├── LLMProvider (OpenAI, Qwen, Gemini, etc.)
└── ResponseValidator (response_validator.py)
```

---

## 🔄 Complete Workflow

```
┌─────────────────┐
│  User Query     │ "Show me faucets under ₹5000"
└────────┬────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 0: Intent Detection & Content Type Filtering         │
│ ├─ Detect: "product_search"                               │
│ └─ Filter: content_type IN ["product", "category"]        │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 1: Parallel Search (Vector + BM25)                   │
│                                                            │
│ ┌──────────────────────┐   ┌──────────────────────┐      │
│ │ Vector Search        │   │ BM25 Text Search     │      │
│ │ ─────────────        │   │ ────────────────     │      │
│ │ 1. Generate embedding│   │ 1. MongoDB $text     │      │
│ │    (Voyage API)      │   │    search            │      │
│ │ 2. Atlas Vector      │   │ 2. Score with        │      │
│ │    Search pipeline   │   │    textScore         │      │
│ │ 3. Similarity filter │   │ 3. Sort by score     │      │
│ │    (≥ 0.7)           │   │ 4. Return top 50     │      │
│ │ 4. Return top 50     │   │                      │      │
│ └──────────────────────┘   └──────────────────────┘      │
│          │                          │                     │
│          └──────────┬───────────────┘                     │
└───────────────────┬─┘                                     │
                    │                                        
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 2: RRF Fusion                                         │
│ ├─ Combine vector + BM25 results                          │
│ ├─ Formula: RRF_score = sum(1 / (k + rank))               │
│ ├─ k = 60 (RRF constant)                                  │
│ └─ Output: ~50 fused chunks, ranked by RRF score          │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 3: Cross-Encoder Reranking                            │
│ ├─ Use Voyage Rerank API (or fallback heuristics)         │
│ ├─ Input: 50 fused chunks                                 │
│ ├─ Process: Deep semantic relevance scoring               │
│ └─ Output: Top 12 chunks (rerank_top_k)                   │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 4: Brand Boost (if enabled)                          │
│ ├─ Boost chunks from brand knowledge base                 │
│ ├─ Priority: manuals > FAQs > policies > products         │
│ └─ Adjust scores based on content_type                    │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 5: Page Context Boost (if enabled)                   │
│ ├─ Boost chunks matching page URL, SKU, or context        │
│ ├─ Extract: URL, path, SKU from page_context              │
│ └─ Higher scores for matching metadata                    │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 6: Deduplication                                      │
│ ├─ Remove duplicate chunks by (doc_id, section)           │
│ └─ Keep only first occurrence (highest ranked)            │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 7: Structured Data Enrichment                        │
│ ├─ Extract product_data from metadata                     │
│ ├─ Extract dealer_data from metadata                      │
│ └─ Populate chunk.product_data / chunk.dealer_data        │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ OUTPUT: RetrievalContext                                   │
│ ├─ chunks: List[DocumentChunk] (top 12)                   │
│ ├─ confidence: float (max chunk score)                    │
│ ├─ sources: List[str] (unique doc_ids)                    │
│ ├─ query_intent: str ("product_search")                   │
│ ├─ content_types_found: ["product"]                       │
│ └─ retrieval_metadata: {execution_time, methods, etc.}    │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 8: Memory Context Building                           │
│ ├─ Short-term: Recent conversation history                │
│ ├─ Episodic: User facts and preferences                   │
│ ├─ Graph: Safety rules and escalations                    │
│ └─ Combine with retrieval context                         │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 9: LLM Response Generation                           │
│ ├─ Build prompt with system prompt + context + history    │
│ ├─ Call LLM (OpenAI/Qwen/Gemini)                          │
│ ├─ Stream or generate full response                       │
│ └─ Extract product_info tags: <product_info>SKU</...>     │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ STEP 10: Response Validation (Anti-Hallucination)         │
│ ├─ Validate facts against catalog data                    │
│ ├─ Check product SKUs, prices, names                      │
│ ├─ Sanitize response if issues found                      │
│ └─ Calculate confidence score                             │
└────────┬───────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│ FINAL OUTPUT: MessageResponse                             │
│ ├─ message: str (validated response text)                 │
│ ├─ conversation_id: str                                   │
│ ├─ citations: List[Citation] (from retrieval)             │
│ ├─ context_used: int (chunk count)                        │
│ └─ confidence_score: float (validation confidence)        │
└────────────────────────────────────────────────────────────┘
```

---

## 📝 Step-by-Step Process

### STEP 0: Query Processing & Intent Detection

**File**: `packages/retrieval/src/retrieval/pipeline.py` → `_detect_query_intent()`

**What Happens**:
1. Normalize query to lowercase
2. Count keyword matches across categories:
   - **Product Search**: faucet, shower, sink, price, buy, etc.
   - **Dealer Search**: store, dealer, location, near, etc.
   - **FAQ**: how to, install, warranty, repair, etc.
   - **Office**: office, headquarters, contact, support, etc.
   - **Category**: types of, range, collection, browse, etc.
3. Check page_context for SKU or product page indicators
4. Return intent with highest keyword score

**Content Type Filtering**:
```python
intent_mapping = {
    "product_search": ["product", "category"],
    "dealer_search": ["dealer", "office"],
    "faq": ["faq", "guide"],
    "office": ["office"],
    "category": ["category", "product"],
    "general": None  # No filtering
}
```

**Example**:
```
Query: "Show me faucets under ₹5000"
Intent: "product_search"
Filter: metadata.content_type IN ["product", "category"]
```

---

### STEP 1a: Vector Search

**File**: `packages/retrieval/src/retrieval/vector/atlas_search.py`

**Process**:
```python
async def search(query, top_k=50, filters, similarity_threshold=0.7):
    # 1. Generate query embedding
    query_embedding = await voyage_client.embed_query(query)
    # Returns: 1024-dimensional vector
    
    # 2. Build MongoDB Atlas Vector Search pipeline
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_embedding,
                "numCandidates": 150,  # Oversample for better recall
                "limit": top_k,
                "filter": filters  # e.g., content_type IN ["product"]
            }
        },
        {
            "$project": {
                "chunk_id": 1,
                "doc_id": 1,
                "content": 1,
                "title": 1,
                "url": 1,
                "metadata": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]
    
    # 3. Execute search
    results = await collection.aggregate(pipeline).to_list(top_k)
    
    # 4. Filter by similarity threshold
    chunks = [
        result_to_chunk(r, r['score']) 
        for r in results 
        if r['score'] >= 0.7
    ]
    
    return SearchResult(chunks=chunks, search_type="vector")
```

**Key Details**:
- **Embedding Model**: Voyage AI (`voyage-3-large`)
- **Vector Dimensions**: 1024
- **Index Type**: MongoDB Atlas Vector Search (HNSW algorithm)
- **Similarity Metric**: Cosine similarity
- **Threshold**: 0.7 (configurable)
- **Top-K**: 50 candidates (configurable)

**Example Output**:
```
Vector Search Results: 45 chunks
Top chunk: score=0.92, SKU=ESS-FAU-001, "Wall-mounted bathroom faucet..."
```

---

### STEP 1b: BM25 Text Search

**File**: `packages/retrieval/src/retrieval/bm25/text_search.py`

**Process**:
```python
async def search(query, top_k=50, filters):
    # 1. Build MongoDB text search query
    search_query = {
        "$text": {"$search": query},
        **filters  # Add content_type filter
    }
    
    # 2. Project with text score
    projection = {
        "chunk_id": 1,
        "doc_id": 1,
        "content": 1,
        "title": 1,
        "metadata": 1,
        "score": {"$meta": "textScore"}
    }
    
    # 3. Execute search, sorted by text score
    results = await collection.find(
        search_query, 
        projection
    ).sort([("score", {"$meta": "textScore"})]).limit(top_k)
    
    # 4. Convert to chunks
    chunks = [result_to_chunk(r) for r in results]
    
    return SearchResult(chunks=chunks, search_type="bm25")
```

**Key Details**:
- **Algorithm**: BM25 (Best Match 25) - probabilistic ranking
- **Index Fields**: `content`, `title`, `section` (text index)
- **Tokenization**: MongoDB's default text tokenizer
- **Language**: English (default)
- **Scoring**: MongoDB's built-in `textScore`
- **Top-K**: 50 candidates (configurable)

**Example Output**:
```
BM25 Search Results: 38 chunks
Top chunk: score=8.5, SKU=ESS-FAU-002, "Faucet price range ₹3000-₹6000"
```

---

### STEP 2: RRF Fusion

**File**: `packages/retrieval/src/retrieval/fusion/rrf.py`

**Algorithm**: Reciprocal Rank Fusion

**Formula**:
```
RRF_score(chunk) = Σ [1 / (k + rank_i)]

where:
- k = 60 (RRF constant, typically 10-100)
- rank_i = rank of chunk in search result i
- Σ = sum across all search results where chunk appears
```

**Process**:
```python
def fuse(search_results: List[SearchResult], top_k=50):
    chunk_scores = defaultdict(float)
    chunk_map = {}
    
    # 1. Calculate RRF scores
    for search_result in search_results:
        for rank, chunk in enumerate(search_result.chunks, start=1):
            chunk_id = chunk.chunk_id
            
            # RRF formula
            rrf_score = 1.0 / (60 + rank)
            chunk_scores[chunk_id] += rrf_score
            
            # Store chunk object
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = chunk
    
    # 2. Sort by RRF score descending
    sorted_chunk_ids = sorted(
        chunk_scores.keys(),
        key=lambda x: chunk_scores[x],
        reverse=True
    )
    
    # 3. Create fused result with updated scores
    fused_chunks = []
    for chunk_id in sorted_chunk_ids[:top_k]:
        chunk = chunk_map[chunk_id]
        chunk.score = chunk_scores[chunk_id]
        chunk.metadata["rrf_score"] = chunk_scores[chunk_id]
        fused_chunks.append(chunk)
    
    return fused_chunks
```

**Example**:
```
Vector: Chunk A (rank 1), Chunk B (rank 5), Chunk C (rank 10)
BM25:   Chunk A (rank 3), Chunk C (rank 2), Chunk D (rank 8)

RRF Scores:
Chunk A: 1/(60+1) + 1/(60+3) = 0.0164 + 0.0159 = 0.0323
Chunk C: 1/(60+10) + 1/(60+2) = 0.0143 + 0.0161 = 0.0304
Chunk B: 1/(60+5) = 0.0154
Chunk D: 1/(60+8) = 0.0147

Final Ranking: A > C > B > D
```

**Why RRF?**
- Handles different score scales (vector vs BM25)
- Emphasizes chunks appearing in multiple results
- Rank-based, not score-based (more robust)
- No score normalization needed

---

### STEP 3: Cross-Encoder Reranking

**File**: `packages/retrieval/src/retrieval/fusion/reranker.py`

**Purpose**: Improve precision by re-scoring with a more powerful model

**Process**:
```python
async def rerank(query, chunks, top_k=12):
    # 1. Prepare documents
    documents = [chunk.content for chunk in chunks]
    
    # 2. Call Voyage Rerank API
    response = await http_client.post(
        "https://api.voyageai.com/v1/rerank",
        json={
            "query": query,
            "documents": documents,
            "model": "rerank-2.5",
            "top_k": 12
        }
    )
    
    # 3. Process results
    results = response.json()["data"]
    reranked_chunks = []
    
    for result in results:
        index = result["index"]
        score = result["relevance_score"]
        
        chunk = chunks[index]
        chunk.score = score  # Update with rerank score
        chunk.metadata["rerank_score"] = score
        reranked_chunks.append(chunk)
    
    return reranked_chunks
```

**Fallback (if API unavailable)**:
```python
async def _rerank_fallback(query, chunks, top_k):
    query_terms = set(query.lower().split())
    
    for chunk in chunks:
        # Calculate term overlap
        content_terms = set(chunk.content.lower().split())
        overlap = len(query_terms & content_terms) / len(query_terms)
        
        # Weighted combination
        combined_score = (0.7 * chunk.score) + (0.3 * overlap)
        chunk.score = combined_score
    
    # Sort and return top_k
    chunks.sort(key=lambda c: c.score, reverse=True)
    return chunks[:top_k]
```

**Key Details**:
- **Model**: Voyage Rerank-1 (cross-encoder)
- **Input**: 50 fused chunks → Output: 12 reranked chunks
- **Scoring**: Deep semantic relevance (0.0 - 1.0)
- **Fallback**: Term overlap heuristic if API fails

**Example**:
```
Input: 50 fused chunks with RRF scores
Output: 12 reranked chunks
Top chunk: rerank_score=0.95, "Essco wall-mounted faucet ₹4,500..."
```

---

### STEP 4: Brand Boost

**File**: `packages/retrieval/src/retrieval/boosts/brand_boost.py`

**Purpose**: Prioritize brand-specific content (manuals, FAQs, policies)

**Logic**:
```python
def apply_boost(chunks):
    boost_factors = {
        "manual": 1.3,      # Installation/user manuals
        "faq": 1.2,         # FAQs
        "policy": 1.15,     # Policies, warranties
        "product": 1.1,     # Product descriptions
        "category": 1.05,   # Category pages
        "dealer": 1.0,      # No boost
        "office": 1.0,      # No boost
    }
    
    for chunk in chunks:
        content_type = chunk.content_type or "general"
        boost = boost_factors.get(content_type, 1.0)
        chunk.score *= boost
        chunk.metadata["brand_boost"] = boost
    
    # Re-sort by boosted scores
    chunks.sort(key=lambda c: c.score, reverse=True)
    return chunks
```

**Example**:
```
Before boost:
1. Product (score: 0.85)
2. FAQ (score: 0.82)
3. Manual (score: 0.80)

After boost:
1. Manual (0.80 × 1.3 = 1.04)
2. Product (0.85 × 1.1 = 0.935)
3. FAQ (0.82 × 1.2 = 0.984)
```

---

### STEP 5: Page Context Boost

**File**: `packages/retrieval/src/retrieval/boosts/page_boost.py`

**Purpose**: Boost chunks relevant to current page context

**Process**:
```python
def apply_boost(chunks, page_context: PageContext):
    for chunk in chunks:
        boost = 1.0
        
        # 1. URL match
        if page_context.url and chunk.url:
            if page_context.url in chunk.url:
                boost *= 1.5
        
        # 2. SKU match
        if page_context.sku:
            chunk_sku = chunk.metadata.get("sku")
            if chunk_sku == page_context.sku:
                boost *= 2.0  # Strong boost for exact SKU match
        
        # 3. Path match
        if page_context.path and chunk.url:
            if page_context.path in chunk.url:
                boost *= 1.3
        
        # 4. Meta keywords match
        if page_context.meta_keywords:
            for keyword in page_context.meta_keywords:
                if keyword.lower() in chunk.content.lower():
                    boost *= 1.1
                    break
        
        chunk.score *= boost
        chunk.metadata["page_boost"] = boost
    
    chunks.sort(key=lambda c: c.score, reverse=True)
    return chunks
```

**Example**:
```
Page Context:
- URL: /products/faucets/ess-fau-001
- SKU: ESS-FAU-001
- Path: /products/faucets

Chunk A (SKU match): score × 2.0
Chunk B (URL match): score × 1.5
Chunk C (Path match): score × 1.3
```

---

### STEP 6: Deduplication

**File**: `packages/retrieval/src/retrieval/pipeline.py` → `_deduplicate()`

**Purpose**: Remove duplicate chunks from same document section

**Logic**:
```python
def _deduplicate(chunks):
    seen = set()
    deduplicated = []
    
    for chunk in chunks:
        # Create unique key: (doc_id, section)
        key = (chunk.doc_id, chunk.section or "")
        
        if key not in seen:
            seen.add(key)
            deduplicated.append(chunk)
        # else: skip duplicate
    
    return deduplicated
```

**Why Needed?**
- Vector and BM25 may return same chunks
- RRF fusion can't fully eliminate duplicates
- Ensures clean, non-repetitive context

**Example**:
```
Before deduplication: 12 chunks
- doc_123, section_1 (appears 2x)
- doc_456, section_2 (appears 1x)
- doc_789, section_1 (appears 3x)

After deduplication: 10 chunks (unique doc+section pairs)
```

---

### STEP 7: Structured Data Enrichment

**File**: `packages/retrieval/src/retrieval/pipeline.py` → `_enrich_with_structured_data()`

**Purpose**: Extract product/dealer data from metadata for direct access

**Process**:
```python
def _enrich_with_structured_data(chunks):
    for chunk in chunks:
        # 1. Set content_type if missing
        if not chunk.content_type and "content_type" in chunk.metadata:
            chunk.content_type = chunk.metadata["content_type"]
        
        # 2. Extract product_data for product chunks
        if chunk.content_type == "product":
            if "product_data" in chunk.metadata:
                chunk.product_data = chunk.metadata["product_data"]
                # Contains: name, sku, price, category, etc.
        
        # 3. Extract dealer_data for dealer chunks
        elif chunk.content_type == "dealer":
            if "dealer_data" in chunk.metadata:
                chunk.dealer_data = chunk.metadata["dealer_data"]
                # Contains: name, location, phone, address, etc.
    
    return chunks
```

**Product Data Structure**:
```json
{
  "name": "Essco Wall-Mounted Faucet",
  "sku": "ESS-FAU-001",
  "price": 4500,
  "category": "Faucets",
  "subcategory": "Wall-Mounted",
  "brand": "Essco Bathware",
  "url": "/products/faucets/ess-fau-001",
  "image_url": "/images/products/ess-fau-001.jpg",
  "short_description": "Premium chrome finish..."
}
```

---

## 🧠 Response Generation

**File**: `apps/api/app/services/message_service.py` → `process_message()`

### Memory Context Building

Before LLM generation, the system builds a comprehensive context:

```python
async def _build_memory_context(conversation_id, user_id, query, escalations):
    # 1. Short-term memory: Recent conversation
    recent_messages = await short_term.get_recent_messages(
        conversation_id, 
        limit=10
    )
    
    # 2. Episodic memory: User facts
    user_facts = await episodic.retrieve_facts(user_id, top_k=5)
    
    # 3. Graph memory: Rules and escalations
    rules = await graph.get_applicable_rules(query)
    
    # 4. Summaries (if conversation is long)
    summaries = await short_term.get_summaries(conversation_id)
    
    return MemoryContext(
        recent_messages=recent_messages,
        user_facts=user_facts,
        rules=rules,
        summaries=summaries,
        escalations=escalations
    )
```

### LLM Prompt Construction

```python
async def _generate_response(message, retrieval_context, memory_context, escalations):
    # 1. Build context from retrieved chunks
    context_text = "\n\n".join([
        f"[{i+1}] {chunk.title or chunk.doc_id}\n{chunk.content}"
        for i, chunk in enumerate(retrieval_context.chunks)
    ])
    
    # 2. Build conversation history
    history_text = "\n".join([
        f"{msg.role}: {msg.content}"
        for msg in memory_context.recent_messages[-5:]
    ])
    
    # 3. Build user facts
    facts_text = "\n".join([
        f"- {fact.fact_text}"
        for fact in memory_context.user_facts
    ])
    
    # 4. Construct full prompt
    prompt = f"""
{system_prompt}

## User Profile
{facts_text}

## Knowledge Base Context
{context_text}

## Conversation History
{history_text}

## Current Query
User: {message}

Instructions:
- Use the knowledge base context to provide accurate information
- For products, wrap SKUs in <product_info> tags
- Include citations to sources
- Be helpful and professional
"""
    
    # 5. Call LLM
    response = await llm_provider.generate(
        prompt=prompt,
        temperature=0.7,
        max_tokens=1000,
        stream=False
    )
    
    return response
```

---

## ✅ Response Validation

**File**: `apps/api/app/services/response_validator.py`

**Purpose**: Prevent hallucinations by validating response against catalog data

### Validation Process

```python
async def validate_response(response, query_intent, catalog_products, catalog_dealers):
    issues = []
    confidence = 1.0
    
    # 1. Extract entities from response
    entities = extract_entities(response)
    # Returns: product_skus, prices, dealer_names, locations
    
    # 2. Validate product information
    if query_intent == "product_search" and catalog_products:
        for sku in entities.product_skus:
            if sku not in [p['sku'] for p in catalog_products]:
                issues.append(f"Unknown product SKU: {sku}")
                confidence -= 0.2
        
        for price in entities.prices:
            if not validate_price_range(price, catalog_products):
                issues.append(f"Price {price} not in catalog range")
                confidence -= 0.15
    
    # 3. Validate dealer information
    if query_intent == "dealer_search" and catalog_dealers:
        for dealer in entities.dealer_names:
            if dealer not in [d['name'] for d in catalog_dealers]:
                issues.append(f"Unknown dealer: {dealer}")
                confidence -= 0.2
    
    # 4. Sanitize response if issues found
    sanitized_response = response
    if issues:
        sanitized_response = remove_invalid_entities(response, issues)
    
    return ValidationResult(
        is_valid=(len(issues) == 0),
        confidence=max(0.0, confidence),
        issues=issues,
        sanitized_response=sanitized_response
    )
```

---

## ⚙️ Configuration

### RetrievalConfig

**File**: `packages/retrieval/src/retrieval/types.py`

```python
class RetrievalConfig:
    # Vector Search
    vector_enabled: bool = True
    vector_top_k: int = 50
    similarity_threshold: float = 0.7
    
    # BM25 Search
    bm25_enabled: bool = True
    bm25_top_k: int = 50
    
    # RRF Fusion
    rrf_k: int = 60  # RRF constant
    
    # Reranking
    rerank_enabled: bool = True
    rerank_top_k: int = 12
    
    # Boosts
    brand_boost_enabled: bool = True
    page_boost_enabled: bool = True
    
    # Deduplication
    dedup_enabled: bool = True
```

### Default Configuration

```python
# In message_service.py
retrieval_config = RetrievalConfig(
    vector_enabled=True,
    vector_top_k=50,
    similarity_threshold=0.7,
    bm25_enabled=True,
    bm25_top_k=50,
    rrf_k=60,
    rerank_enabled=True,
    rerank_top_k=12,
    brand_boost_enabled=True,
    page_boost_enabled=True,
    dedup_enabled=True
)
```

---

## 📊 Performance Metrics

### Execution Time Breakdown

Typical query execution (from logs):

```
Total: ~300-500ms
├─ Intent Detection: 5-10ms
├─ Vector Search: 80-150ms
│  └─ Embedding generation: 50-80ms
│  └─ Atlas vector search: 30-70ms
├─ BM25 Search: 20-40ms
├─ RRF Fusion: 2-5ms
├─ Reranking: 100-200ms (API call)
├─ Boosts: 1-2ms
└─ Deduplication: 1-2ms
```

### Retrieval Metadata

The system tracks detailed metrics:

```json
{
  "search_methods": ["vector", "bm25"],
  "total_candidates": 88,
  "execution_time_ms": 387,
  "reranked": true,
  "deduped": true,
  "intent_detected": "product_search",
  "content_types_requested": ["product", "category"],
  "chunks_returned": 12,
  "confidence": 0.92
}
```

---

## 🔍 Example: Complete Flow

### Query
```
"Show me wall-mounted faucets under ₹5000"
```

### Step-by-Step

**1. Intent Detection**
```
Intent: product_search
Filter: content_type IN ["product", "category"]
```

**2. Vector Search**
```
Query embedding: [0.123, 0.456, ..., 0.789] (1024 dims)
Results: 42 chunks with score ≥ 0.7
Top: ESS-FAU-001 (score: 0.91)
```

**3. BM25 Search**
```
Text query: "wall-mounted faucets under ₹5000"
Results: 35 chunks
Top: ESS-FAU-005 (score: 9.2)
```

**4. RRF Fusion**
```
Combined: 53 unique chunks
Top RRF scores:
- ESS-FAU-001: 0.0312
- ESS-FAU-005: 0.0298
- ESS-FAU-003: 0.0285
```

**5. Reranking (Top 12)**
```
Voyage Rerank API called
Results:
1. ESS-FAU-001 (rerank: 0.94)
2. ESS-FAU-003 (rerank: 0.89)
3. ESS-FAU-005 (rerank: 0.87)
...
12. ESS-CAT-002 (rerank: 0.72)
```

**6. Brand Boost**
```
ESS-FAU-001 (product): 0.94 × 1.1 = 1.034
ESS-CAT-002 (category): 0.72 × 1.05 = 0.756
```

**7. Page Boost**
```
No page_context provided, skip
```

**8. Deduplication**
```
12 chunks → 12 unique (no duplicates)
```

**9. Enrichment**
```
ESS-FAU-001: product_data populated
{
  name: "Essco Wall-Mounted Faucet",
  sku: "ESS-FAU-001",
  price: 4500,
  ...
}
```

**10. LLM Response**
```
Prompt includes:
- System: "You are Essco AI Assistant..."
- Context: 12 product chunks
- History: Recent 5 messages
- Query: "Show me wall-mounted faucets under ₹5000"

Response:
"Here are some excellent wall-mounted faucets under ₹5000:

<product_info>
- product_sku: ESS-FAU-001
- product_short_description: Premium chrome finish, single lever
</product_info>

<product_info>
- product_sku: ESS-FAU-003
- product_short_description: Brass body, wall-mounted mixer
</product_info>

..."
```

**11. Validation**
```
Extracted SKUs: ESS-FAU-001, ESS-FAU-003
Catalog check: Both SKUs exist ✓
Price check: Both under ₹5000 ✓
Confidence: 0.95
```

**12. Final Output**
```json
{
  "message": "Here are some excellent wall-mounted faucets...",
  "conversation_id": "conv-123",
  "citations": [
    {
      "title": "Essco Wall-Mounted Faucet",
      "url": "/products/ess-fau-001",
      "excerpt": "Premium chrome finish..."
    }
  ],
  "context_used": 12,
  "confidence_score": 0.95
}
```

---

## 🎯 Key Takeaways

1. **Hybrid Search**: Combines semantic (vector) + keyword (BM25) for best recall
2. **RRF Fusion**: Rank-based fusion handles different score scales elegantly
3. **Reranking**: Cross-encoder improves precision (top-k accuracy)
4. **Boosts**: Context-aware ranking (brand + page) for relevance
5. **Validation**: Anti-hallucination checks prevent false information
6. **Performance**: <500ms total latency with parallel execution
7. **Observability**: Detailed logging and metrics at each step

---

## 📚 Related Documentation

- [AGENTS.md](../AGENTS.md) - Agent configuration and management
- [packages/retrieval/](../packages/retrieval/) - Source code

---

**Last Updated**: November 11, 2025  
**Version**: 1.0.0  
**Status**: Production Implementation
