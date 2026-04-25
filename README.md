# 🤖 Agent Builder Platform

A production-grade AI Agent Builder Platform for creating, deploying, and managing intelligent conversational agents with enterprise RAG, structured knowledge bases, and comprehensive observability.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19.1+-61DAFB?logo=react)](https://react.dev)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb)](https://www.mongodb.com/atlas)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.4+-3178C6?logo=typescript)](https://www.typescriptlang.org)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python)](https://www.python.org)

---

## 🎯 Overview

The **Agent Builder Platform** empowers businesses to create intelligent AI agents with:

- 🧠 **Structured Knowledge Management** - Upload products, dealers, FAQs, and documents with rich metadata
- 🔍 **Hybrid RAG System** - Vector search (MongoDB Atlas) + BM25 + RRF fusion + cross-encoder reranking
- 💬 **4-Layer Memory** - Short-term, episodic, semantic, and graph-based memory with PII vaulting
- 🎨 **Multi-Brand Support** - Isolated agent configurations per brand with custom styling
- 📊 **Enterprise Observability** - OpenTelemetry tracing, Prometheus metrics, structured logging
- 🔐 **Security Built-in** - JWT authentication, rate limiting, RBAC, content filtering
- ⚡ **High Performance** - Redis caching, connection pooling, <100ms retrieval target

---

## ✨ Key Features

### 📚 Structured Knowledge Base
- **6 Content Types**: Products, Dealers, FAQs, Office Locations, Categories, Guides
- **Flexible Field Mapping**: Map JSON fields, use fixed values, or skip optional fields
- **Bulk Upload**: JSON-based bulk import with auto-mapping and validation
- **Metadata-Rich**: SKU, pricing, location, contact info stored as structured data
- **Anti-Hallucination**: Grounded responses using verified knowledge base

### 🎨 Admin Dashboard
- **Visual Agent Builder**: 7-step wizard for creating agents without code
- **Brand Management**: Multi-tenant support with isolated configurations
- **Knowledge Base UI**: Upload, view, and delete documents with metadata preview
- **Real-time Monitoring**: View usage metrics, conversation logs, and performance
- **System Prompts Editor**: Customize agent personality and behavior

### 🔍 Intelligent Retrieval
- **Hybrid Search**: Combines vector similarity + keyword matching
- **RRF Fusion**: Reciprocal Rank Fusion for optimal result blending
- **Cross-Encoder Reranking**: Fine-tuned reranking for relevance
- **Content Type Boosts**: Prioritize manuals, FAQs, and product pages
- **Deduplication**: MinHash-based chunk deduplication

### 💾 Memory System
- **Short-term**: Rolling buffer with auto-summarization (72h TTL)
- **Episodic**: User facts and preferences with PII vaulting (90d TTL)
- **Semantic**: Brand knowledge base with versioning
- **Graph**: Rules, policies, and escalation logic

### 🤖 SOTA Agentic Runtime (New)
- **Orchestrator Pattern**: Plan-and-Execute loop for complex reasoning
- **Internal Reasoning**: Reasoning steps (Thought -> Plan -> Execute)
- **Tooling Layer**: Standardized tool interface (MCP-inspired)
- **Self-Correction**: Critic loop to validate and fix responses

### 🔌 LLM Support
- **OpenAI**: GPT-4, GPT-4 Turbo, GPT-3.5 Turbo
- **Qwen**: Qwen-max, Qwen-plus
- **Google**: Gemini Pro, Gemini Pro Vision
- **Meta**: LLaMA models
- **Anthropic**: Claude 3 (planned)

---

## 🏗️ Architecture

```
Browser (end user)   → apps/widget  (port 5174) ──┐
Browser (admin)      → apps/admin   (port 3000) ──┤──► apps/api (port 8000)
                                                    │         │
Agent tool calls     ─────────────────────────────┘         ├──► apps/shopify-mcp (port 3005)
                                                              ├──► MongoDB  (vector + documents)
                                                              ├──► Redis    (pub/sub, job state, sessions)
                                                              ├──► OpenAI / Qwen  (LLM)
                                                              └──► Voyage AI      (embeddings)
```

**Request flow** (chat message):
1. Widget sends message over SSE/WebSocket → API
2. API retrieves relevant docs (vector + BM25 hybrid search)
3. `agent_runtime` Orchestrator plans tool calls (retrieval, Shopify MCP, etc.)
4. Results synthesized by LLM → streamed back to Widget
5. Admin can take over any live conversation via dedicated WebSocket channel; on release, the conversation history is injected back into the agent's memory

**Multi-instance ready**: All shared state (human-control flags, job status, WebSocket fanout) lives in Redis. Run as many API replicas as needed behind a load balancer.

---

## 📂 Project Structure

```
agent-builder/
├── apps/
│   ├── api/                          # FastAPI Backend
│   │   ├── app/
│   │   │   ├── main.py               # Application entry
│   │   │   ├── config.py             # Pydantic settings
│   │   │   ├── api/v1/endpoints/     # API routes
│   │   │   │   ├── messages.py       # Chat endpoints (WebSocket/SSE)
│   │   │   │   ├── knowledge.py      # Knowledge base CRUD
│   │   │   │   ├── agents.py         # Agent management
│   │   │   │   └── auth.py           # Authentication
│   │   │   ├── services/             # Business logic
│   │   │   │   ├── knowledge_service.py   # Document ingestion
│   │   │   │   ├── message_service.py     # Chat orchestration
│   │   │   │   └── retrieval_service.py   # Hybrid retrieval
│   │   │   └── middleware.py         # CORS, logging, rate limits
│   │   ├── requirements.txt          # Python dependencies
│   │   └── run.py                    # Server startup
│   │
│   ├── admin/                        # React Admin Dashboard
│   │   ├── src/
│   │   │   ├── pages/                # Dashboard routes
│   │   │   │   ├── Agents.tsx        # Agent list & cards
│   │   │   │   ├── AgentWizard.tsx   # 7-step agent builder
│   │   │   │   ├── AgentDetail.tsx   # Agent config viewer
│   │   │   │   └── Brands.tsx        # Brand management
│   │   │   ├── components/
│   │   │   │   ├── AgentWizard/      # Wizard steps
│   │   │   │   │   ├── StepKnowledgeBase.tsx  # KB upload UI
│   │   │   │   │   └── ...
│   │   │   │   └── KnowledgeBase/    # KB components
│   │   │   │       ├── DocumentUploadWizard.tsx   # 4-step upload
│   │   │   │       ├── JsonFieldMapper.tsx        # Field mapping
│   │   │   │       ├── DocumentsList.tsx          # View/delete docs
│   │   │   │       └── ContentTypeSelector.tsx    # 6 content types
│   │   │   └── api/
│   │   │       ├── client.ts         # Axios instance
│   │   │       └── knowledge.ts      # KB API client
│   │   ├── package.json
│   │   └── tailwind.config.js
│   │
│   └── widget/                       # React Widget SDK
│       ├── src/
│       │   ├── components/           # Chat UI
│       │   ├── stores/               # Zustand state
│       │   └── utils/
│       │       └── pageContext.ts    # Page metadata extraction
│       └── package.json
│
├── packages/                         # Shared Libraries
│   ├── retrieval/                    # Hybrid Retrieval Engine
│   │   └── src/retrieval/
│   │       ├── vector/
│   │       │   ├── atlas_search.py   # MongoDB Atlas Vector Search
│   │       │   └── voyage_client.py  # Voyage AI embeddings
│   │       ├── bm25/
│   │       │   └── bm25_search.py    # Keyword search
│   │       ├── fusion.py             # RRF fusion algorithm
│   │       ├── reranker.py           # Cross-encoder reranking
│   │       └── pipeline.py           # End-to-end retrieval
│   │
│   ├── memory/                       # 4-Layer Memory System
│   │   └── src/memory/
│   │       ├── short_term.py         # Rolling buffer (72h)
│   │       ├── episodic.py           # User facts (90d, PII vault)
│   │       ├── semantic.py           # Knowledge base
│   │       └── graph.py              # Rules & policies
│   │
│   ├── llm/                          # LLM Provider Adapters
│   │   └── src/llm/
│   │       ├── base.py               # Abstract base class
│   │       ├── openai_adapter.py     # OpenAI GPT
│   │       ├── qwen_adapter.py       # Qwen models
│   │       └── factory.py            # Provider factory
│   │
│   ├── tools/                        # Agent Tools (MCP Standard)
│   │   └── src/tools/
│   │       ├── registry.py           # Tool registry
│   │       ├── types.py              # Base tool interfaces
│   │       └── builtin/              # Built-in tools (Retrieval, etc.)
│   │
│   ├── agent_runtime/                # SOTA Orchestrator
│   │   └── src/agent_runtime/
│   │       └── orchestrator.py       # Plan-Execute-Review loop
│   │
│   └── commons/                      # Shared Utilities
│       └── src/commons/
│           ├── types.py              # Common type definitions
│           ├── config.py             # Configuration helpers
│           └── logging.py            # Structured logging
│
├── scripts/                          # Utility Scripts
│   ├── setup_mongodb_indexes.py      # Create MongoDB indexes
│   ├── verify_vector_index.py        # Verify Atlas vector search
│   └── test_retrieval_pipeline.py    # End-to-end retrieval test
│
├── docs/                             # Documentation
│   ├── VECTOR_DATABASE_ARCHITECTURE.md
│   ├── guides/
│   └── api/
│
├── .env                              # Environment variables (gitignored)
├── README.md                         # This file
└── AGENTS.md                         # Agent system contracts
```

---

## 🚀 Deployment and local development

### Recommended deploy path: Docker Compose

Use Docker Compose as the primary deployment path. The frontend containers now read API URLs from runtime-injected config, so you can switch between local and production targets without rebuilding the admin or widget images.

### Prerequisites

- Docker + Docker Compose
- API keys for your selected providers
- MongoDB and Redis are included in Compose for the standard stack

### 1. Configure environment

Create `.env.docker` for backend secrets and runtime settings.

Required minimum values:

```env
OPENAI_API_KEY=sk-...
VOYAGE_API_KEY=pa-...
SECRET_KEY=<openssl rand -hex 32>
PII_ENCRYPTION_KEY=<base64-32-byte-key>
ADMIN_API_KEY=<openssl rand -hex 32>
SESSION_SECRET=<openssl rand -hex 32>
MONGODB_URI=mongodb://mongodb:27017
REDIS_URL=redis://redis:6379
CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:5174
ENVIRONMENT=production
DEBUG=false
ALLOW_ADMIN_KEY_BYPASS=false
REQUIRE_MONGODB=true
REQUIRE_REDIS=false
```

Optional frontend runtime overrides in your shell or Compose env:

```env
ADMIN_API_BASE_URL=http://localhost:8000
WIDGET_BASE_URL=http://localhost:5174
WIDGET_API_BASE_URL=http://localhost:8000
```

For production, point `ADMIN_API_BASE_URL` and `WIDGET_API_BASE_URL` to your public API origin, and `WIDGET_BASE_URL` to your public widget origin.

### 2. Build and start

```bash
docker compose build
docker compose up -d
```

### 3. Verify

```bash
curl http://localhost:8000/live
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/config-check
```

Open:

- Admin: http://localhost:3000
- Widget: http://localhost:5174
- API: http://localhost:8000

### Runtime switching: local vs production URLs

The admin and widget no longer depend on build-time baked API URLs in Docker deployments.

At container startup they generate `runtime-config.js` from environment variables:

- Admin uses `API_BASE_URL`
- Widget uses `API_BASE_URL`

That means you can point the same built image at different API origins just by changing container env values.

### Local non-Docker development

You can still run services directly:

```bash
cd apps/api && python run.py
cd apps/admin && npm start
cd apps/widget && npm run dev
cd apps/shopify-mcp && npm start
```

Local frontend builds still support `REACT_APP_API_URL` and `VITE_API_BASE_URL`, but Docker runtime env injection is the preferred deployment mechanism.

### Security baseline

Current deployment hardening includes:

- runtime-config separation for browser-safe values only
- admin write protection via `X-Admin-Key`
- production guardrails for `DEBUG`, wildcard CORS, and admin-key bypass
- readiness/liveness endpoints for orchestration
- baseline security headers in API and nginx-served frontends
- optional metrics endpoint controlled by config

For enterprise deployment, keep TLS termination in front of these services and set production CORS origins to exact domains only.

> **Azure Key Vault** is supported but not required. Set `USE_AZURE_KEYVAULT=true` and `AZURE_KEYVAULT_NAME` if you want to pull secrets from AKV instead.

### MongoDB Atlas Vector Index (required for RAG)

1. Atlas Console → your cluster → Search → Create Search Index
2. Database: your agent DB, Collection: `knowledge_base`, Index name: `vector_index`
3. Add vector field: `embeddings`, type `knnVector`, dimensions `1024`, similarity `cosine`
4. Optional filter fields: `agent_id`, `doc_id`, `content_type` (all `token` type)
5. Wait for "Active" status

See [`ATLAS_VECTOR_INDEX_VISUAL_GUIDE.md`](./ATLAS_VECTOR_INDEX_VISUAL_GUIDE.md) for screenshots.

---

## 🐳 Production (Docker Compose)

The full stack — API, Admin, Widget, Shopify MCP, MongoDB, Redis — in one command. No local Python, Node, MongoDB, or Redis installs needed.

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (macOS / Windows / Linux)

### 1. Create `.env.docker`

```bash
cp .env.example .env.docker
```

Fill in the required variables:

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key (`sk-...`) |
| `VOYAGE_API_KEY` | Yes | Voyage AI embeddings key (`pa-...`) |
| `SECRET_KEY` | Yes | JWT signing key — `openssl rand -hex 32` |
| `PII_ENCRYPTION_KEY` | Yes | PII vault key — `openssl rand -hex 32` |
| `ADMIN_API_KEY` | Recommended | Protects all admin write routes |
| `SESSION_SECRET` | Yes | Shopify MCP session key — `openssl rand -hex 32` |
| `SHOPIFY_WEBHOOK_SECRET` | If using webhooks | From Shopify Partner Dashboard |
| `CORS_ALLOW_ORIGINS` | Production | Your frontend domains (comma-separated) |
| `FIRECRAWL_API_KEY` | Optional | Only needed for web-scrape catalog imports |
| `STRAPI_API_TOKEN` | Optional | If using Strapi CMS integration |

> MongoDB and Redis are started as containers — leave `MONGODB_URI` and `REDIS_URL` pointing at the internal Docker hostnames (`mongodb://mongodb:27017`, `redis://redis:6379`).

### 2. Build & run

```bash
docker compose up --build
```

First build: ~3–5 minutes. Subsequent starts: instant (images cached).

### 3. Services

| Container | URL | Role |
|---|---|---|
| `agentbuilder-api` | http://localhost:8000 | FastAPI backend + Swagger at `/docs` |
| `agentbuilder-admin` | http://localhost:3000 | React admin dashboard (nginx) |
| `agentbuilder-widget` | http://localhost:5174 | Embeddable chat widget (nginx) |
| `agentbuilder-shopify` | http://localhost:3005 | Shopify MCP bridge |
| `agentbuilder-mongodb` | internal only | MongoDB 7 (no host port exposed) |
| `agentbuilder-redis` | internal only | Redis 7 (no host port exposed) |

All six containers have healthchecks. The `api` service won't start until MongoDB and Redis pass their checks.

> To connect MongoDB Compass or redis-cli locally, temporarily add `ports: ["27017:27017"]` / `ports: ["6379:6379"]` to the respective service in `docker-compose.yml` — comments in the file explain exactly where.

### 4. Useful commands

```bash
# Detached (background)
docker compose up --build -d

# Tail logs
docker compose logs -f api
docker compose logs -f admin

# Rebuild one service after a code change
docker compose up --build api

# Stop (keep data)
docker compose down

# Stop + wipe all data (fresh slate)
docker compose down -v
```

### 5. Scaling the API

The API is Redis pub/sub ready for WebSocket fanout and uses Redis-backed job state — safe to run multiple replicas. With Docker Compose:

```yaml
# docker-compose.yml
api:
  deploy:
    replicas: 3
```

In ECS/Kubernetes, point multiple task instances at the same Redis and MongoDB.

### Notes

- **Admin & Widget build args**: `REACT_APP_API_URL` and `VITE_API_BASE_URL` are baked into the nginx images at build time. If your API is behind a public domain, set them:
  ```bash
  docker compose build \
    --build-arg REACT_APP_API_URL=https://api.yourdomain.com \
    --build-arg VITE_API_BASE_URL=https://api.yourdomain.com
  ```
- **HTTPS**: Add a reverse proxy (nginx, Caddy, or an AWS ALB) in front — the containers themselves serve plain HTTP internally.
- **Strapi CMS** is a separate repository (`agentbuilder-strapi`) — not included in this Compose file. Run it independently if needed.
- Secrets are never baked into images — loaded at runtime via `env_file: .env.docker`.

---

## 📖 Usage Guide

### Creating Your First Agent

1. **Open Admin Dashboard**: http://localhost:3000
2. **Click "Create New Agent"**
3. **Follow 7-Step Wizard**:
   - **Step 1**: Basic Info (name, description, brand)
   - **Step 2**: LLM Config (provider, model, temperature)
   - **Step 3**: System Prompt (personality, tone, guidelines)
   - **Step 4**: Knowledge Base (upload documents)
   - **Step 5**: RAG Config (top-k, threshold, reranking)
   - **Step 6**: Features (WebSockets, memory, file upload)
   - **Step 7**: Review & Deploy

### Uploading Knowledge Base Documents

#### Bulk Upload (Recommended)

1. **Navigate to Agent** → Knowledge Base (Step 4)
2. **Click "Upload Document"**
3. **Select Content Type**:
   - 🛍️ **Product** - SKU, name, price, category, features
   - 🏪 **Dealer** - ID, name, city, phone, address
   - ❓ **FAQ** - Questions and answers
   - 🏢 **Office** - Locations and contact info
   - 📂 **Category** - Product categories
   - 📖 **Guide** - Installation, maintenance guides

4. **Upload/Paste JSON**:

**Example: Products**
```json
[
  {
    "sku": "FAU-001",
    "name": "Chrome Bathroom Faucet",
    "price": 299900,
    "category": "Faucets",
    "image_url": "https://example.com/faucet.jpg",
    "in_stock": true,
    "features": ["Chrome finish", "Water-saving", "Easy install"]
  },
  {
    "sku": "SHW-002",
    "name": "Rain Shower Head 8-inch",
    "price": 599900,
    "category": "Showers",
    "in_stock": true,
    "features": ["8-inch diameter", "Anti-clog nozzles", "Adjustable"]
  }
]
```

**Example: Dealers**
```json
[
  {
    "dealer_id": "DLR-001",
    "name": "Mumbai Bathware Store",
    "city": "Mumbai",
    "state": "Maharashtra",
    "phone": "+91-22-1234567",
    "email": "mumbai@bathware.com",
    "address": "123 Main Street, Andheri, Mumbai"
  }
]
```

5. **Field Mapping** (Products/Dealers only):
   - **Map from JSON**: Auto-detected field mapping
   - **Use Fixed Value**: Set constant value (e.g., currency="INR")
   - **Skip**: Optional fields can be skipped

6. **Review & Upload**: Verify data and click Upload

**See detailed guide**: [`UPLOAD_TESTING_GUIDE.md`](./UPLOAD_TESTING_GUIDE.md)

### Viewing Uploaded Documents

1. **Edit Agent** or **Create Agent** → Step 4: Knowledge Base
2. **Scroll Down** to "Uploaded Documents" section
3. **View**:
   - Document title and content type
   - Upload date and chunks count
   - Metadata preview (SKU/price for products, etc.)
   - Delete button

**See detailed guide**: [`VIEWING_AGENT_DOCUMENTS.md`](./VIEWING_AGENT_DOCUMENTS.md)

### Testing Chat

Use the built-in API docs or integrate the widget:

```bash
# Test via API
curl -X POST http://localhost:8000/api/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "your-agent-id",
    "message": "Show me chrome faucets under 5000 rupees",
    "session_id": "test-session-123"
  }'
```

Or use the Widget SDK:

```html
<!-- Add to your webpage -->
<script src="http://localhost:5173/widget.js"></script>
<script>
  AgentWidget.init({
    agentId: 'your-agent-id',
    apiUrl: 'http://localhost:8000'
  });
</script>
```

---

## 🔧 Configuration

### Agent Configuration (YAML)

Agents can be configured via YAML files in `agents/` directory:

```yaml
# agents/my-agent.yaml
metadata:
  name: "Customer Support Agent"
  brand: "my-brand"
  version: "1.0.0"

configuration:
  llm:
    provider: "openai"
    model: "gpt-4o-mini"
    temperature: 0.7
    max_tokens: 1000
  
  embedding:
    provider: "voyage"
    model: "voyage-large-2-instruct"
  
  rag:
    enabled: true
    top_k: 5
    similarity_threshold: 0.7

system_prompt: |
  You are a helpful customer support assistant.
  Use the knowledge base to provide accurate answers.
  Be professional, friendly, and solution-oriented.

features:
  websockets: true
  conversation_memory: true
  typing_indicators: true
```

### Environment Variables

**Required to start:**

| Variable | App | Description |
|---|---|---|
| `OPENAI_API_KEY` | api | OpenAI API key (`sk-...`) |
| `VOYAGE_API_KEY` | api | Voyage AI embeddings key |
| `SECRET_KEY` | api | JWT signing key (32-char random) |
| `PII_ENCRYPTION_KEY` | api | PII vault encryption key (32-char random) |
| `SESSION_SECRET` | shopify-mcp | express-session secret |
| `MONGODB_URI` | api | MongoDB connection string |
| `REDIS_URL` | api, shopify-mcp | Redis connection string |

**Recommended for production:**

| Variable | App | Description |
|---|---|---|
| `ADMIN_API_KEY` | api | Protects all admin write routes (`X-Admin-Key` header) |
| `CORS_ALLOW_ORIGINS` | api, shopify-mcp | Comma-separated allowed origins |
| `SHOPIFY_WEBHOOK_SECRET` | shopify-mcp | HMAC signing secret for webhook verification |

**Optional / feature-specific:**

| Variable | Default | Description |
|---|---|---|
| `FIRECRAWL_API_KEY` | — | Web scraping for catalog imports |
| `STRAPI_URL` | `http://localhost:1337` | Strapi CMS URL |
| `STRAPI_API_TOKEN` | — | Strapi API token |
| `SHOPIFY_SHOP_URL` | — | Shopify storefront URL |
| `SHOPIFY_CLIENT_ID` | — | Shopify OAuth app client ID |
| `SHOPIFY_CLIENT_SECRET` | — | Shopify OAuth app client secret |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM model name |
| `VOYAGE_MODEL` | `voyage-large-2-instruct` | Embeddings model |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` | Per-user rate limit |
| `ENABLE_WEBSOCKETS` | `true` | WebSocket support |
| `ENABLE_METRICS` | `true` | Prometheus metrics at `/api/v1/status/metrics` |
| `USE_AZURE_KEYVAULT` | `false` | Pull secrets from Azure Key Vault |
| `AZURE_KEYVAULT_NAME` | — | AKV name (if `USE_AZURE_KEYVAULT=true`) |

---

## 🧪 Testing

### Run API Tests

```bash
cd apps/api
pytest tests/
```

### Test Retrieval Pipeline

```bash
python scripts/test_retrieval_pipeline.py
```

### Test Vector Search

```bash
python scripts/verify_vector_index.py
```

### Test Document Ingestion

```bash
python scripts/test_document_ingestion.py
```

### Manual Testing Guides

- **Upload System**: [`UPLOAD_TESTING_GUIDE.md`](./UPLOAD_TESTING_GUIDE.md)
- **Knowledge Base**: [`QUICK_START_KNOWLEDGE_BASE.md`](./QUICK_START_KNOWLEDGE_BASE.md)
- **Field Mapping**: [`FIELD_MAPPING_TESTING_GUIDE.md`](./FIELD_MAPPING_TESTING_GUIDE.md)

---

## 📊 Key Technologies

### Backend
- **FastAPI** - Modern async Python web framework
- **Motor** - Async MongoDB driver
- **Pydantic** - Data validation and settings
- **OpenTelemetry** - Distributed tracing
- **Structlog** - Structured logging
- **Redis** - Caching and session storage

### Frontend
- **React 19** - UI library
- **TypeScript** - Type-safe JavaScript
- **TailwindCSS** - Utility-first CSS
- **Tanstack Query** - Data fetching & caching
- **React Router** - Client-side routing
- **Axios** - HTTP client

### Infrastructure
- **MongoDB Atlas** - Vector database & document store
- **Voyage AI** - Text embeddings (1024-dim)
- **Redis** - KV cache & session storage
- **OpenAI/Qwen** - LLM providers

---

## 📈 Performance

### SLOs (Service Level Objectives)

| Metric | Target | Current |
|--------|--------|---------|
| **Retrieval P95** | < 100ms | ~80ms |
| **End-to-End P95** | < 3s | ~2.5s |
| **Cache Hit Ratio** | > 70% | ~75% |
| **Citation Coverage** | > 95% | ~97% |
| **Uptime** | > 99.9% | - |

### Optimization Features

- **Redis KV Cache**: 24h TTL, <100ms retrieval
- **Connection Pooling**: MongoDB & Redis connection reuse
- **Batch Embeddings**: Process 100 docs/batch
- **RRF Fusion**: Combines vector + BM25 results
- **Cross-Encoder Reranking**: Fine-tuned relevance scoring
- **Content Type Boosts**: Prioritize authoritative sources

---

## 🔐 Security

### 1. Configure Authentication (Choose One)

**Option A: Interactive Login (Recommended for Local Dev)**
```bash
az login
```

**Option B: Service Principal (Env Variables)**
Set the following in your root `.env` file:
- `AZURE_CLIENT_ID`
- `AZURE_CLIENT_SECRET`
- `AZURE_TENANT_ID`
- **RBAC**: Role-based permissions (planned)

### Data Protection
- **PII Vaulting**: Sensitive data encryption
- **Content Filtering**: Safety guardrails
- **Rate Limiting**: 60 req/min/user
- **Input Validation**: Pydantic schemas

### Network Security
- **CORS**: Configurable origin whitelist
- **TLS/HTTPS**: Encrypted transport (production)
- **Request Size Limits**: Prevent DoS
- **WAF**: Web application firewall (production)

---

## 🛣️ Roadmap

### ✅ Completed
- [x] Admin dashboard with 7-step agent builder wizard
- [x] Structured knowledge base upload (6 content types + field mapping)
- [x] Hybrid retrieval (Vector + BM25 + RRF fusion + cross-encoder reranking)
- [x] 4-layer memory system (short-term, episodic, semantic, graph)
- [x] Multi-LLM support (OpenAI, Qwen)
- [x] WebSocket/SSE streaming with human takeover channel
- [x] MongoDB Atlas integration + Voyage AI embeddings
- [x] Shopify MCP bridge (OAuth, product/order/customer tools)
- [x] Plan-Execute-Synthesize-Critic agent orchestrator
- [x] Production hardening: Redis pub/sub WebSocket fanout, Redis-backed job state, HMAC webhook verification, auth wiring, CORS lockdown, rate limiting, Docker healthchecks

### 📋 Planned
- [ ] Batch delete / export documents
- [ ] Version history for knowledge base
- [ ] A/B testing for system prompts
- [ ] Cost tracking per agent
- [ ] Multi-modal support (images in chat)
- [ ] Anthropic Claude provider
- [ ] Fine-tuning pipeline

---

## 🤝 Contributing

We welcome contributions! Please follow these steps:

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Commit changes**: `git commit -m 'Add amazing feature'`
4. **Push to branch**: `git push origin feature/amazing-feature`
5. **Open a Pull Request**

### Development Guidelines

- Follow existing code style (Black for Python, Prettier for TypeScript)
- Add tests for new features
- Update documentation
- Ensure all tests pass: `pytest` and `npm test`
- Update `AGENTS.md` for behavior changes

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Voyage AI** - Excellent embedding models
- **MongoDB Atlas** - Powerful vector search
- **FastAPI** - Amazing Python web framework
- **React Team** - Modern UI library
- **OpenAI** - GPT models and inspiration

---

## 📞 Support

- **Documentation**: See `docs/` directory
- **Issues**: [GitHub Issues](https://github.com/yourusername/agent-builder/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/agent-builder/discussions)

---

## 📚 Additional Resources

### Documentation
- [`AGENTS.md`](./AGENTS.md) - Agent system architecture & contracts
- [`ATLAS_VECTOR_INDEX_VISUAL_GUIDE.md`](./ATLAS_VECTOR_INDEX_VISUAL_GUIDE.md) - MongoDB vector search setup
- [`UPLOAD_TESTING_GUIDE.md`](./UPLOAD_TESTING_GUIDE.md) - Knowledge base upload guide
- [`VIEWING_AGENT_DOCUMENTS.md`](./VIEWING_AGENT_DOCUMENTS.md) - Viewing uploaded documents
- [`docs/VECTOR_DATABASE_ARCHITECTURE.md`](./docs/VECTOR_DATABASE_ARCHITECTURE.md) - Vector DB deep dive

### Guides
- [`QUICK_START_KNOWLEDGE_BASE.md`](./QUICK_START_KNOWLEDGE_BASE.md) - Quick start guide
- [`FIELD_MAPPING_TESTING_GUIDE.md`](./FIELD_MAPPING_TESTING_GUIDE.md) - Field mapping reference
- [`FLEXIBLE_FIELD_MAPPING_COMPLETE.md`](./FLEXIBLE_FIELD_MAPPING_COMPLETE.md) - Field mapping features

### Status Reports
- [`UPLOAD_SYSTEM_COMPLETE.md`](./UPLOAD_SYSTEM_COMPLETE.md) - Upload system status
- [`KNOWLEDGE_BASE_SINGLE_FLOW_COMPLETE.md`](./KNOWLEDGE_BASE_SINGLE_FLOW_COMPLETE.md) - Unified flow documentation
- [`PLATFORM_READY.md`](./PLATFORM_READY.md) - Platform readiness checklist

---

**Built with ❤️ for creating intelligent, grounded AI agents**

---

## 🏁 Getting Started Checklist

- [ ] Clone repository
- [ ] Set up `.env` file with API keys
- [ ] Create MongoDB Atlas cluster
- [ ] Create vector search index (`vector_index`)
- [ ] Install Python dependencies
- [ ] Install Node.js dependencies
- [ ] Start API server (port 8000)
- [ ] Start Admin dashboard (port 3000)
- [ ] Create your first agent
- [ ] Upload knowledge base documents
- [ ] Test chat functionality
- [ ] Review documentation

**Happy Building! 🚀**
