# Agent Builder Platform

The Agent Builder is a context-aware RAG assistant framework. It powers website-embedded AI agents that are fast, page-aware, grounded in truth, and citation-first. This README is the single source of truth for AI coders and human devs to implement the system feature-by-feature with minimal ambiguity.

## 🚀 Vision & Mission

- **Vision**: Every brand has a truthful, page-aware AI assistant—expert, fast, grounded.
- **Mission**: Provide a modular system to ingest brand data, build memory layers, capture page context, and serve accurate, cited responses in <3s P95.
- **North Star**:
  - `citation_coverage = 100% (answers must cite at least one source)`
  - `factuality >= 0.9 (eval set)`
  - `P95_total_latency <= 3s`
  - `cache_hit_ratio >= 50%`
  - **Zero hallucinations**: refuse if no source.

## 🏗️ Monorepo Structure

agent-builder/
├─ apps/
│  ├─ api/            # FastAPI (or Node/Fastify) service
│  │  ├─ app/
│  │  │  ├─ routers/          # messages, tools, ingest, sessions
│  │  │  ├─ models/           # pydantic schemas
│  │  │  ├─ services/         # retrieval, context_builder, llm_writer
│  │  │  └─ __init__.py
│  │  ├─ policies/            # safety/refusal YAMLs
│  │  ├─ requirements.txt
│  │  └─ main.py
│  ├─ widget/         # Website widget (React+TS, Vite)
│  │  └─ src/         # sdk.ts, ChatWidget.tsx
│  └─ admin/          # Admin UI (agents, evals, telemetry)
├─ packages/
│  ├─ retrieval/      # hybrid search (vector+BM25) + rerank + fusion
│  ├─ memory/         # short-term, episodic, semantic, graph
│  ├─ llm/            # schema-constrained I/O, retries, guardrails
│  ├─ tools/          # registry + typed executors
│  ├─ cache/          # Redis KV + embedding cache
│  ├─ tracing/        # OpenTelemetry + Prometheus
│  └─ commons/        # types, errors, config, utils
├─ agents/            # brand blueprints (YAML)
├─ ingestion/         # pipelines, chunkers, jobs
├─ evals/             # datasets, suites, reports
├─ infra/
│  ├─ docker/         # Dockerfiles
│  ├─ helm/           # K8s charts, HPA, secrets
│  └─ github-actions/ # CI/CD workflows
└─ README.md

---

## 🔑 Core Features

### Messages API (contract)

- **Endpoint:** `/api/v1/messages` (SSE/WebSocket for streaming)
- **Input:** `session_id`, `agent_id`, `text`, `constraints`, `page_context`

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

- **Output:** `response.text`, `citations[]`, `trace_id`

{
  "response": {
    "text": "Step 1… Step 2…",
    "citations": [ { "title": "Manual p.12", "url": "https://…", "excerpt": "…" } ],
    "safety": { "disclaimer": "Brand guidance; follow local safety rules.", "escalation": ["sparking", "gas smell"] },
    "follow_up": ["Do you have model ABC-123?"]
  },
  "trace_id": "tr_abc123"
}

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

## 📦 Quickstart


### API (dev)
```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# Health: http://localhost:8000/health
```


### Widget (dev)
```bash
cd apps/widget
npm i
npm run dev
```
- Configure API base in `apps/widget/src/sdk.ts`.


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


✅ With these enhancements, the Agent Builder remains **fast, truthful, model-agnostic, and enterprise-ready**, capable of supporting modern LLMs with **streaming, embeddings, and scalable memory layers**.

---

## 🔧 Agent Config (YAML Template)

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

## 🧩 Build Order (Hand to AI Coder)

1. Messages API – I/O + schema validation + traces
2. Short-Term Memory – buffer + summarization
3. KV Cache – Redis salted keys
4. Hybrid Retrieval – fusion + rerank
5. Context Builder – page-aware boosts + deterministic YAML
6. LLM Writer – schema-locked, refusal-safe
7. Episodic Memory – PII vault, confidence gate
8. Tools – registry + allowlists
9. Ingestion – chunk → embed → index → versioning
10. Observability – traces, metrics, eval harness
11. Security – rate-limits, GDPR deletion
12. Widget SDK – page context extractor + sendMessage

## ✅ Definition of Done (per feature)

- Schemas validated; contract tests pass.
- Traces show spans & boosts; logs redacted.
- Meets SLOs (citation_coverage >= 0.95, P95 <= 3s).
- Security scans (PII linter, dep scan) pass.
- Nightly evals show no regression.

## 📊 Evaluation Harness

- Retrieval: recall@k, precision@k, nDCG
- Grounding: citation presence + overlap vs retrieved text
- Latency: P50/P95 cold vs warm; cache vs non-cache
- Alerts: SLO breach → Slack/email; auto-create Jira

## 🔐 Security & Compliance

- Transport & Storage: TLS everywhere; at-rest encryption.
- Auth/Z: JWT per agent, RBAC/ABAC, IP allowlists (admin).
- Data Handling: No raw PII in logs/prompts; PII vault; configurable retention.
- User Rights: GDPR/CCPA delete for episodic memory.
- Abuse: WAF, rate-limits, request body size limits.

## 🧪 Testing Strategy

- Unit: services (retrieval, builder, cache)
- Contract: API request/response schemas
- Integration: end-to-end message flow (mock LLM)
- Load: latency under RPS targets; HPA validation
- Security: PII redaction tests; fuzz on page_context

## 🛠️ Ingestion Pipeline (Deterministic)

- Chunking: semantic (300–500 tokens, 60 overlap), keep headings & tables.
- Embedding: latest supported model; store vector + meta{doc_id, section, url, sku, tags[]}.
- Indexing: vector + BM25; fusion = RRF; rerank = cross-encoder.
- Invalidation: re-ingest overwrites doc_id+section; bump version & indexed_at; cache keys include chunk fingerprint (SHA256).

## 🧭 Architecture Diagrams

### A. Component Map (mermaid)

flowchart TD
    subgraph Widget["Website Widget (React/TS)"]
        A1[Chat Input]
        A2[Page Context Extractor]
        A3[SendMessage SDK]
        A1 --> A3
        A2 --> A3
    end

    subgraph API["Agent Builder API"]
        B1[Messages API]
        B2[Policy Gate]
        B3[KV Cache]
        B4[Hybrid Retrieval]
        B5[Memory Layer]
        B6[Context Builder]
        B7[LLM Writer]
        B8[Tools Executor]
        B9[Tracing]
    end

    subgraph Stores["Data Stores"]
        C1[(Redis)]
        C2[(Vector DB)]
        C3[(BM25/Elastic)]
        C4[(Blob Store)]
        C5[(Episodic Vault)]
        C6[(Graph Rules)]
    end

    subgraph Admin["Ops & Admin"]
        D1[Agent YAML Configs]
        D2[Eval Harness]
        D3[Dashboards]
        D4[Security & Compliance]
    end

    Widget -->|POST /messages| API
    B1 --> B2 --> B3
    B2 --> B4
    B4 --> C2
    B4 --> C3
    B5 --> C5
    B5 --> C6
    B3 <-->|get/set| C1
    B6 --> B7 --> B8
    B9 --> D3
    D1 --> API
    D2 --> API
    D4 --> API

### B. Message Flow Sequence (mermaid)

sequenceDiagram
  participant U as User (Widget)
  participant W as Widget SDK
  participant A as API /messages
  participant C as Cache
  participant R as Retrieval
  participant M as Memories
  participant L as LLM Writer

  U->>W: type question
  W->>A: POST /messages {text, page_context}
  A->>C: cache.get(fingerprint)
  alt hit
    C-->>A: cached response
    A-->>W: response + citations
  else miss
    A->>R: hybrid search (vector+BM25)
    R-->>A: candidates
    A->>M: short-term + episodic + graph
    M-->>A: memory bundle
    A->>L: context YAML (deterministic)
    L-->>A: grounded answer + citations
    A->>C: cache.set(key, response)
    A-->>W: response + citations
  end
  W-->>U: render answer

## 🧱 Retrieval Algorithm (Exact Steps)

- Normalize user text (lowercase, strip, spell-tolerant), plus page intent terms.
- Vector Search (k=40) with cosine similarity (min_sim=0.70).
- BM25 Search (k=20) over title/body.
- RRF Fusion with 1/(k + rank); keep top ~50.
- Rerank using cross-encoder → top 12.
- Brand Boosts: multiply scores for sources in brand_boost.sources.
- Page Boosts: if Product SKU matches or page type == FAQ, apply configured boosts.
- Deduplicate by doc_id+section using MinHash.
- Return chunks with {title, url, excerpt, meta}.

## 🧩 Context Builder (Deterministic YAML)

- Inputs: user text, page_context, memories, top-k chunks, tool hints.
- Output conforms to JSON Schema; excludes PII; includes boosts_applied trace.
- Rule: If top-k < threshold or sources low-confidence → set no_source = true to trigger refusal path.

## ✍️ LLM Writer (Schema-locked)

- System prompt enforces: concise, cited, brand-safe, no speculation.
- Output must match schema:

{
  "text": "…",
  "citations": [ { "title":"...", "url":"...", "excerpt":"..." } ],
  "safety": { "disclaimer":"...", "escalation":["..."] },
  "follow_up": ["..."]
}

- If citations[] empty → respond with refusal template and helpful next steps.

## 🧰 Tools Registry (Examples)

tools:
  render_diagram:
    input_schema: { "type": "object", "properties": { "dsl": { "type":"string" } }, "required":["dsl"] }
    network: false
  unit_convert:
    input_schema: { "type": "object", "properties": { "from": {"type":"string"}, "to":{"type":"string"}, "value":{"type":"number"} }, "required":["from","to","value"] }
    network: false
  ticket_create:
    input_schema: { "type": "object", "properties": { "summary":{"type":"string"}, "priority":{"type":"string"} }, "required":["summary"] }
    network: true

## 🧯 Error Codes & Rate Limits

- 400 schema validation failed
- 401/403 auth failed / not allowed
- 409 tool conflict / busy
- 422 unsafe/unfulfillable request (policy)
- 429 rate limited (default 60 req/min/user)
- 500 unexpected server error (trace id in body)

## 🔄 Versioning & Migrations

- Use semver for agents and APIs.
- Chunk fingerprint (SHA256) drives cache invalidation.
- Ingestion overwrites doc_id+section and increments version.

## 🧭 Runbook (Incidents)

1. Check Grafana: Latency and Citation Coverage panels.
2. If citation_coverage < 0.95:
- Inspect recent ingests, index health, and retrieval errors.
- Roll back to last passing index snapshot if required.
3. If P95 > 3s:
- Inspect cache ratio; warm popular queries.
- Scale HPA on API pods and vector DB read replicas.

## $$ 👩‍💻 Contribution Guide

- Branch naming: feature/<name>
- Conventional commits: feat:, fix:, docs:
- PR checklist: tests + evals pass, security checks green
- Code style: black, mypy, ruff (Py) / eslint (TS)

## 🎯 Goals Summary

1. Minimal hallucinations – citation-first, refusal-safe
2. Fast inference – cache & slim contexts, KV cache optimized for <100ms retrieval
3. Brand-safe – safety graph + policy gate, schema constrianed
4. Enterprise-ready – observability, compliance, security built-in

## 📚 Glossary

- Citation Coverage: fraction of answers containing ≥1 source.
- RRF Fusion: Reciprocal Rank Fusion combining vector & BM25 ranks.
- Episodic Memory: user-specific facts/preferences with retention/consent.
- Page Fingerprint: hash of page context features for cache key salting.

