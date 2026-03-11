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
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Builder Platform                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │   Widget     │   │     API      │   │    Admin     │        │
│  │  (React TS)  │◄──┤  (FastAPI)   │──►│  (React TS)  │        │
│  │  WebSockets  │   │   Streaming  │   │  Dashboard   │        │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘        │
│         │                   │                   │                 │
│         └───────────────────┴───────────────────┘                 │
│                             │                                     │
│         ┌───────────────────┴────────────────────┐                │
│         │        Core Services                   │                │
│    ┌────▼─────┐  ┌──────────┐  ┌─────────────┐  │                │
│    │Retrieval │  │  Memory  │  │     LLM     │  │                │
│    │  Hybrid  │  │ 4-Layer  │  │  Adapters   │  │                │
│    │Vector+BM25│ │Short+Epi │  │Multi-Model  │  │                │
│    └────┬─────┘  └────┬─────┘  └─────┬───────┘  │                │
│         │             │              │           │                │
│    ┌────▼─────────────▼──────────────▼──────┐    │                │
│    │      Storage & Caching Infrastructure  │    │                │
│    │ MongoDB Atlas │ Redis │ Voyage AI      │    │                │
│    │ Vector Search │  KV   │ Embeddings     │    │                │
│    └─────────────────────────────────────────┘    │                │
└─────────────────────────────────────────────────────────────────┘
```

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

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- **MongoDB Atlas** account (free tier works)
- **Redis** (optional, for caching)
- **API Keys**:
  - Azure Key Vault access
  - Voyage AI (for embeddings)
  - OpenAI or Qwen (for LLM)
- **Azure CLI**: Logged in via `az login`

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/agent-builder.git
cd agent-builder
```

### 2. Environment Setup

The platform uses a consolidated environment management system with **Azure Key Vault** for secrets.

1. **Login to Azure**:
   ```bash
   az login
   ```

2. **Root `.env`**: Create a `.env` file in the root for non-sensitive configuration:
   ```bash
   # Azure Configuration
   USE_AZURE_KEYVAULT=true
   AZURE_KEYVAULT_NAME=kv-agentbuilder-dev

   # API Settings
   API_HOST=0.0.0.0
   API_PORT=8000
   API_LOG_LEVEL=info

   # CORS (comma-separated)
   CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:5173
   ```

3. **Sync JS Apps**: Run the sync script to generate local config for Admin/Widget (no secrets downloaded):
   ```bash
   python scripts/sync_secrets.py
   ```

### 3. MongoDB Atlas Setup

#### Create Vector Search Index

1. **Go to MongoDB Atlas Console**
2. **Navigate to**: Cluster → Database → Search
3. **Click**: Create Search Index → Visual Editor
4. **Configure**:
   - Database: `agent-builder`
   - Collection: `knowledge_base`
   - Index Name: `vector_index`
5. **Add Vector Field**:
   - Field Name: `embeddings`
   - Data Type: `knnVector`
   - Dimensions: `1024`
   - Similarity: `cosine`
6. **Add Filter Fields** (optional but recommended):
   - `agent_id` → token
   - `doc_id` → token
   - `content_type` → token
7. **Create Index** and wait for "Active" status

**See detailed guide**: [`ATLAS_VECTOR_INDEX_VISUAL_GUIDE.md`](./ATLAS_VECTOR_INDEX_VISUAL_GUIDE.md)

### 4. Install Dependencies

#### Backend (API)

```bash
cd apps/api

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install local packages in editable mode
pip install -e ../../packages/commons
pip install -e ../../packages/memory
pip install -e ../../packages/retrieval
pip install -e ../../packages/llm
```

#### Frontend (Admin Dashboard)

```bash
cd apps/admin
npm install
```

#### Widget (Optional)

```bash
cd apps/widget
npm install
```

### 5. Run Servers

#### Start API Server

```bash
cd apps/api
python run.py
# API running at http://localhost:8000
# Docs at http://localhost:8000/docs
```

#### Start Admin Dashboard

```bash
cd apps/admin
npm start
# Dashboard at http://localhost:3000
```

#### Start Widget (Optional)

```bash
cd apps/widget
npm run dev
# Widget at http://localhost:5173
```

### 6. Verify Setup

```bash
# Check API health
curl http://localhost:8000/health

# Check MongoDB connection
curl http://localhost:8000/api/v1/health/mongodb

# Verify vector search index
python scripts/verify_vector_index.py
```

---

## 🐳 Docker Quick Start

The fastest way to run the full stack — no local Python, Node, MongoDB, or Redis installs needed. One command brings up all services.

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (macOS / Windows / Linux)

### 1. Copy & fill the environment file

```bash
cp .env.docker.example .env
```

Open `.env` and fill in at minimum:

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Your OpenAI key (`sk-...`) |
| `VOYAGE_API_KEY` | Voyage AI embeddings key (`pa-...`) |
| `SECRET_KEY` | Random 32-char string (JWT signing) |
| `PII_ENCRYPTION_KEY` | Random 32-char string (PII vault) |
| `FIRECRAWL_API_KEY` | Optional — only needed for Scrape tab |

> MongoDB and Redis are started automatically as containers — leave their URLs as-is.

### 2. Build & start all services

```bash
docker compose up --build
```

First build takes ~3–5 minutes (downloads base images, installs deps). Subsequent starts are instant.

### 3. Open the apps

| Service | URL |
|---|---|
| Admin Dashboard | http://localhost:3000 |
| Chat Widget | http://localhost:5174 |
| API + Swagger docs | http://localhost:8000/docs |
| MongoDB (Compass) | mongodb://localhost:27017 |
| Redis | redis://localhost:6379 |

### What each container does

| Container | Image | Role |
|---|---|---|
| `agentbuilder-api` | Python 3.12 + FastAPI | Backend API, RAG, memory, streaming |
| `agentbuilder-admin` | Node 20 build → nginx | React admin dashboard |
| `agentbuilder-widget` | Node 20 build → nginx | React chat widget |
| `agentbuilder-mongodb` | mongo:7 | Primary database |
| `agentbuilder-redis` | redis:7-alpine | Caching & session store |

### Useful Docker commands

```bash
# Run in background (detached)
docker compose up --build -d

# View logs for a specific service
docker compose logs -f api
docker compose logs -f admin

# Stop all services (keeps data volumes)
docker compose down

# Stop and wipe all data (fresh slate)
docker compose down -v

# Rebuild a single service after code change
docker compose up --build api
```

### Notes

- **Strapi CMS** is a separate repository (`agentbuilder-strapi`) and is **not** included in this compose file. Run it independently if needed.
- The `.env` file is never baked into any image — it's mounted at runtime via `env_file` so secrets stay local.
- Data persists across restarts in named Docker volumes (`mongo_data`, `redis_data`). Use `down -v` only when you want a full reset.

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

| Variable | Location | Required | Description |
|----------|----------|----------|-------------|
| `AZURE_KEYVAULT_NAME` | Root `.env` | ✅ Yes | Name of your Azure Key Vault |
| `USE_AZURE_KEYVAULT` | Root `.env` | ✅ Yes | Set to `true` to enable AKV |
| `MONGODB_URI` | **AKV** | ✅ Yes | MongoDB Atlas connection string |
| `OPENAI_API_KEY` | **AKV** | Conditional | OpenAI API key |
| `VOYAGE_API_KEY` | **AKV** | ✅ Yes | Voyage AI API key |
| `SECRET_KEY` | **AKV** | ✅ Yes | Django-style secret key |
| `API_PORT` | Root `.env` | No | API server port (default 8000) |
| `LOG_LEVEL` | Root `.env` | No | Logging level |

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

### ✅ Completed (Phase 0-5)
- [x] Admin dashboard with agent builder
- [x] Structured knowledge base upload (6 content types)
- [x] Flexible field mapping (3 modes)
- [x] Documents list with view/delete
- [x] Hybrid retrieval (Vector + BM25 + RRF)
- [x] 4-layer memory system
- [x] Multi-LLM support (OpenAI, Qwen)
- [x] WebSocket/SSE streaming
- [x] MongoDB Atlas integration
- [x] Voyage AI embeddings

### 🚧 In Progress
- [ ] MongoDB indexes for performance
- [ ] End-to-end upload testing
- [ ] Production deployment
- [ ] Monitoring dashboards

### 📋 Planned
- [ ] Batch delete documents
- [ ] Export documents to JSON
- [ ] Version history for documents
- [ ] Advanced search/filtering
- [ ] A/B testing for prompts
- [ ] Cost tracking per agent
- [ ] Multi-modal support (images, PDFs)
- [ ] Fine-tuning pipeline
- [ ] Anthropic Claude integration

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
