# Agent Builder Platform - Implementation Plan

> **Last Updated:** August 28, 2025  
> **Status:** Phase 6 In Progress - Frontend Widget Development  
> **Architecture Review:** ✅ Complete

---

## 🎯 Progress Tracker

| Phase | Status | Completion Date | Notes |
|-------|--------|----------------|-------|
| **Phase 1** | ✅ Complete | Aug 25, 2025 | Commons package operational |
| **Phase 2** | ✅ Complete | Aug 25, 2025 | 4-layer memory system ready |
| **Phase 3** | ✅ Complete | Aug 27, 2025 | Retrieval engine operational |
| **Phase 4** | ✅ Complete | Aug 27, 2025 | Multi-LLM support ready |
| **Phase 5** | ✅ Complete | Aug 28, 2025 | FastAPI backend operational |
| **Phase 6** | 🔄 In Progress | Aug 28, 2025 | Frontend widget active |
| **Phase 7** | ⏳ Pending | TBD | Production deployment |

---

## 📋 Executive Summary

This is a comprehensive implementation plan for the Agent Builder Platform - a context-aware RAG assistant framework focused on brand-safe, citation-first answers with minimal hallucinations and fast streaming responses.

### Core Objectives
- **Citation Coverage:** 100% (No source → No answer)
- **Factuality:** ≥ 0.9 
- **P95 Latency:** ≤ 3s
- **Cache Hit Ratio:** ≥ 50%
- **Model Agnostic:** Support Qwen, Gemini, LLaMA, OpenAI, Claude

---

## 🏗️ Implementation Phases

### Phase 1: Core Infrastructure (Foundation)
**Timeline:** Week 1  
**Priority:** Critical Path

#### 1.1 Commons Package (`packages/commons/`)
- **Types & Schemas:** Pydantic models for all contracts
- **Error Handling:** Standardized exceptions and error responses  
- **Configuration:** Environment management and validation
- **Utilities:** Shared helpers and constants

**Deliverables:**
```
packages/commons/
├── AGENTS.md
├── pyproject.toml
├── src/commons/
│   ├── types/
│   │   ├── __init__.py
│   │   ├── requests.py      # Message, Context, Agent schemas
│   │   ├── responses.py     # LLM output, Citation, Safety schemas
│   │   └── memory.py        # Memory layer types
│   ├── errors/
│   │   ├── __init__.py
│   │   └── exceptions.py    # Custom exceptions
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py      # Environment variables
│   └── utils/
│       ├── __init__.py
│       ├── hashing.py       # Cache key generation
│       └── validation.py    # Schema validators
└── tests/
```

#### 1.2 Tracing Package (`packages/tracing/`)
- **OpenTelemetry:** Span creation and context propagation
- **Prometheus Metrics:** Custom metrics for SLOs
- **Observability:** Request tracing across all components

#### 1.3 Cache Package (`packages/cache/`)
- **Redis Integration:** KV store with <100ms retrieval
- **Key Strategy:** SHA256 salted keys with agent_id + query + page_fp
- **TTL Management:** 24h expiration with LRU eviction

#### 1.4 Basic API Structure (`apps/api/`)
- **FastAPI Setup:** Health endpoint and middleware
- **CORS Configuration:** Environment-based origins
- **Request/Response Models:** Schema validation

---

### Phase 2: Memory & Storage
**Timeline:** Week 2  
**Dependencies:** Phase 1 complete

#### 2.1 Memory Package (`packages/memory/`)
**Short-Term Memory:**
- Rolling buffer with auto-summary every 4 turns
- TTL: 72 hours
- Context window management

**Episodic Memory:**
- User facts/preferences storage
- PII vaulting and redaction
- TTL: 90 days
- Confidence threshold: ≥ 0.70

**Semantic Memory:**
- Brand KB chunking and versioning
- Document ID + section tracking
- Metadata preservation

**Graph Memory:**
- Rules and policies storage
- Escalation logic

#### 2.2 MongoDB Atlas Integration
- **Vector Search Setup:** Index configuration for Voyage embeddings
- **Collection Design:** Documents, chunks, metadata structure
- **Connection Management:** Pool configuration and health checks

**✅ Phase 2 Complete - August 25, 2025**

> **🎉 Deliverables Achieved:**
> - ✅ **Memory Package:** 4-layer memory system operational
> - ✅ **Short-term Memory:** 72h TTL conversation buffer with Redis
> - ✅ **Episodic Memory:** User facts with PII detection (90d TTL, ≥0.7 confidence)
> - ✅ **Semantic Memory:** Knowledge chunks with vector embeddings
> - ✅ **Graph Memory:** Rules and policies storage
> - ✅ **Content Processing:** PII detection, entity extraction, validation
> - ✅ **Storage Adapters:** MongoDB and Redis with connection pooling
> - ✅ **Testing:** Full integration test passed
> 
> **📊 Test Results:**
> - Memory manager instantiation: ✅ 
> - PII detection: ✅ (email detected and redacted)
> - All 4 memory layers: ✅ Operational
> - Health checks: ✅ Passing
> - Package structure: ✅ Clean imports and dependencies
>
> **🚀 Ready for Phase 5:** FastAPI backend and API endpoints

---

### Phase 3: Retrieval Engine ✅ **COMPLETE**
**Timeline:** Week 3  
**Dependencies:** Phase 2 complete

#### 3.1 Retrieval Package (`packages/retrieval/`)
**Hybrid Search Pipeline:**
1. **Text Normalization:** Clean and prepare query
2. **Vector Search:** Voyage embeddings in MongoDB Atlas
3. **BM25 Search:** Lucene/Elastic text search
4. **RRF Fusion:** Combine results → top 50
5. **Cross-Encoder Rerank:** Refine to top 12
6. **Brand/Page Boosts:** Priority scoring
7. **Deduplication:** MinHash on doc_id+section

**Components:**
```
packages/retrieval/
├── AGENTS.md
├── src/retrieval/
│   ├── vector/
│   │   ├── voyage_client.py    # Embedding generation
│   │   └── atlas_search.py     # MongoDB vector queries
│   ├── bm25/
│   │   └── text_search.py      # BM25 implementation
│   ├── fusion/
│   │   ├── rrf.py              # Reciprocal Rank Fusion
│   │   └── reranker.py         # Cross-encoder reranking
│   ├── boosts/
│   │   ├── brand_boost.py      # Manual/FAQ/policy priority
│   │   └── page_boost.py       # SKU/page-type scoring
│   └── pipeline.py             # Main retrieval orchestrator
└── tests/
```

#### 3.2 Context Builder
- **Deterministic Assembly:** User text + page context + memories + chunks
- **Boost Tracking:** Record applied boosts in trace
- **Confidence Scoring:** Trigger refusal on low confidence
- **JSON Schema Output:** Structured context for LLM

---

### Phase 4: LLM Integration ✅ **COMPLETE**
**Timeline:** Week 4  
**Dependencies:** Phase 3 complete

#### 4.1 LLM Package (`packages/llm/`)
**Multi-Provider Support:**
- **Qwen:** Alibaba Cloud model adapter
- **Gemini:** Google AI model adapter  
- **LLaMA:** Meta model adapter
- **OpenAI:** GPT model adapter
- **Claude:** Anthropic model adapter

**Unified Interface:**
```python
class LLMProvider:
    async def generate_stream(self, context: Context) -> AsyncIterator[Token]:
        """Stream tokens with cancellation support"""
    
    async def generate(self, context: Context) -> Response:
        """Single response generation"""
    
    def validate_output(self, response: dict) -> Response:
        """Schema validation and citation enforcement"""
```

**Output Schema Enforcement:**
```json
{
  "text": "Generated response with citations",
  "citations": [
    {
      "title": "Document Title",
      "url": "https://example.com/doc",
      "excerpt": "Relevant excerpt from source"
    }
  ],
  "safety": {
    "disclaimer": "Generated response disclaimer",
    "escalation": ["urgent", "technical_support"]
  },
  "follow_up": ["Related question 1", "Related question 2"]
}
```

#### 4.2 Tools Package (`packages/tools/`)
- **Registry System:** Allowlisted tool execution
- **Typed I/O:** Schema validation for tool inputs/outputs
- **Tracing Integration:** Span creation for tool calls
- **Examples:** `render_diagram`, `unit_convert`, `ticket_create`

---

### Phase 5: API Endpoints ✅ **COMPLETE**
**Timeline:** Week 5  
**Dependencies:** Phase 4 complete

#### 5.1 Messages API (`apps/api/`)
**WebSocket Endpoint:** `/ws/v1/messages`
- Real-time bidirectional communication
- Token-level streaming
- Client cancellation support
- Connection management

**SSE Endpoint:** `/api/v1/messages/stream`
- Server-Sent Events fallback
- Same streaming behavior
- HTTP-based transport

**REST Endpoint:** `/api/v1/messages`
- Non-streaming responses
- Full response generation
- Caching optimization

**Request/Response Flow:**
1. Validate request schema
2. Extract page context
3. Generate cache key
4. Check Redis cache
5. Execute retrieval pipeline
6. Build context
7. Generate LLM response
8. Stream/return response
9. Cache result

#### 5.2 Ingestion API
**Endpoints:**
- `POST /api/v1/ingest/documents` - Upload documents
- `POST /api/v1/ingest/chunks` - Process chunks
- `GET /api/v1/ingest/status/{job_id}` - Check progress

**Pipeline:**
1. **Document Processing:** Extract text and metadata
2. **Chunking:** 300-500 tokens with 60 token overlap
3. **Embedding:** Generate Voyage embeddings
4. **Indexing:** Store in MongoDB Atlas + BM25
5. **Versioning:** Track doc_id + section versions

---

### Phase 6: Frontend Components 🔄 **IN PROGRESS**
**Timeline:** Week 6  
**Dependencies:** Phase 5 complete

#### 6.1 Widget SDK (`apps/widget/`) ✅ **ACTIVE**
**React Component Features:**
- ✅ **Page Context Extraction:** URL, title, meta extraction implemented
- ✅ **Real-time Chat:** WebSocket/SSE integration ready
- ✅ **Token Streaming:** Real-time response display setup
- ✅ **Citation Display:** Source links and excerpts ready
- ✅ **Responsive Design:** Mobile-friendly chat interface
- ✅ **Custom Styling:** Embeddable widget with branding support
- 🔄 **Testing in Progress:** Widget functionality validation
- ⏳ **Accessibility:** WCAG 2.1 AA compliance (pending)

**Bundle Requirements:**
- ✅ Small bundle size optimization
- ✅ Tree-shakeable imports
- ✅ Vite build system configured
- TypeScript definitions
- NPM package distribution

#### 6.2 Admin UI (`apps/admin/`)
**Management Interface:**
- **Agent Configuration:** YAML editor with validation
- **Document Management:** Upload, chunk, index status
- **Performance Dashboards:** SLO metrics and alerts
- **Usage Analytics:** Request patterns and costs
- **Memory Browser:** Inspect episodic and semantic memory
- **Tool Registry:** Manage allowlisted tools

---

### Phase 7: Production Readiness
**Timeline:** Week 7  
**Dependencies:** Phase 6 complete

#### 7.1 Security Implementation
**Authentication & Authorization:**
- JWT token validation per agent
- RBAC/ABAC policy enforcement
- Rate limiting: 60 requests/min/user

**Data Protection:**
- TLS everywhere (API, WebSocket, internal)
- PII redaction in logs and traces
- GDPR/CCPA compliance for memory deletion
- WAF integration for request filtering

**Input Validation:**
- Request size limits
- Schema validation on all endpoints
- SQL injection prevention
- XSS protection

#### 7.2 Evaluation Harness (`evals/`)
**Automated Testing:**
- **Retrieval Metrics:** Recall@k, Precision@k, nDCG
- **Grounding Quality:** Citation accuracy and relevance  
- **Latency Testing:** P50/P95 response times
- **Factuality Scoring:** Automated fact-checking

**Continuous Integration:**
- Nightly evaluation runs
- SLO regression detection
- Performance baselines
- Alert integration (Slack, Email, Jira)

**Datasets:**
- Golden question-answer pairs
- Citation accuracy test cases
- Edge case scenarios
- Multi-language test sets

---

## 🎯 Success Criteria & SLOs

### Primary Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| Citation Coverage | 100% | All responses must include source citations |
| Factuality Score | ≥ 0.9 | Automated evaluation against ground truth |
| P95 Latency | ≤ 3s | End-to-end response time |
| Cache Hit Ratio | ≥ 50% | Redis cache effectiveness |

### Secondary Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| Availability | 99.9% | Service uptime |
| Error Rate | <0.1% | Failed requests |
| Token Throughput | 1000+ tokens/sec | Streaming performance |
| Memory Accuracy | ≥ 0.8 | Episodic recall precision |

---

## 🛠️ Technology Stack

### Backend
- **API Framework:** FastAPI with WebSocket + SSE support
- **Language:** Python 3.11+ with async/await
- **Validation:** Pydantic v2 for schema enforcement
- **Database:** MongoDB Atlas with Vector Search
- **Cache:** Redis with sentinel for HA
- **Embeddings:** Voyage AI for semantic search
- **Observability:** OpenTelemetry + Prometheus + Grafana

### Frontend
- **Framework:** React 18 with TypeScript
- **Build Tool:** Vite for fast development
- **State Management:** React Query for server state
- **Styling:** Tailwind CSS for consistent design
- **Testing:** Jest + React Testing Library

### Infrastructure
- **Containers:** Docker with multi-stage builds
- **Orchestration:** Kubernetes with Helm charts
- **CI/CD:** GitHub Actions with automated testing
- **Monitoring:** Prometheus + Grafana + AlertManager
- **Secrets:** HashiCorp Vault or cloud native

---

## 🚧 Risk Mitigation

### Technical Risks
1. **MongoDB Atlas Performance:** Vector search at scale
   - *Mitigation:* Benchmark with production data, implement sharding
2. **LLM Provider Reliability:** Multiple model dependencies
   - *Mitigation:* Circuit breakers, fallback providers, retry logic
3. **Cache Invalidation:** Stale responses with fresh data
   - *Mitigation:* Version-based cache keys, TTL optimization

### Business Risks
1. **Citation Coverage:** Risk of no-source scenarios
   - *Mitigation:* Robust refusal templates, escalation paths
2. **Latency SLOs:** Complex retrieval pipeline
   - *Mitigation:* Progressive optimization, async processing
3. **Security Compliance:** PII handling requirements
   - *Mitigation:* Privacy by design, audit trails, automated redaction

---

## 📦 Deliverables Checklist

### Phase 1 ✅ **COMPLETE**
- [x] Commons package with types and schemas
- [x] Error handling system with HTTP status codes  
- [x] Configuration management with environment variables
- [x] Utility functions for hashing and validation
- [x] Pydantic v2 schema validation
- [x] Package installation and testing complete

### Phase 2 ✅
- [x] Memory package with all four layers
- [x] MongoDB Atlas integration
- [x] PII vaulting and redaction

### Phase 3 ✅
- [x] Retrieval package with hybrid search
- [x] Context builder with boosts
- [x] Deduplication and ranking
- [x] Vector search (Voyage + MongoDB Atlas)
- [x] BM25 text search implementation
- [x] RRF fusion and cross-encoder reranking
- [x] Brand and page boost scoring

### Phase 4 ✅
- [x] LLM package with multi-provider support
- [x] OpenAI and Qwen provider implementations
- [x] Factory pattern for provider instantiation
- [x] Environment-based model configuration

### Phase 5 ✅
- [x] Messages API with WebSocket + SSE
- [x] Ingestion API with chunking pipeline
- [x] Request/response validation
- [x] FastAPI application with async support
- [x] Health monitoring and metrics endpoints
- [x] Background job processing
- [x] Full RAG pipeline integration

### Phase 6 🔄
- [ ] Widget SDK with page context
- [ ] Admin UI with management tools
- [ ] Frontend integration testing

### Phase 7 ⏳
- [ ] Security implementation complete
- [ ] Evaluation harness operational
- [ ] Production deployment ready

---

## 🚀 Next Steps

**Phase 6 - Frontend Development:**
1. **Widget SDK:** Create embeddable chat widget with page context
2. **Admin UI:** Build management interface for configuration and monitoring
3. **Integration Testing:** End-to-end testing of complete system

**Current Status:**
- **Backend Complete:** Full FastAPI application operational at `http://localhost:8000`
- **API Endpoints:** Messages, ingestion, health, and metrics all functional
- **RAG Pipeline:** Memory, retrieval, and LLM integration working
- **Ready for Frontend:** All backend APIs documented and tested

**Development Approach:**
- Component-based frontend development
- Real-time WebSocket integration
- Responsive design for mobile compatibility
- Comprehensive testing coverage

**Backend Running:** FastAPI server operational with full RAG capabilities. Ready to begin Phase 6 frontend development.

---

*This plan follows the specifications in [`AGENTS.md`](AGENTS.md) and maintains the principle of "nearest AGENTS.md wins" for local overrides.*
