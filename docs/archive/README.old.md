# Agent Builder Platform

A production-grade AI Agent Builder Platform enabling businesses to create, deploy, and manage intelligent conversational agents with enterprise-grade RAG (Retrieval-Augmented Generation), multi-layer memory, and comprehensive observability.

---

## 🎯 Overview

The **Agent Builder Platform** is a monorepo-based system that empowers you to:
- **Build** AI agents with custom personalities, knowledge bases, and behaviors
- **Deploy** agents across multiple channels (web widgets, APIs, integrations)
- **Manage** agent configurations, document ingestion, and user interactions
- **Monitor** performance, usage, and quality through comprehensive observability

### Key Features

- 🧠 **4-Layer Memory System**: Short-term, episodic, semantic, and graph-based memory
- 🔍 **Hybrid Retrieval**: Vector search (MongoDB Atlas) + BM25 + RRF fusion + cross-encoder reranking
- 🔐 **Enterprise Security**: JWT authentication, API keys, RBAC, rate limiting, PII vaulting
- 📊 **Observability**: OpenTelemetry tracing, Prometheus metrics, structured logging
- 🎨 **Multi-Brand Support**: Isolated agent configurations per brand with custom styling
- ⚡ **High Performance**: Redis caching, connection pooling, optimized retrieval (<100ms target)
- 🔌 **Pluggable LLMs**: Support for OpenAI, Qwen, Gemini, LLaMA, Anthropic Claude

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent Builder Platform                  │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐    │
│  │    Widget    │   │     API      │   │    Admin     │    │
│  │  (React TS)  │   │  (FastAPI)   │   │  (React TS)  │    │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘    │
│         │                   │                   │             │
│         └───────────────────┴───────────────────┘             │
│                             │                                 │
│         ┌───────────────────┴───────────────────┐             │
│         │                                       │             │
│    ┌────▼─────┐  ┌──────────┐  ┌────────────┐  │             │
│    │ Retrieval│  │  Memory  │  │    LLM     │  │             │
│    │  Engine  │  │  System  │  │  Adapters  │  │             │
│    └────┬─────┘  └────┬─────┘  └─────┬──────┘  │             │
│         │             │              │          │             │
│    ┌────▼─────────────▼──────────────▼────┐     │             │
│    │         Storage & Caching             │     │             │
│    │  MongoDB Atlas  │  Redis  │  S3/Local│     │             │
│    └───────────────────────────────────────┘     │             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📂 Project Structure

```
agent-builder/
├── apps/
│   ├── api/                 # FastAPI backend service
│   │   ├── app/
│   │   │   ├── main.py      # Application entry point
│   │   │   ├── config.py    # Pydantic settings
│   │   │   ├── api/v1/      # API route handlers
│   │   │   ├── auth/        # Authentication (JWT, API keys, RBAC)
│   │   │   ├── services/    # Business logic
│   │   │   └── middleware.py # CORS, logging, rate limiting
│   │   └── run.py           # Server startup script
│   ├── admin/               # React admin dashboard
│   │   └── src/
│   │       ├── pages/       # Dashboard, Brands, Agents
│   │       ├── components/  # Reusable UI components
│   │       └── api/         # API client
│   └── widget/              # React widget SDK
│       └── src/
│           ├── components/  # Chat UI components
│           ├── stores/      # State management
│           └── utils/       # Page context extraction
├── packages/
│   ├── retrieval/           # Hybrid retrieval (Vector + BM25 + RRF)
│   │   └── src/retrieval/
│   │       ├── vector_search.py    # MongoDB Atlas Vector Search
│   │       ├── bm25_search.py      # BM25 keyword search
│   │       ├── fusion.py           # RRF fusion algorithm
│   │       └── reranker.py         # Cross-encoder reranking
│   ├── memory/              # 4-layer memory system
│   │   └── src/memory/
│   │       ├── short_term.py       # Rolling buffer (72h TTL)
│   │       ├── episodic.py         # User facts (90d TTL, PII vault)
│   │       ├── semantic.py         # Knowledge base
│   │       └── graph.py            # Rules and policies
│   ├── llm/                 # LLM provider adapters
│   │   └── src/llm/
│   │       ├── openai_adapter.py   # OpenAI GPT models
│   │       ├── qwen_adapter.py     # Qwen models
│   │       └── base.py             # Abstract base class
│   ├── commons/             # Shared utilities
│   │   └── src/commons/
│   │       ├── types.py            # Common data types
│   │       ├── errors.py           # Error classes
│   │       └── hashing.py          # Hashing utilities
│   ├── tracing/             # OpenTelemetry observability
│   └── cache/               # Redis caching layer (planned)
├── agents/                  # Agent YAML configurations
│   └── essco-bathware-agent.yaml
├── ingestion/               # Document ingestion pipeline
├── evals/                   # Evaluation datasets & metrics
├── infra/                   # Docker, K8s, CI/CD
└── docs/                    # Documentation
    ├── phases/              # Phase-specific docs
    ├── guides/              # User guides
    ├── api/                 # API documentation
    └── archive/             # Historical documentation
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+** (3.12.6 recommended)
- **Node.js 18+** and npm/yarn
- **MongoDB Atlas** account with Vector Search enabled
- **Redis** server (local or cloud)
- API keys for:
  - **OpenAI** or **Qwen** (LLM provider)
  - **Voyage AI** (embeddings)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd agent-builder
   ```

2. **Install dependencies**
   ```bash
   # Backend (Python)
   python3 -m pip install -r apps/api/requirements.txt
   
   # Install packages in editable mode
   pip install -e packages/commons
   pip install -e packages/retrieval
   pip install -e packages/memory
   pip install -e packages/llm
   
   # Frontend (Admin Dashboard)
   cd apps/admin
   npm install
   
   # Frontend (Widget)
   cd ../widget
   npm install
   ```

3. **Configure environment variables**
   ```bash
   # Copy example env file
   cp apps/api/.env.example apps/api/.env
   
   # Edit .env with your configuration
   nano apps/api/.env
   ```

   **Required variables:**
   ```bash
   # Core
   API_SECRET_KEY=your-256-bit-secret-key-here
   API_HOST=0.0.0.0
   API_PORT=8000
   
   # Database
   MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/agent_builder
   REDIS_URL=redis://localhost:6379/0
   
   # LLM Provider (choose one)
   MODEL_PROVIDER=openai  # or qwen
   OPENAI_API_KEY=sk-...
   # QWEN_API_KEY=sk-...
   
   # Embeddings
   EMBEDDINGS_PROVIDER=voyage
   VOYAGE_API_KEY=pa-...
   
   # Memory System (Phase 5)
   PII_ENCRYPTION_KEY=your-pii-encryption-key-32-chars
   SHORT_TERM_TTL=259200          # 72 hours
   EPISODIC_TTL=7776000           # 90 days
   CONFIDENCE_THRESHOLD=0.70      # Min confidence for fact extraction
   AUTO_SUMMARY_TURNS=4           # Turns before auto-summary
   ENABLE_AUTO_SUMMARY=true
   ENABLE_PII_VAULTING=true
   ENABLE_FACT_EXTRACTION=true
   
   # CORS
   CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:5173
   ```

4. **Run the application**
   ```bash
   # Terminal 1: Start API server
   cd apps/api
   python run.py
   # API available at http://localhost:8000
   # API docs at http://localhost:8000/docs
   
   # Terminal 2: Start Admin Dashboard
   cd apps/admin
   npm start
   # Dashboard available at http://localhost:3000
   
   # Terminal 3: Start Widget (optional)
   cd apps/widget
   npm run dev
   # Widget available at http://localhost:5173
   ```

5. **Verify installation**
   ```bash
   # Check API health
   curl http://localhost:8000/health
   
   # Expected response:
   # {"status":"healthy","timestamp":"..."}
   ```

---

## 🔧 Tech Stack

### Backend
- **FastAPI**: High-performance async API framework
- **Python 3.12.6**: Modern Python with type hints
- **Pydantic v2**: Data validation and settings management
- **MongoDB Atlas**: Vector database with Atlas Vector Search
- **Redis**: In-memory caching and rate limiting
- **Voyage AI**: High-quality embeddings (voyage-large-2-instruct)
- **OpenAI/Qwen**: LLM providers (pluggable architecture)
- **python-jose**: JWT token handling (HS256)
- **bcrypt**: Password hashing
- **httpx**: Async HTTP client

### Frontend
- **React 18**: UI framework
- **TypeScript**: Type-safe JavaScript
- **Tailwind CSS**: Utility-first styling
- **Vite**: Fast build tool and dev server
- **React Router**: Client-side routing
- **Zustand**: State management (widget)
- **Axios**: HTTP client

### Security & Auth
- **JWT**: JSON Web Tokens (30min access, 7day refresh)
- **API Keys**: SHA-256 hashed, scoped permissions
- **RBAC**: Role-based access control (admin, user, viewer)
- **Rate Limiting**: Redis-based sliding window (60 req/min)
- **PII Vaulting**: AES-256 encrypted episodic memory
- **Password Policy**: Min 8 chars, complexity requirements

### Memory System (4 Layers)
- **Short-term**: Rolling buffer, auto-summary every 4 turns, TTL 72h (Redis/Mongo)
- **Episodic**: User facts/preferences with PII vaulting, TTL 90d, confidence ≥ 0.70 (MongoDB)
- **Semantic**: Brand knowledge base (chunked + embedded), versioned by doc_id+section (MongoDB Atlas Vector)
- **Graph**: Rules, policies, escalation paths (MongoDB)

### Retrieval Pipeline
1. **Vector Search**: Voyage embeddings in MongoDB Atlas Vector Search
2. **BM25**: Traditional keyword search (Elasticsearch/Lucene compatible)
3. **RRF Fusion**: Reciprocal Rank Fusion (1/(k+rank)) → ~top 50 results
4. **Cross-encoder Reranking**: Rerank to top 12 most relevant results
5. **Boosts**: Brand-specific (manuals/FAQs/policies first), page-type boosts (SKU, FAQ)
6. **Deduplication**: MinHash on doc_id+section to remove duplicates

### Observability
- **OpenTelemetry**: Distributed tracing with spans across services
- **Prometheus**: Metrics (p95_total, cache_hit_ratio, citation_coverage, errors)
- **Structured Logging**: JSON logs with trace_id correlation and redaction
- **Health Checks**: Liveness (/health) and readiness probes
- **Dashboards**: Grafana dashboards for monitoring (planned)

---

## 📊 Current Status

**Overall Completion: 82%** 🚀

### ✅ What's Working
- ✅ **Core API**: FastAPI server with health checks and /api/v1 routes
- ✅ **Configuration**: Pydantic Settings with all Phase 5 memory fields
- ✅ **Authentication System**: JWT, API keys, RBAC fully built (1,840 lines)
- ✅ **Memory System**: All 4 layers complete (short-term, episodic, semantic, graph)
- ✅ **Retrieval Engine**: Hybrid retrieval with Vector + BM25 + RRF + reranking
- ✅ **LLM Adapters**: OpenAI and Qwen providers with streaming support
- ✅ **Document Ingestion**: Upload, chunking, embedding, indexing pipeline operational
- ✅ **Embeddings**: Voyage AI integration for vector embeddings
- ✅ **Admin UI**: Brand and agent management interfaces (UI complete)
- ✅ **Widget UI**: Chat interface components (UI complete)
- ✅ **Rate Limiting**: Redis-based with sliding window algorithm
- ✅ **Database**: MongoDB collections (users, api_keys, documents, memory)
- ✅ **Security**: Password hashing, API key hashing, permission checks

### 🚧 Critical Gaps (P0 Blockers)
- ❌ **WebSocket/SSE Streaming**: Real-time token streaming not implemented (4-6h)
  - Location: `apps/api/app/api/v1/messages.py` needs WebSocket endpoint
  - Impact: Cannot stream responses in real-time (required for chat UX)
  
- ❌ **Auth Integration**: Built but not wired into main.py routes (3-4h)
  - Location: `apps/api/app/main.py` missing auth_router inclusion
  - Impact: No authentication/authorization on API endpoints
  
- ❌ **Widget Backend Integration**: UI ready but not connected to API (6-8h)
  - Location: `apps/widget/src/` needs WebSocket client + API integration
  - Impact: Widget cannot communicate with backend
  
- ❌ **Admin Backend Integration**: UI ready but not connected to API (4-5h)
  - Location: `apps/admin/src/api/` needs proper API client implementation
  - Impact: Admin dashboard cannot manage brands/agents

**Total time to MVP: 17-23 hours**

See **[CRITICAL_GAPS_ANALYSIS.md](./CRITICAL_GAPS_ANALYSIS.md)** for comprehensive gap analysis with solutions.

---

## 📖 Documentation

### Core Documentation
- **[AGENTS.md](./AGENTS.md)**: Complete system architecture, contracts, coding standards, and AGENTS.md hierarchy
- **[PROGRESS_TRACKER.md](./PROGRESS_TRACKER.md)**: Detailed component-by-component progress tracking
- **[STATUS_SUMMARY.md](./STATUS_SUMMARY.md)**: Quick reference dashboard with visual progress bars
- **[CRITICAL_GAPS_ANALYSIS.md](./CRITICAL_GAPS_ANALYSIS.md)**: Production readiness assessment with P0/P1/P2 gaps
- **[PLAN.md](./PLAN.md)**: Development phases and roadmap
- **[QUICK_START_CARD.md](./QUICK_START_CARD.md)**: Next session quick reference

### API Documentation
- **[API_DOCUMENTATION.md](./docs/api/API_DOCUMENTATION.md)**: Complete API endpoint reference with examples
- **[Postman Collection](./docs/api/Agent_Builder_Platform.postman_collection.json)**: Ready-to-import API collection

### Phase Documentation
- [Phase 1-6 Documentation](./docs/phases/) - Detailed phase-by-phase implementation
  - Phase 5: Memory Systems (100% complete)
  - Phase 6: Authentication (75% complete - built, not integrated)

### Guides
- [Production Ready Guide](./docs/guides/PRODUCTION_READY.md)
- [Quick Start Guide](./docs/guides/QUICK_START.md)
- [Phase 6 Quick Start](./docs/guides/PHASE6_QUICKSTART.md)

---

## 🛠️ Development

### Running the API Server
```bash
cd apps/api

# Standard run
python run.py

# With uvicorn directly (auto-reload)
uvicorn app.main:app --reload --port 8000

# View logs
tail -f server.log

# View API documentation
open http://localhost:8000/docs
```

### Running Tests
```bash
# Unit tests
pytest apps/api/tests/ -v

# Integration tests
pytest apps/api/tests/integration/ -v

# Coverage report
pytest --cov=app --cov-report=html --cov-report=term

# Open coverage report
open htmlcov/index.html
```

### Running Admin Dashboard
```bash
cd apps/admin

# Development mode
npm start
# Available at http://localhost:3000

# Production build
npm run build
npm install -g serve
serve -s build -p 3000
```

### Running Widget
```bash
cd apps/widget

# Development mode
npm run dev
# Available at http://localhost:5173

# Production build
npm run build
npm run preview
```

### Code Style

**Python:**
- **Formatter**: Black (line length 100)
- **Import sorting**: isort
- **Linting**: flake8
- **Type checking**: mypy (planned)
```bash
# Format code
black apps/api/app packages/

# Sort imports
isort apps/api/app packages/

# Lint
flake8 apps/api/app packages/
```

**TypeScript:**
- **Linter**: ESLint
- **Formatter**: Prettier
- **Config**: .eslintrc, .prettierrc
```bash
# Lint
npm run lint

# Format
npm run format
```

**Commits:**
- Follow **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Example: `feat: add WebSocket streaming support for messages`

---

## 🎯 Roadmap & Time Estimates

### Phase 6 (Current - 75% Complete)
- ✅ Build authentication system (JWT, API keys, RBAC) - **DONE**
- 🚧 Integrate auth into API routes - **3-4 hours**
- 🚧 Implement WebSocket/SSE streaming - **4-6 hours**
- 🚧 Connect Widget to backend - **6-8 hours**
- 🚧 Connect Admin Dashboard to backend - **4-5 hours**

**Phase 6 Completion: 17-23 hours** → **MVP Ready**

### Phase 7 (Planned - P1 Critical)
- Deployment infrastructure (Docker, K8s, Helm charts) - **15-20 hours**
- Monitoring dashboards (Grafana, Prometheus, alerts) - **10-12 hours**
- Content filtering and safety guardrails - **6-10 hours**
- Authentication integration tests - **4-6 hours**
- Secrets management (Vault, K8s secrets) - **2-3 hours**

**Phase 7 Total: 31-42 hours** → **Production Beta Ready**

### Phase 8 (Planned - P2 Important)
- Comprehensive unit tests (retrieval, memory, LLM) - **15-20 hours**
- Evaluation harness with datasets (recall@k, nDCG) - **10-12 hours**
- Error handling improvements - **5-7 hours**
- Performance optimization - **8-10 hours**
- Documentation completion - **5-8 hours**

**Phase 8 Total: 30-39 hours** → **Enterprise Ready**

### Timeline Summary
- **MVP (P0 blockers)**: 17-23 hours
- **Production Beta (P0 + P1)**: 48-66 hours
- **Enterprise Ready (P0 + P1 + P2)**: 78-105 hours

See **[CRITICAL_GAPS_ANALYSIS.md](./CRITICAL_GAPS_ANALYSIS.md)** for detailed breakdown and solutions.

---

## 🔐 Security

### Authentication & Authorization
- **JWT Tokens**: 30-min access tokens, 7-day refresh tokens (HS256)
- **API Keys**: SHA-256 hashed, scoped by brand and permissions
- **Roles**: admin, user, viewer with granular permissions
- **RBAC**: Role-based access control with permission checks
- **Session Management**: Refresh token rotation, logout invalidation

### Data Protection
- **PII Vaulting**: AES-256 encrypted episodic memory storage
- **Password Hashing**: bcrypt with 12 rounds
- **API Key Hashing**: SHA-256 with salt
- **Environment Variables**: Secrets never in code, use .env files
- **TLS**: HTTPS required in production (TLS 1.2+)

### Rate Limiting & Abuse Prevention
- **Rate Limits**: 60 requests/min per user/API key
- **Algorithm**: Redis-based sliding window with sorted sets
- **Headers**: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset
- **Account Lockout**: 5 failed login attempts → 15 min lockout

### Planned Security Features
- 🚧 Content filtering for harmful content
- 🚧 Input sanitization and validation
- 🚧 DDoS protection with WAF
- 🚧 Penetration testing
- 🚧 Security audit logging
- 🚧 GDPR/CCPA compliance (episodic memory deletion)

---

## 🤝 Contributing

We welcome contributions! Please follow these guidelines:

### Getting Started
1. **Fork the repository** and clone your fork
2. **Create a feature branch**: `git checkout -b feature/your-feature-name`
3. **Set up development environment** (see Quick Start)
4. **Install pre-commit hooks** (optional but recommended)

### Development Guidelines
- **Follow code style**: Black for Python, ESLint+Prettier for TypeScript
- **Write tests**: Unit tests for new features, integration tests for APIs
- **Update documentation**: 
  - Update relevant `AGENTS.md` files (root and package-specific)
  - Update API documentation if endpoints change
  - Update README if major features added
- **Add observability**: Include OpenTelemetry spans and Prometheus metrics
- **Security first**: Never commit secrets, sanitize inputs, validate data

### Commit Guidelines
- **Use Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- **Be specific**: Good: `feat: add WebSocket streaming for messages`
- **Reference issues**: `fix: resolve rate limiting bug (#123)`

### Pull Request Process
1. **Ensure all tests pass**: `pytest apps/api/tests/ -v`
2. **Update documentation**: README, AGENTS.md, API docs
3. **Write clear PR description**: What, why, how
4. **Link related issues**: Closes #123
5. **Request review**: Tag relevant maintainers
6. **Address feedback**: Make requested changes
7. **Squash commits**: Clean git history before merge

### Code Review Checklist
- [ ] Code follows style guidelines
- [ ] Tests added and passing
- [ ] Documentation updated
- [ ] No security vulnerabilities
- [ ] Observability added (spans, metrics, logs)
- [ ] Backwards compatible (or migration plan)
- [ ] Performance acceptable

---

## 📄 License

This project is proprietary software. All rights reserved.

For licensing inquiries, please contact: licensing@yourcompany.com

---

## 📞 Contact & Support

### Getting Help
- **Documentation**: Start with this README and [AGENTS.md](./AGENTS.md)
- **Issues**: [GitHub Issues](https://github.com/your-org/agent-builder/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/agent-builder/discussions)
- **Email**: support@yourcompany.com

### Community
- **Slack**: [Join our community](https://yourslack.slack.com)
- **Twitter**: [@YourCompany](https://twitter.com/yourcompany)
- **Blog**: [blog.yourcompany.com](https://blog.yourcompany.com)

### Enterprise Support
For enterprise support, SLAs, and custom development:
- **Sales**: sales@yourcompany.com
- **Enterprise Support**: enterprise@yourcompany.com

---

## 🙏 Acknowledgments

Built with amazing open-source tools:
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [React](https://react.dev/) - UI library
- [MongoDB Atlas](https://www.mongodb.com/atlas) - Vector database with Atlas Vector Search
- [Redis](https://redis.io/) - In-memory data store
- [OpenAI](https://openai.com/) - GPT models
- [Voyage AI](https://www.voyageai.com/) - High-quality embeddings
- [Tailwind CSS](https://tailwindcss.com/) - Utility-first CSS
- [Vite](https://vitejs.dev/) - Fast build tool
- [Pydantic](https://pydantic-docs.helpmanual.io/) - Data validation

Special thanks to the open-source community for making this possible! 🙌

---

**Current Version:** 0.8.2 (82% Complete)  
**Last Updated:** January 2025  
**Status:** Active Development 🚀  
**Next Milestone:** MVP (17-23 hours remaining)
