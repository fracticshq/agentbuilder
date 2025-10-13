# Agent Configuration and Management

This document covers agent configuration, management, and the planned admin dashboard for the Agent Builder Platform.

## 📋 Table of Contents

1. [Current Agent Configuration](#current-agent-configuration)
2. [Planned Admin Dashboard](#planned-admin-dashboard)
3. [Brand Management](#brand-management)
4. [Agent Builder Wizard](#agent-builder-wizard)
5. [Knowledge Base Management](#knowledge-base-management)
6. [System Prompt Configuration](#system-prompt-configuration)
7. [LLM Provider Configuration](#llm-provider-configuration)

## 🔧 Current Agent Configuration

### Manual YAML Configuration

Currently, agents are configured manually using YAML files in the `agents/` directory.

#### Example Agent Configuration

```yaml
# agents/essco-bathware-agent.yaml
metadata:
  name: "Essco Bathware Customer Support"
  description: "AI assistant for Essco Bathware customer inquiries"
  version: "1.0.0"
  brand: "essco-bathware"
  created_at: "2024-01-15T10:00:00Z"
  updated_at: "2024-01-15T10:00:00Z"

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
    knowledge_base_id: "essco-kb-001"

system_prompt: |
  You are the Essco Bathware AI Assistant, a knowledgeable customer service representative 
  for Essco Bathware, a premium bathroom solutions company.
  
  Your role:
  - Help customers find the right bathroom products
  - Provide installation guidance and support
  - Answer questions about warranties and maintenance
  - Maintain Essco's professional and helpful brand voice
  
  Guidelines:
  - Always be professional, helpful, and solution-oriented
  - Use the knowledge base to provide accurate product information
  - If you don't know something, direct customers to human support
  - Focus on Essco's quality and premium positioning

personality:
  tone: "professional"
  style: "helpful"
  expertise_level: "expert"
  brand_voice: "premium_helpful"

features:
  websockets: true
  file_upload: true
  conversation_memory: true
  typing_indicators: true

security:
  rate_limiting: true
  content_filtering: true
  session_timeout: 1800
```

### Current Limitations

- ❌ **Manual file editing** required for agent configuration
- ❌ **No visual interface** for agent creation
- ❌ **No brand management** system
- ❌ **Manual knowledge base** upload via API
- ❌ **No system prompt editor** interface
- ❌ **No centralized LLM** provider configuration

## 🎯 Planned Admin Dashboard

### Overview

A comprehensive web-based admin dashboard that will replace manual YAML editing with an intuitive interface for managing brands and agents.

### Key Features

1. **Brand Management** - Multi-tenant support for different companies
2. **Agent Builder Wizard** - Step-by-step agent creation
3. **Knowledge Base Manager** - Upload and organize documents
4. **System Prompt Editor** - Rich text editor for agent personality
5. **LLM Configuration** - Visual provider and model selection
6. **YAML Auto-generation** - Automatic config file creation from UI

## 🏢 Brand Management

### Brand Entity Structure

```typescript
interface Brand {
  id: string;
  name: string;              // e.g., "Essco Bathware"
  slug: string;              // e.g., "essco-bathware"
  description: string;
  logo_url?: string;
  website?: string;
  industry: string;
  contact_info: {
    email: string;
    phone?: string;
    address?: string;
  };
  brand_voice: {
    tone: string;            // professional, casual, friendly
    style: string;           // helpful, authoritative, consultative
    personality: string[];    // [expert, approachable, solution-oriented]
  };
  colors: {
    primary: string;
    secondary: string;
    accent: string;
  };
  created_at: string;
  updated_at: string;
}
```

### Brand Management UI

#### Create Brand Flow
1. **Basic Information**
   - Brand name, description, industry
   - Logo upload and website URL
   - Contact information

2. **Brand Voice Configuration**
   - Tone selection (professional, casual, friendly)
   - Style preferences (helpful, authoritative)
   - Personality traits selection

3. **Visual Identity**
   - Color scheme selection
   - Logo and branding assets
   - Widget styling preferences

#### Brand Dashboard
- Overview of all agents for the brand
- Knowledge base statistics
- Usage analytics and metrics
- Brand settings and configuration

## 🤖 Agent Builder Wizard

### Step-by-Step Agent Creation

#### Step 1: Basic Configuration
- **Agent Name**: e.g., "Customer Support Assistant"
- **Description**: Brief description of agent purpose
- **Brand Selection**: Choose from existing brands
- **Agent Type**: Support, Sales, Technical, General

#### Step 2: LLM Configuration
- **Provider Selection**: OpenAI, Qwen, Anthropic (dropdown)
- **Model Selection**: Based on selected provider
- **Advanced Settings**: Temperature, max tokens, top-p
- **API Key Management**: Secure key storage per brand

#### Step 3: System Prompt Creation
- **Rich Text Editor** with markdown support
- **Template Library**: Pre-built prompts for common use cases
- **Brand Voice Integration**: Auto-populate brand-specific guidelines
- **Preview Mode**: Test prompt with sample queries

#### Step 4: Knowledge Base Setup
- **Document Upload**: Drag-and-drop interface
- **File Management**: Organize documents by category
- **Processing Status**: Real-time ingestion progress
- **Content Preview**: View processed document content

#### Step 5: RAG Configuration
- **Enable/Disable RAG**: Toggle RAG functionality
- **Similarity Threshold**: Adjust retrieval sensitivity
- **Top-K Results**: Number of documents to retrieve
- **Knowledge Base Linking**: Select relevant document sets

#### Step 6: Features & Security
- **Feature Toggles**: WebSockets, file upload, memory
- **Rate Limiting**: Configure usage limits
- **Content Filtering**: Enable safety measures
- **Session Configuration**: Timeout and persistence settings

#### Step 7: Review & Deploy
- **Configuration Preview**: Review all settings
- **YAML Generation**: Auto-generated config file
- **Test Interface**: Test agent before deployment
- **Deployment**: One-click agent activation

### Auto-Generated YAML

The wizard automatically generates the YAML configuration based on UI inputs:

```typescript
// Auto-generation logic
const generateAgentConfig = (formData: AgentFormData) => {
  return {
    metadata: {
      name: formData.name,
      description: formData.description,
      brand: formData.brand.slug,
      version: "1.0.0",
      created_at: new Date().toISOString(),
    },
    configuration: {
      llm: {
        provider: formData.llmProvider,
        model: formData.llmModel,
        temperature: formData.temperature,
        max_tokens: formData.maxTokens,
      },
      // ... rest of config
    },
    system_prompt: formData.systemPrompt,
    // ... rest of configuration
  };
};
```

## 📚 Knowledge Base Management

### Document Management Interface

#### Upload Interface
- **Drag-and-Drop Zone**: Support for multiple file types
- **Bulk Upload**: Upload multiple documents at once
- **Progress Tracking**: Real-time upload and processing status
- **Error Handling**: Clear feedback on failed uploads

#### Document Organization
- **Categories**: Organize documents by type or topic
- **Tags**: Flexible tagging system for document discovery
- **Search**: Full-text search across all documents
- **Filters**: Filter by type, date, category, processing status

#### Document Processing
- **Text Extraction**: Preview extracted content
- **Chunking Strategy**: Configure how documents are split
- **Embedding Generation**: Monitor embedding creation
- **Vector Storage**: Track storage in MongoDB Atlas

#### Supported File Types
- PDF documents (.pdf)
- Markdown files (.md)
- Text files (.txt)
- Word documents (.docx)
- HTML files (.html)

### Knowledge Base Analytics
- **Document Count**: Total documents per agent
- **Storage Usage**: Monitor vector storage consumption
- **Query Analytics**: Most retrieved documents
- **Performance Metrics**: Retrieval accuracy and speed

## ✍️ System Prompt Configuration

### Rich Text Editor Features

#### Editor Interface
- **Markdown Support**: Rich text editing with markdown
- **Syntax Highlighting**: Code blocks and formatting
- **Real-time Preview**: Live preview of formatted prompt
- **Template Variables**: Insert brand-specific variables

#### Template Library
- **Industry Templates**: Pre-built prompts for different industries
- **Use Case Templates**: Customer support, sales, technical
- **Brand Voice Templates**: Professional, casual, friendly tones
- **Custom Templates**: Save and reuse custom prompts

#### Brand Integration
- **Auto-population**: Insert brand voice and guidelines
- **Variable Substitution**: Dynamic brand information
- **Voice Consistency**: Maintain consistent brand voice
- **Guidelines Enforcement**: Built-in brand guideline prompts

#### Testing Interface
- **Prompt Testing**: Test prompts with sample queries
- **Response Preview**: See how agent responds
- **A/B Testing**: Compare different prompt versions
- **Performance Metrics**: Track prompt effectiveness

## ⚙️ LLM Provider Configuration

### Provider Management

#### Supported Providers
- **OpenAI**: GPT-4, GPT-3.5-turbo models
- **Qwen**: Qwen-max, Qwen-plus models
- **Anthropic**: Claude models (planned)
- **Custom Providers**: API-compatible endpoints

#### Configuration Interface
- **Provider Selection**: Dropdown with available providers
- **Model Selection**: Dynamic model list based on provider
- **API Key Management**: Secure storage and validation
- **Advanced Settings**: Temperature, top-p, frequency penalty

#### Per-Brand Configuration
- **Brand-specific Keys**: Different API keys per brand
- **Model Preferences**: Preferred models for each brand
- **Cost Management**: Usage tracking and limits
- **Fallback Providers**: Backup provider configuration

### Model Configuration

```typescript
interface LLMConfiguration {
  provider: 'openai' | 'qwen' | 'anthropic' | 'custom';
  model: string;
  api_key: string;          // Encrypted storage
  base_url?: string;        // For custom providers
  parameters: {
    temperature: number;     // 0.0 - 2.0
    max_tokens: number;      // Model-specific limits
    top_p?: number;          // 0.0 - 1.0
    frequency_penalty?: number;
    presence_penalty?: number;
  };
  rate_limits: {
    requests_per_minute: number;
    tokens_per_minute: number;
  };
}
```

## 🗂️ File Structure (Planned)

```
apps/admin/                          # Admin Dashboard
├── src/
│   ├── pages/
│   │   ├── brands/
│   │   │   ├── BrandList.tsx       # List all brands
│   │   │   ├── BrandCreate.tsx     # Create new brand
│   │   │   ├── BrandEdit.tsx       # Edit brand settings
│   │   │   └── BrandDashboard.tsx  # Brand overview
│   │   ├── agents/
│   │   │   ├── AgentList.tsx       # List agents
│   │   │   ├── AgentWizard.tsx     # Agent creation wizard
│   │   │   ├── AgentEdit.tsx       # Edit agent configuration
│   │   │   └── AgentTest.tsx       # Test agent interface
│   │   ├── knowledge/
│   │   │   ├── DocumentManager.tsx # Document upload/management
│   │   │   ├── DocumentUpload.tsx  # Bulk upload interface
│   │   │   └── DocumentAnalytics.tsx # Knowledge base analytics
│   │   └── prompts/
│   │       ├── PromptEditor.tsx    # Rich text prompt editor
│   │       ├── PromptTemplates.tsx # Template library
│   │       └── PromptTesting.tsx   # Prompt testing interface
│   ├── components/
│   │   ├── forms/
│   │   │   ├── BrandForm.tsx       # Brand creation form
│   │   │   ├── AgentConfigForm.tsx # Agent configuration
│   │   │   └── LLMConfigForm.tsx   # LLM provider settings
│   │   ├── editors/
│   │   │   ├── YamlEditor.tsx      # YAML configuration editor
│   │   │   ├── PromptEditor.tsx    # System prompt editor
│   │   │   └── CodeEditor.tsx      # Code editing component
│   │   └── upload/
│   │       ├── FileUpload.tsx      # File upload component
│   │       ├── DocumentViewer.tsx  # Document preview
│   │       └── UploadProgress.tsx  # Upload progress tracking
│   ├── hooks/
│   │   ├── useBrands.ts           # Brand management hooks
│   │   ├── useAgents.ts           # Agent management hooks
│   │   └── useDocuments.ts        # Document management hooks
│   ├── api/
│   │   ├── brands.ts              # Brand API calls
│   │   ├── agents.ts              # Agent API calls
│   │   ├── documents.ts           # Document API calls
│   │   └── llm.ts                 # LLM provider API calls
│   └── utils/
│       ├── yaml-generator.ts      # YAML config generation
│       ├── validation.ts          # Form validation
│       └── file-utils.ts          # File handling utilities
```

## 🔄 Migration Path

### From Manual to Admin Dashboard

1. **Phase 1**: Build brand management interface
2. **Phase 2**: Implement agent creation wizard
3. **Phase 3**: Add knowledge base management
4. **Phase 4**: System prompt editor and testing
5. **Phase 5**: Advanced features and analytics

### Backwards Compatibility
- Existing YAML files will be importable
- API endpoints remain unchanged
- Gradual migration of manual configurations

## 📊 Current Status

- ✅ **YAML Configuration**: Manual agent configuration working
- ✅ **API Endpoints**: Document ingestion and messaging APIs
- 🚧 **Admin Dashboard**: Not implemented - high priority
- 🚧 **Brand Management**: Not implemented - required for multi-tenancy
- 🚧 **Visual Agent Builder**: Not implemented - core feature
- 🚧 **Knowledge Base UI**: Not implemented - essential for usability
- 🚧 **System Prompt Editor**: Not implemented - important for customization

## 🎯 Next Steps

1. **Implement Admin Dashboard** foundation
2. **Build Brand Management** system
3. **Create Agent Builder Wizard** with auto-YAML generation
4. **Develop Knowledge Base** management interface
5. **Add System Prompt Editor** with rich text capabilities
6. **Integrate LLM Provider** configuration UI
7. **Add Testing and Analytics** features

This admin dashboard will transform the platform from a developer-focused tool to a user-friendly platform accessible to non-technical users.
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
