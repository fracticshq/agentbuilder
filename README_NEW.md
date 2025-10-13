# Agent Builder Platform

A comprehensive platform for building, managing, and deploying AI agents with RAG (Retrieval Augmented Generation) capabilities.

## 🚀 Quick Start

### Prerequisites
- Node.js 18+
- Python 3.9+
- MongoDB Atlas account
- OpenAI API key
- Voyage AI API key

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd agent-builder
   ```

2. **Install dependencies**
   ```bash
   # Install API dependencies
   cd apps/api
   pip install -r requirements.txt

   # Install widget dependencies (if using)
   cd ../widget
   npm install
   ```

3. **Configure environment**
   ```bash
   # Copy and configure API environment
   cd apps/api
   cp .env.example .env
   # Edit .env with your API keys
   ```

4. **Start the services**
   ```bash
   # Start API server
   cd apps/api
   uvicorn app.main:app --reload --port 8000

   # Start admin dashboard (when available)
   cd apps/admin
   npm run dev

   # Start widget (if needed)
   cd apps/widget
   npm run dev
   ```

## 🏗️ Architecture

### Current Components

- **API Server** (`apps/api/`) - FastAPI backend with RAG capabilities
- **Chat Widget** (`apps/widget/`) - Embeddable chat interface
- **Agent Configs** (`agents/`) - YAML-based agent definitions

### Planned Components

- **Admin Dashboard** (`apps/admin/`) - Web-based management interface
- **Brand Management** - Multi-tenant brand support
- **Agent Builder** - Visual agent creation and configuration

## 📱 Applications

### 1. API Server (`apps/api/`)
FastAPI backend providing:
- RESTful APIs for agent interactions
- Document ingestion and RAG pipeline
- Multi-LLM provider support (OpenAI, Qwen)
- Vector storage with MongoDB Atlas
- Real-time messaging with WebSockets

**Current Status**: ✅ Fully functional

### 2. Chat Widget (`apps/widget/`)
Embeddable React component for:
- Real-time chat interface
- File upload capabilities
- Customizable styling
- Easy integration into websites

**Current Status**: ✅ Basic implementation

### 3. Admin Dashboard (`apps/admin/`) - *Planned*
Web-based management interface for:
- **Brand Management**: Create and manage multiple brands (e.g., Essco Bathware)
- **Agent Builder**: Visual agent creation with step-by-step wizard
- **Knowledge Base**: Upload and manage documents per agent
- **System Prompts**: Rich text editor for agent personality
- **LLM Configuration**: Provider selection and API key management
- **YAML Generation**: Auto-populate agent configs from UI forms

**Current Status**: 🚧 Not implemented - planned for development

## 🎯 Current Workflow (Manual)

1. Create agent YAML file in `agents/` directory
2. Configure `.env` file with API keys
3. Upload documents via API endpoints
4. Test agent via API or widget

## 🎯 Planned Workflow (Admin Dashboard)

1. **Create Brand** → Web form with brand details
2. **Create Agent** → Wizard that auto-populates YAML template
3. **Add Knowledge** → Drag-and-drop document upload
4. **Configure Prompts** → Rich text editor for system prompts
5. **Set LLM Provider** → Dropdown with API key configuration
6. **Deploy Agent** → One-click activation and testing

## 🔧 Configuration

### Environment Variables
See `apps/api/.env` for configuration options:
- LLM provider settings (OpenAI, Qwen)
- Vector database configuration
- API keys and security settings

### Agent Configuration
Agents are defined in YAML files in the `agents/` directory. See `AGENTS.md` for detailed configuration options.

## 📚 Documentation

- `AGENTS.md` - Agent configuration and management
- `PLAN.md` - Development roadmap and current status
- `apps/api/README.md` - API documentation
- `apps/widget/README.md` - Widget integration guide

## 🛠️ Development

### API Server
```bash
cd apps/api
uvicorn app.main:app --reload --port 8000
```

### Running Tests
```bash
cd apps/api
pytest
```

## 🚀 Deployment

### Production Setup
1. Configure production environment variables
2. Set up MongoDB Atlas cluster
3. Deploy API server to cloud platform
4. Configure domain and SSL certificates

## 📞 Support

For technical support and questions:
- Create an issue in this repository
- Check the documentation in `/docs`
- Review the API documentation at `/docs` when server is running

## 🔄 Current Status

- ✅ **API Server**: Fully functional with RAG capabilities
- ✅ **Chat Widget**: Basic implementation complete
- 🚧 **Admin Dashboard**: Planned - requires development
- 🚧 **Brand Management**: Planned - requires development
- 🚧 **Visual Agent Builder**: Planned - requires development

See `PLAN.md` for detailed development roadmap.

---

## 🔑 Core Features

### Messages API (contract)

- **Endpoint:** `/api/v1/messages` (SSE/WebSocket for streaming)
- **Input:** `session_id`, `agent_id`, `text`, `constraints`, `page_context`

```json
{
  "session_id": "s_123",
  "agent_id": "glen_ai_v1",
  "text": "How to clean the baffle filter?",
  "constraints": { "language": "en-IN" },
  "page_context": {
    "url": "https://site.com/chimneys/abc",
    "path": "/chimneys/abc",
    "title": "Chimney ABC",
    "lang": "en",
    "meta": { "og_title":"...", "og_type":"product", "canonical":"...", "section":"Kitchen", "tags":["chimney","baffle"] },
    "schemaOrg": { "type":"Product", "sku":"ABC-123", "data":{ } },
    "domHints": "nearby paragraph text…"
  }
}
```

- **Output:** `response.text`, `citations[]`, `trace_id`

```json
{
  "response": {
    "text": "Step 1… Step 2…",
    "citations": [ { "title": "Manual p.12", "url": "https://…", "excerpt": "…" } ],
    "safety": { "disclaimer": "Brand guidance; follow local safety rules.", "escalation": ["sparking", "gas smell"] },
    "follow_up": ["Do you have model ABC-123?"]
  },
  "trace_id": "tr_abc123"
}
```

- **Hard rules**: If citations.length == 0 → refuse politely with next steps.

### Page-Aware Context (spatial awareness)
- Extracts: `URL`, `path`, `title`, `schema.org` (Product, FAQPage, etc.), `meta tags`, `breadcrumbs`, `lang`, `neighbbour text around widget`

- Retrieval boosts chunks matching page signals (e.g., Product SKU, FAQ page).

- Privacy: Redact query params; do not log raw DOM unless consented.

### Memory Layers

- **Short-Term:** Rolling buffer with auto-summaries (every 4 turns), TTL=72h.
- **Episodic:** Durable user preferences/facts; PII vaulted; TTL=90d; write if confidence >= 0.70.
- **Semantic:** Brand KB (chunked, embedded, indexed in vector + BM25).
- **Graph:** Safety rules, policy links, escalation graphs. 

### Hybrid Retrieval
- Semantic embeddings (Embed → vector search) + BM25 lexical + RRF fusion  
- Cross-encoder rerank (top_k=12)
- Brand-first boosting: manuals, FAQs, policies > blogs, PR.

### LLM Writer (guarded)
- Deterministic prompt; Schema-constrained outputs  
- No source → no answer; produce refusal with helpful next steps.
- Strips chain-of-thought; includes safety & troubleshooting when applicable.

### KV Cache
- Key: sha256(agent|locale|constraints|normalized_query|page_fp)
- Salted by `agent_id + query + page_fp`  
- `<100ms` retrieval path  
- TTL=24h
- Least Recently Used (LRU) cache is a cache eviction algorithm that organizes elements in order of use.

### Tools (allow-listed)

- Deterministic adapters: render_diagram, unit_convert, ticket_create, etc.
- Policy-gated in agent YAML; typed I/O; fully traced.

### Observability
- OpenTelemetry spans (intent, retrieval, rerank, generation, writebacks).
- Prometheus: p95_total, cache_hit_ratio, citation_coverage, errors. 
- Grafana dashboards
- Nightly evals: retrieval, grounding, latency; fail CI if SLOs regress.

### Security
- TLS, JWT per agent, RBAC/ABAC, WAF; rate limit 60 req/min/user.
- PII vault, log redaction; GDPR/CCPA deletions for episodic memory.
- No raw PII in prompts or logs.

---

## ⚙️ Environment Variables (API)

| Key | Default | Notes |
| -------------------- | ------- | ----------------------------------- |
| `API_LOG_LEVEL` | `info` | `debug | info | warn | error` |
| `CORS_ALLOW_ORIGINS` | `*` | tighten in prod |
| `REDIS_URL` | — | required for KV cache |
| `MONGO_URI` | — | required for MongoDB Atlas Vector Search |
| `EMBEDDINGS_PROVIDER`| `voyage`| set to `voyage` (default) |
| `MODEL_PROVIDER` | — | choose between `qwen`, `gemini`, `llama`, `openai`, `claude` |

---

## 🔧 WebSocket Support
- **Messages API** now supports both **Server-Sent Events (SSE)** and **WebSockets**.
- WebSockets enable **real-time, token-level streaming responses** and bidirectional features like cancellation and interactive tool calls.

---

## 🛠️ Extended Tech Stack

- **Frontend**: React + TypeScript (Vite)
- **API**: Python (FastAPI) with **WebSocket + SSE support**
- **Admin UI**: React + TypeScript
- **Cache**: Redis KV
- **Memory Store & Vector DB**: MongoDB Atlas (short-term, episodic, semantic KB, vector search)
- **Retrieval**: Hybrid (BM25 via Elastic/Lucene + Voyage AI embeddings + Atlas vector search + RRF fusion + reranker)
- **Models**: Pluggable (Qwen, Gemini, LLaMA, OpenAI GPTs, Claude)
- **Tracing/Monitoring**: OpenTelemetry, Prometheus, Grafana
- **Infra**: Docker, Helm (K8s), GitHub Actions for CI/CD
- **Security**: TLS, JWT per agent, RBAC/ABAC, WAF, GDPR/CCPA compliance

---

## 🔧 Agent Config (YAML Template)

```yaml
agent:
  id: "<brand>_assistant_v1"
  persona:
    voice: "Crisp, expert, friendly"
    style: "Stepwise, cited"
    languages: ["en-IN","hi-IN"]
  north_star:
    citations_required: true
    no_source_behavior: "say_dont_know"
    fast_path: ["kv_cache", "short_schema"]
  retrieval:
    provider: "pinecone"
    k: { vector: 40, bm25: 20, rerank_top_k: 12 }
    reranker: "voyage-rerank-2"
    thresholds: { min_sim: 0.70 }
    brand_boost: { sources: ["manuals","faqs","policies"], weight: 1.25 }
    fusion: "rrf"
  memory:
    short_term: { ttl_hours: 72, summarize_after_turns: 4 }
    episodic:   { ttl_days: 90, write_if_confidence_gte: 0.70, redact_pii: true }
    semantic:   { versioning: "doc_id+section", prefer_latest: true }
  kv_cache:
    key_parts: ["agent_id","locale","constraints","normalized_query","page_fp"]
    ttl_hours: 24
  page_awareness:
    boosts:
      - if: "schemaOrg.type == 'Product' && chunk.meta.sku == schemaOrg.sku" then: +2.0
      - if: "path like '/support' && chunk.meta.kind == 'faq'" then: +1.5
  tool_policies:
    allow: ["render_diagram","execute_python"]
    execute_python: { deny_network: true }
  safety:
    forbid_speculation: true
    escalation_rules: ["gas smell","visible sparking"]
  evaluation_targets:
    recall_at_12_min: 0.80
    precision_at_12_min: 0.70
    p95_total_seconds: 3.0
```

---

✅ With these enhancements, the Agent Builder remains **fast, truthful, model-agnostic, and enterprise-ready**, capable of supporting modern LLMs with **streaming, embeddings, and scalable memory layers**.
