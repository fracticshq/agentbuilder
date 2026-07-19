<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/nova-logo-for-dark-mode.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/nova-logo-for-light-mode.svg">
    <img alt="NOVA" src="docs/assets/nova-logo-for-light-mode.svg" width="260">
  </picture>
</p>

<h1 align="center">NOVA - Agent Builder Platform</h1>

NOVA is Fractics' context-aware conversational agent platform for building, deploying, and operating grounded AI agents across web, commerce, and support workflows.

The repository name remains `agentbuilder` for engineering purposes, but the product name is **NOVA - Agent Builder Platform**.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19.1+-61DAFB?logo=react)](https://react.dev)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb)](https://www.mongodb.com/atlas)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.4+-3178C6?logo=typescript)](https://www.typescriptlang.org)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python)](https://www.python.org)

---

## About

NOVA is a context-aware conversational agent platform by Fractics. It helps teams build grounded AI assistants with hybrid search, structured knowledge bases, memory, product catalogs, embeddable web chat, human takeover, and responsible AI observability.

---

## Overview

NOVA helps teams create reliable AI agents with:

- **Multi-agent architecture** for brand-specific and task-specific agents
- **Hybrid retrieval** using MongoDB Atlas Vector Search or local Qdrant, BM25, RRF fusion, and reranking
- **Session continuity and memory** across conversations
- **Structured knowledge bases** for products, dealers, FAQs, guides, and documents
- **Embeddable web widget** for deploying agents on external websites
- **Shopify MCP bridge** for commerce workflows
- **Human takeover** for live conversations
- **Responsible AI observability** for rate limits, guardrails, fallbacks, hallucination signals, Strapi sync health, and latency
- **Secure data handling** with JWT auth, admin API protection, rate limiting, PII handling, and production CORS controls

---

## Architecture

```text
Website visitor     -> apps/widget       -> apps/api
Admin user          -> apps/admin        -> apps/api
Shopify tools       -> apps/shopify-mcp  -> apps/api / Shopify

apps/api -> MongoDB         # documents, agents, memory, knowledge source of truth
apps/api -> Qdrant          # local/self-hosted vector search when VECTOR_BACKEND=qdrant
apps/api -> Redis           # cache, rate limits, jobs, pub/sub, live handoff
apps/api -> LLM providers   # OpenAI, Azure OpenAI, Qwen
apps/api -> Voyage AI       # embeddings
apps/api -> Strapi          # conversation/session sync, when configured
```

Core services:

| Service | Path | Default URL | Role |
|---|---|---|---|
| API | `apps/api` | http://localhost:8000 | FastAPI backend, chat runtime, retrieval, observability |
| Admin | `apps/admin` | http://localhost:3000 | NOVA dashboard for brands, agents, settings, KB, observability |
| Widget | `apps/widget` | http://localhost:5174 | Embeddable chat widget |
| Shopify MCP | `apps/shopify-mcp` | http://localhost:3005 | Shopify OAuth and MCP bridge |
| Catalog sync worker | `apps/api/app/workers/catalog_sync_worker.py` | internal | Mongo-leased Shopify full sync, delete, and uninstall lifecycle work |
| MongoDB | Compose service | internal | Agent data, knowledge, memory, source of truth |
| Qdrant | Compose-only internal service | not host-published | Local/self-hosted vector search; requires an API key |
| Redis | Compose service | internal | Rate limits, jobs, pub/sub, session state |

The API image is built from the repository root so it installs the same canonical
`packages/` source used in development and CI. There is no API-local copy of
these packages; changes belong in the root tree. The admin, widget, and Shopify
MCP services retain independent build contexts.

---

## Project Structure

```text
agentbuilder/
├── apps/
│   ├── api/             # FastAPI backend and agent runtime service
│   ├── admin/           # React admin dashboard
│   ├── widget/          # React embeddable web widget
│   └── shopify-mcp/     # Shopify MCP bridge
├── packages/
│   ├── agent_runtime/   # Agent orchestration
│   ├── commons/         # Shared types/utilities
│   ├── llm/             # LLM provider adapters
│   ├── memory/          # Memory managers and processors
│   ├── retrieval/       # Hybrid retrieval pipeline
│   └── tools/           # Tool registry and built-in tools
├── scripts/             # Operational setup/verification scripts
├── docs/                # Current architecture and production guides
├── docker-compose.yml   # Local full-stack runtime
├── AGENTS.md            # Coding-agent instructions
└── README.md            # This file
```

`packages/` is the single source of truth for shared Python packages. The legacy
`apps/api/packages/` copies are excluded from image builds and must not be used
for runtime changes.

---

## Quick Start

### 1. Configure Environment

Create `.env.docker` in the repository root.

Minimum local values:

```env
OPENAI_API_KEY=sk-...
VOYAGE_API_KEY=pa-...
VOYAGE_BASE_URL=https://api.voyageai.com/v1
SECRET_KEY=<openssl rand -hex 32>
PII_ENCRYPTION_KEY=<openssl rand -hex 32>
ADMIN_API_KEY=<openssl rand -hex 32>
SESSION_SECRET=<openssl rand -hex 32>
MCP_SERVICE_AUTH_TOKEN=<openssl rand -hex 32>
MONGODB_URI=mongodb://mongodb:27017
REDIS_URL=redis://redis:6379
VECTOR_BACKEND=qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=<openssl rand -hex 32>
CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:5174
ENVIRONMENT=production
DEBUG=false
ALLOW_ADMIN_KEY_BYPASS=false
```

Use `VOYAGE_BASE_URL=https://ai.mongodb.com/v1` when the key is a MongoDB Atlas Model API key.

Optional integrations:

```env
STRAPI_URL=http://host.docker.internal:1337
STRAPI_API_TOKEN=...
SHOPIFY_CLIENT_ID=...
SHOPIFY_CLIENT_SECRET=...
SHOPIFY_WEBHOOK_SECRET=...
FIRECRAWL_API_KEY=...
```

### 2. Build And Run

```bash
docker compose build
docker compose up -d
```

### 3. Verify

```bash
curl http://localhost:8000/live
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:3005/health
```

Open:

- Admin dashboard: http://localhost:3000
- Widget: http://localhost:5174
- API docs: http://localhost:8000/docs
- Shopify MCP service info: http://localhost:3005

---

## Local Development

Run each service directly when you want fast iteration:

```bash
cd apps/api && python run.py
cd apps/admin && npm start
cd apps/widget && npm run dev
cd apps/shopify-mcp && npm start
```

Widget runs on port `5174`.

For Docker deployments, admin and widget runtime URLs are injected through generated `runtime-config.js` files at container startup. This keeps browser-safe runtime config separate from secrets and avoids rebuilding frontend images just to change API origins.

---

## Embedding A NOVA Agent

The widget can be embedded on an external website with the generated agent snippet from the NOVA admin dashboard.

Typical shape:

```html
<script
  src="https://your-widget-domain/embed.js"
  data-agent-id="your-agent-id"
  data-api-url="https://your-api-domain"
  async
></script>
```

For local testing, use the widget service at `http://localhost:5174`.

---

## Knowledge And Retrieval

NOVA supports structured and unstructured knowledge sources:

- Products
- Dealers
- FAQs
- Office locations
- Categories
- Guides and documents

Retrieval combines:

- MongoDB Atlas Vector Search
- BM25 keyword search
- Reciprocal Rank Fusion
- Reranking
- Content-type and brand-aware boosts
- Groundedness and source-validation checks

For MongoDB Atlas Vector Search, create a vector index on the `knowledge_base` collection with:

- index name: `vector_index`
- vector field: `embeddings`
- dimensions: `1024`
- similarity: `cosine`
- useful filters: `agent_id`, `brand_id`, `brand_slug`, `doc_id`, `content_type`

---

## Responsible AI Operations

NOVA includes operational controls for enterprise-grade agents:

- Rate limiting by policy, brand, agent, IP/user, and conversation
- Guardrail tracking by action and reason
- Fallback tracking by stage and reason
- Hallucination-management signals such as groundedness and low-confidence responses
- Strapi sync health by operation and status
- Message latency by mode and status
- Low-cardinality Prometheus metrics
- Dashboard-level observability in the admin app

---

## Testing

Run service-specific tests from each app/package.

API:

```bash
cd apps/api
pytest tests/
```

Admin:

```bash
cd apps/admin
npm test
```

Widget:

```bash
cd apps/widget
npm test
```

Full container build:

```bash
docker compose build api admin widget shopify catalog-sync-worker
```

---

## Deployment Notes

Recommended Azure layout:

- API: Azure Container Apps or App Service for Containers
- Admin: Azure Static Web Apps, App Service, or containerized nginx
- Widget: Azure Static Web Apps, Storage Static Website + CDN, or containerized nginx
- Shopify MCP: separate Azure Container App or App Service for Containers
- MongoDB: MongoDB Atlas
- Local/self-hosted vector search: Qdrant
- Redis: Azure Cache for Redis
- Secrets: Azure Key Vault
- Edge/TLS: Azure Front Door or Application Gateway

For independent Azure container deployments, configure each service through Azure Container Apps/App Service environment variables or Key Vault references. Root `.env.docker` is only for local Docker Compose and should not be required by deployed service containers.

Keep Strapi deployed separately from this repository. Strapi is expected to run from the `agentbuilder-strapi` repository.

---

## Documentation

Current docs:

- [Server Startup Guide](./SERVER_STARTUP_GUIDE.md)
- [Database Setup](./docs/DATABASE_SETUP.md)
- [Production Readiness Guide](./docs/guides/PRODUCTION_READY.md)
- [Vector Database Architecture](./docs/VECTOR_DATABASE_ARCHITECTURE.md)
- [Hybrid RAG Workflow](./docs/HYBRID_RAG_WORKFLOW.md)
- [API Documentation](./docs/api/API_DOCUMENTATION.md)
- [Generated OpenAPI 3.1 Contract](./docs/api/openapi.json)
- [Generated Postman Collection](./docs/api/Agent_Builder_Platform.postman_collection.json)
- [Canonical Source and API Contract](./docs/api/P6_CANONICAL_SOURCE_AND_API_CONTRACT.md)
- [GA Release and Operations Contract](./docs/operations/GA_RELEASE_OPERATIONS.md)
- [Agent/Coding Contracts](./AGENTS.md)

---

## License And Ownership

NOVA is built and owned by Fractics ([fractics.com](https://fractics.com)).

The code is released under the [GNU Affero General Public License v3.0 or later](./LICENSE). You can self-deploy, use, study, modify, and share NOVA under the terms of the AGPL.

The NOVA and Fractics names, logos, product identity, and brand assets remain owned by Fractics. The AGPL covers the code; it does not grant trademark rights or permission to present a hosted, managed, white-label, or commercial resale offering as the official NOVA product.

For commercial hosting, managed services, white-label use, resale, or brand permissions, contact Fractics. See [TRADEMARKS.md](./TRADEMARKS.md).

---

## Contributors

- Anant Mendiratta - [LinkedIn](https://www.linkedin.com/in/anantmendiratta) · [GitHub](https://github.com/anantmendiratta)
- Nishant Jain - [LinkedIn](https://www.linkedin.com/in/nishant--jain/) · [GitHub](https://github.com/nishu3210)
- Claude Code
- Codex

---

## Product Positioning

Public product name:

**NOVA - Agent Builder Platform**

Internal engineering name:

`agentbuilder`

Suggested short description:

> NOVA is a context-aware conversational agent platform that helps brands deploy grounded AI assistants with hybrid search, memory, product catalogs, human takeover, and responsible AI observability.

---

Built by Fractics for reliable, grounded, context-aware AI agents.

<p align="center">
  <a href="https://fractics.com">
    <img alt="Built by Fractics" src="docs/assets/fractics-logo-black.png" width="180">
  </a>
</p>
