# AGENTS.md — Agent Operating Guide (Root)

> **Scope:** This file tells coding agents how to work inside this monorepo. Subprojects **must** ship their own `AGENTS.md`; agents always read the **nearest** one in the tree, so local rules override global rules.

---

## 1. Project Overview
This is a context‑aware RAG assistant framework for brand‑safe, citation‑first answers. Core pillars: **minimal hallucinations, fast streaming, model‑agnostic LLMs, MongoDB Atlas vector search, Voyage AI embeddings, hybrid retrieval, KV cache**, and **strict security & observability**.

### North‑Star SLOs
- `citation_coverage = 100%`
- `factuality ≥ 0.9`
- `P95 latency ≤ 3s`
- `cache_hit_ratio ≥ 50%`
- **No source → No answer** (return refusal template)

---

## 2. Build & Run (Top Level)
**Apps** live in `apps/`; shared libraries in `packages/`. Prefer local `Makefile` or `package.json` scripts where provided.

### API (FastAPI + WebSockets/SSE)
```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000  # Health: /health
```

### Widget (React + TS, Vite)
```bash
cd apps/widget
npm i
npm run dev
```

### Admin (React + TS)
```bash
cd apps/admin
npm i
npm run dev
```

---

## 3. Environment (Global)
Set in deployment or local `.env` files (never commit secrets).

| Key | Required | Example / Notes |
| --- | --- | --- |
| `API_LOG_LEVEL` | No | `debug` \| `info` \| `warn` \| `error` |
| `CORS_ALLOW_ORIGINS` | No | `*` (tighten in prod) |
| `REDIS_URL` | Yes | Redis for KV cache |
| `MONGO_URI` | Yes | MongoDB Atlas (Vector Search enabled) |
| `EMBEDDINGS_PROVIDER` | Yes | `voyage` |
| `MODEL_PROVIDER` | Yes | `qwen` \| `gemini` \| `llama` \| `openai` \| `claude` |

---

## 4. Architecture & Contracts (What to Enforce)

### Memory Layers
- **Short‑Term**: rolling buffer, auto‑summary every 4 turns, TTL 72h.
- **Episodic**: user facts/preferences; **PII vaulted**; TTL 90d; write only if `confidence ≥ 0.70`.
- **Semantic**: brand KB (chunked + embedded) — version by `doc_id+section`.
- **Graph**: rules, policies, escalation.

### Retrieval Algorithm
1) Normalize text + page‑intent terms  
2) **Vector Search** (Voyage embeddings in **MongoDB Atlas Vector Search**)  
3) **BM25** (Elastic/Lucene or equivalent)  
4) **RRF fusion** → ~top 50  
5) **Cross‑encoder rerank → top 12**  
6) **Brand/Page boosts** (manuals/FAQs/policies first; SKU/page‑type boosts)  
7) Deduplicate by `doc_id+section` (MinHash)

### Context Builder (Deterministic)
- Inputs: user text, page_context, memories, top‑k chunks, tool hints
- Output: JSON Schema; contains trace of `boosts_applied`  
- If low confidence or too few sources → set `no_source=true` (triggers refusal)

### LLM Writer (Schema‑Locked, Model‑Agnostic)
- **Providers:** Qwen, Gemini, LLaMA, OpenAI GPTs, Anthropic Claude  
- Output schema:
```json
{
  "text": "...",
  "citations": [{"title":"...","url":"...","excerpt":"..."}],
  "safety": {"disclaimer":"...","escalation":["..."]},
  "follow_up": ["..."]
}
```
- If `citations` empty → **refuse politely** with next steps.

### Streaming
- **Must support**: **WebSockets** (preferred) and **SSE**  
- Behavior: token‑level streaming; support client cancel; emit partial traces if available.

### KV Cache (Redis)
- Key: `sha256(agent_id|locale|constraints|normalized_query|page_fp)`; salted by `agent_id + query + page_fp`  
- TTL 24h; `<100ms` retrieval path; LRU eviction

### Tools (Allow‑listed)
- Only execute tools declared in agent YAML (typed I/O, traced), e.g.: `render_diagram`, `unit_convert`, `ticket_create`

### Security
- TLS everywhere; JWT per agent; RBAC/ABAC; WAF; **60 req/min/user**  
- No raw PII in prompts/logs; GDPR/CCPA delete for episodic memory  
- Log redaction on traces; request size limits

### Observability & Evaluation
- OpenTelemetry spans across intent → retrieval → rerank → context → generation → writebacks  
- Prometheus metrics: `p95_total`, `cache_hit_ratio`, `citation_coverage`, `errors`  
- Nightly evals: retrieval/grounding/latency; CI **fails** on SLO regression

---

## 5. Coding Standards (Global)
- **Contracts first**: add/extend JSON Schemas before code  
- **No uncited answers** — wire refusal path  
- **Tests**: unit + integration + contract  
- **Observability required**: new code must add spans/metrics  
- **Security gates**: PII vault writes, redaction, rate‑limits  
- **Docs**: update local `AGENTS.md` upon behavior changes

---

## 6. Definition of Done (Feature‑Level)
- JSON/Pydantic schemas validated  
- Unit + integration tests pass  
- Traces/logs redacted & observable  
- Meets SLOs (`citation_coverage ≥ 0.95`, `P95 ≤ 3s`)  
- Security scans clear  
- Added to nightly eval suite (no regressions)

---

## 7. Where to Place `AGENTS.md` Files (Monorepo)
Agents always read the **nearest** `AGENTS.md` in the directory tree. Put them here:

```
agent-builder/
├─ AGENTS.md                      # ← Root (this file)
├─ apps/
│  ├─ api/
│  │  ├─ AGENTS.md               # ← API-specific rules (WebSockets/SSE, routes, contracts)
│  │  └─ ...
│  ├─ widget/
│  │  ├─ AGENTS.md               # ← Widget-specific rules (SDK, page_context extraction)
│  │  └─ ...
│  └─ admin/
│     ├─ AGENTS.md               # ← Admin UI rules (telemetry views, operator tools)
│     └─ ...
├─ packages/
│  ├─ retrieval/
│  │  ├─ AGENTS.md               # ← Retrieval impl, fusion, rerank, boosts
│  │  └─ ...
│  ├─ memory/
│  │  ├─ AGENTS.md               # ← Short-term, episodic (PII vault), semantic, graph
│  │  └─ ...
│  ├─ llm/
│  │  ├─ AGENTS.md               # ← Model adapters (qwen/gemini/llama/openai/claude)
│  │  └─ ...
│  ├─ tools/
│  │  ├─ AGENTS.md               # ← Registry, allowlists, typed I/O, tracing
│  │  └─ ...
│  ├─ cache/
│  │  ├─ AGENTS.md               # ← Redis keys, TTLs, eviction, perf targets
│  │  └─ ...
│  ├─ tracing/
│  │  ├─ AGENTS.md               # ← OTel spans, Prom metrics, dashboards
│  │  └─ ...
│  └─ commons/
│     ├─ AGENTS.md               # ← Types, errors, config, shared utils
│     └─ ...
├─ agents/
│  ├─ AGENTS.md                   # ← Brand blueprint authoring rules & examples
│  └─ glen_ai_v1/
│     ├─ AGENTS.md               # ← Brand-specific overrides (boosts, safety, tools)
├─ ingestion/
│  ├─ AGENTS.md                   # ← Chunking, embeddings (Voyage), indexing to Atlas/BM25
├─ evals/
│  ├─ AGENTS.md                   # ← Datasets, metrics (recall@k, precision@k, nDCG)
├─ infra/
│  ├─ AGENTS.md                   # ← Docker/Helm/K8s, GitHub Actions, secrets handling
```

**Rule of precedence:** `packages/retrieval/AGENTS.md` overrides the root for retrieval behavior; `apps/api/AGENTS.md` overrides both for API runtime behaviors, etc.

---

## 8. Subproject Templates
Copy one of these into each subproject and customize.

### Template — `apps/api/AGENTS.md`
```markdown
# AGENTS.md — API

## What
FastAPI service exposing `/api/v1/messages` with **WebSockets + SSE** streaming. Enforces schema‑locked outputs and refusal on missing citations.

## How
- **Run:** `uvicorn app.main:app --reload --port 8000`
- **Streaming:** default = WebSockets; fallback = SSE
- **Contracts:** validate request/response JSON Schemas; attach `trace_id`
- **Cache:** Redis KV; TTL 24h; `<100ms` retrieval target
- **Retrieval:** Hybrid (Atlas Vector + BM25) → RRF → rerank top 12; apply boosts
- **Models:** adapters for qwen/gemini/llama/openai/claude (env: `MODEL_PROVIDER`)
- **Embeddings:** Voyage (env: `EMBEDDINGS_PROVIDER=voyage`)
- **Security:** JWT per agent, rate limit 60 req/min/user, redact PII
- **Observability:** OTel spans; Prom metrics (`p95_total`, `citation_coverage`)

## Done
- Tests (unit+integration) pass; contracts enforced  
- Meets SLOs; dashboards updated; docs updated
```

### Template — `apps/widget/AGENTS.md`
```markdown
# AGENTS.md — Widget SDK

## What
React + TS widget that extracts `page_context` and streams responses from the API.

## How
- **Run:** `npm i && npm run dev`
- **Page Context:** collect URL, path, title, lang, meta, schema.org, nearby text
- **Transport:** prefer WebSockets; auto‑fallback to SSE
- **UI:** show token‑level stream; cancel support; show citations + disclaimers
- **Perf:** avoid blocking main thread; debounce inputs; small bundle

## Done
- Page context accurate; streaming resilient; a11y + i18n compliant
```

### Template — `packages/retrieval/AGENTS.md`
```markdown
# AGENTS.md — Retrieval

## What
Hybrid retrieval library: Voyage embeddings in MongoDB Atlas Vector Search + BM25; RRF fusion; cross‑encoder rerank; boosts.

## How
- **Vector:** upsert/query embeddings (Voyage) in Atlas Vector index
- **BM25:** search over title/body (Elastic/Lucene)
- **Fusion:** RRF 1/(k+rank) → ~top 50; **Rerank** → top 12
- **Boosts:** brand (manuals/faqs/policies), page (SKU, FAQ page)
- **Dedup:** MinHash on `doc_id+section`

## Done
- Deterministic results under seed; recall/precision targets met
```

### Template — `packages/llm/AGENTS.md`
```markdown
# AGENTS.md — LLM Adapters

## What
Uniform interface for Qwen, Gemini, LLaMA, OpenAI, Claude with streaming and schema‑locked outputs.

## How
- **Select provider:** env `MODEL_PROVIDER`
- **Streaming:** surface token events; support stop/cancel
- **Guardrails:** enforce output JSON Schema; inject refusal template on empty citations

## Done
- Golden tests per provider; identical behavior under the contract
```

### Template — `packages/memory/AGENTS.md`
```markdown
# AGENTS.md — Memory

## What
Short‑term buffer (auto‑summary), episodic (PII vault), semantic KB, graph rules.

## How
- **Short‑term:** summarize every 4 turns; TTL 72h
- **Episodic:** write if confidence ≥ 0.70; redact PII; TTL 90d; GDPR delete
- **Semantic:** version by `doc_id+section`; prefer latest

## Done
- Redaction tests; retention honored; GDPR delete works
```

### Template — `packages/cache/AGENTS.md`
```markdown
# AGENTS.md — Cache

## What
Redis KV cache to reduce cost/latency; `<100ms` retrieval.

## How
- **Key:** sha256(agent_id|locale|constraints|normalized_query|page_fp)
- **Salt:** agent_id + query + page_fp; TTL 24h; LRU eviction

## Done
- Hit‑ratio tracked; keys stable; no PII leakage
```

### Template — `ingestion/AGENTS.md`
```markdown
# AGENTS.md — Ingestion

## What
Deterministic pipeline: chunk → embed (Voyage) → index (Atlas Vector + BM25) → version.

## How
- **Chunking:** 300–500 tokens, 60 overlap; keep headings/tables
- **Metadata:** {doc_id, section, url, sku, tags[]}
- **Invalidation:** overwrite doc_id+section; bump version; update cache fingerprints

## Done
- Re‑ingest produces stable, versioned indexes; evals pass
```

### Template — `evals/AGENTS.md`
```markdown
# AGENTS.md — Evals

## What
Datasets & suites measuring retrieval (recall@k, precision@k, nDCG), grounding, latency (P50/P95).

## How
- **Nightly:** run suites, publish dashboards; fail CI on regression

## Done
- Baselines defined; alerts wired to Slack/Email/Jira
```

### Template — `infra/AGENTS.md`
```markdown
# AGENTS.md — Infra

## What
Docker images, Helm charts, K8s HPA, secrets & CI/CD.

## How
- **Secrets:** never in repo; use vault/CI secrets
- **K8s:** liveness/readiness; resource limits; HPA on RPS/P95
- **CD:** blue/green or canary; rollbacks scripted

## Done
- Reproducible deployments; rollback tested; budgets enforced
```

---

## 9. Contribution Workflow
- Conventional commits; small PRs; include tracing & tests  
- Update relevant `AGENTS.md` on behavior/config changes  
- Add eval cases for new retrieval/memory/LLM behaviors

---

## 10. Refusal & Safety Templates
- **No groundable source** → return refusal with: brief apology, what we can do next (e.g., ask for model/SKU, link to docs), and escalation cues (e.g., "gas smell", "visible sparking").

---

**End of root AGENTS.md.** Create/adjust the local `AGENTS.md` files as per the paths above; the **closest file wins** for agent behavior in each subproject.
