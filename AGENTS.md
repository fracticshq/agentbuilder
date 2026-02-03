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

### Admin Dashboard - Visual Agent Builder ✅

The Agent Builder platform now features a **fully functional web-based admin dashboard** that provides an intuitive interface for managing brands and agents without manual YAML editing.

**Access:** `http://localhost:3000` (default)

### Key Features (Implemented)

1. ✅ **Brand Management** - Multi-tenant support with brand-isolated databases
2. ✅ **Agent Builder Wizard** - 7-step wizard for agent creation and editing
3. ✅ **Knowledge Base Manager** - Drag-and-drop document upload with real-time processing
4. ✅ **System Prompt Editor** - Template library with 10+ industry-specific prompts
5. ✅ **LLM Configuration** - Visual provider and model selection (Qwen, OpenAI, Gemini, etc.)
6. ✅ **Brand-Isolated Databases** - Each brand gets its own MongoDB database
7. ✅ **Product Card Display** - E-commerce style product recommendations in widget
8. ✅ **Smart Citations** - Perplexity-style citations with product awareness

### How It Works

#### 1. Brand Creation
- Navigate to `/brands/new` in the admin dashboard
- Fill in brand details (name, slug, industry, contact info)
- Configure brand voice (tone, style, personality traits)
- Set visual identity (colors, logo)
- System creates dedicated MongoDB database: `{brand-slug}`

#### 2. Agent Creation via 7-Step Wizard
Navigate to `/agents/new` and complete:

**Step 1: Basic Configuration**
- Agent name and description
- Select parent brand from dropdown
- Choose agent type (Support, Sales, Technical, General)

**Step 2: LLM Configuration**
- Provider selection: OpenAI, Qwen, Gemini, Anthropic
- Model selection (dynamic based on provider)
- Temperature, max tokens, streaming settings

**Step 3: System Prompt**
- Choose from 10+ professional templates
- Variable substitution for brand-specific info
- Full markdown editor with preview
- Templates include: Customer Support, Technical Support, Sales, E-commerce, Healthcare, Finance, etc.

**Step 4: Knowledge Base**
- Drag-and-drop document upload (PDF, TXT, MD, DOCX, HTML)
- Real-time processing status
- Documents stored in brand database with metadata (agent_id, brand_id, brand_slug)
- List view with document management

**Step 5: RAG Configuration**
- Enable/disable RAG
- Similarity threshold (0.0 - 1.0)
- Top-K results configuration
- Embedding provider selection

**Step 6: Features & Security**
- Toggle WebSockets, streaming, conversation memory
- Rate limiting configuration
- Session timeout settings

**Step 7: Review & Deploy**
- Preview all configuration
- Test interface (coming soon)
- One-click deployment
- Agent immediately available via API

#### 3. Knowledge Base Management
- Upload documents via `/agents/{id}/edit` → Knowledge Base tab
- Supported formats: PDF, Markdown, Text, Word, HTML
- Automatic chunking (300-500 tokens, 60 overlap)
- Voyage embeddings generated automatically
- Vector storage in MongoDB Atlas with brand isolation
- Documents include metadata for cross-referencing

#### 4. Widget Integration
Embed the agent in any website:

```html
<div id="agent-widget"></div>
<script src="http://localhost:5173/widget.js"></script>
<script>
  AgentWidget.init({
    agentId: 'your-agent-id',
    apiUrl: 'http://localhost:8000',
    theme: 'light'
  });
</script>
```

**Widget Features:**
- ✅ Token-level streaming responses
- ✅ Horizontal product card carousel (8-10 products)
- ✅ Product cards with image, name, SKU, price, "Learn More" button
- ✅ Perplexity-style numbered citations (small, compact)
- ✅ Product-aware citations linking to product pages
- ✅ Readable markdown text (15px base font)
- ✅ WebSocket support with SSE fallback

### Current Capabilities

- ✅ **Visual agent creation** - No code or YAML editing required
- ✅ **Brand isolation** - Complete data separation per brand
- ✅ **Document ingestion** - Automatic processing and embedding
- ✅ **Multi-LLM support** - Switch providers via dropdown
- ✅ **Template library** - Pre-built prompts for common use cases
- ✅ **Real-time chat** - Streaming responses with WebSockets
- ✅ **Product recommendations** - E-commerce style cards with product info
- ✅ **Smart citations** - Context-aware citations with product links
- ✅ **Brand databases** - Each brand has dedicated MongoDB database

## 🎯 Planned Features (Not Yet Implemented)

### Future Enhancements

1. **Enhanced Prompt Editor** - Rich text editor with live preview
2. **Form Validation** - Comprehensive validation across all wizard steps
3. **YAML Import/Export** - Import existing agent configurations

4. **Agent Testing Interface** - Test agents before deployment
5. **Analytics Dashboard** - Usage metrics and performance tracking
6. **Advanced Security Settings** - Fine-grained access control
7. **Conversation History Viewer** - Review past conversations
8. **A/B Testing for Prompts** - Compare prompt effectiveness
9. **Multi-language Support** - Internationalization for widgets
10. **Webhook Integrations** - Connect to external systems

## 🏢 Brand Management (Implemented ✅)

### Brand Entity Structure

```typescript
interface Brand {
  _id: string;
  name: string;              // e.g., "Essco Bathware"
  slug: string;              // e.g., "essco-bathware" (database name)
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

### Brand Management UI (Live)

#### Create Brand Flow (`/brands/new`)
1. **Basic Information**
   - Brand name, description, industry
   - Website URL
   - Contact email, phone, address

2. **Brand Voice Configuration**
   - Tone selection (professional, casual, friendly)
   - Style preferences (helpful, authoritative, consultative)
   - Personality traits multi-select

3. **Visual Identity**
   - Primary, secondary, accent colors
   - Logo URL (future: upload)

4. **Database Creation**
   - System automatically creates MongoDB database: `{brand-slug}`
   - Initializes collections: knowledge_base, conversations, etc.
   - Stores brand metadata in system database

#### Brand Dashboard (`/brands`)
- ✅ List all brands with search and filtering
- ✅ View agents per brand
- ✅ Edit brand settings
- ✅ Delete brands (with confirmation)
- 🚧 Knowledge base statistics (coming soon)
- 🚧 Usage analytics (coming soon)

## 🤖 Agent Builder Wizard (Implemented ✅)

### Step-by-Step Agent Creation

The Agent Builder Wizard is **fully functional** and accessible at `/agents/new` or `/agents/{id}/edit`.

#### Step 1: Basic Configuration ✅
- **Agent Name**: e.g., "Customer Support Assistant"
- **Description**: Brief description of agent purpose
- **Brand Selection**: Dropdown of existing brands (required)
- **Agent Type**: Support, Sales, Technical, General (dropdown)

#### Step 2: LLM Configuration ✅
- **Provider Selection**: OpenAI, Qwen, Gemini, Anthropic (dropdown)
- **Model Selection**: Dynamic list based on selected provider
  - OpenAI: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo
  - Qwen: qwen-max, qwen-plus, qwen-turbo
  - Gemini: gemini-pro, gemini-1.5-pro
- **Advanced Settings**: 
  - Temperature (0.0 - 2.0 slider)
  - Max tokens (100 - 4000)
  - Streaming (toggle)

#### Step 3: System Prompt Creation ✅
- **Template Library**: 10+ pre-built industry templates
  - Customer Support Agent
  - Technical Support Specialist
  - Sales Assistant
  - E-commerce Product Advisor
  - Healthcare Assistant
  - Financial Advisor
  - Legal Assistant
  - Education Tutor
  - HR Assistant
  - General Knowledge Assistant
- **Variable Substitution**: `{brand_name}`, `{brand_tone}`, `{brand_style}` auto-populated
- **Markdown Editor**: Full editing with syntax highlighting
- **Preview Mode**: See formatted prompt (coming soon)

#### Step 4: Knowledge Base Setup ✅
- **Document Upload**: Drag-and-drop with multiple file support
- **Supported Formats**: PDF, MD, TXT, DOCX, HTML
- **Real-time Processing**: Progress bars and status updates
- **Document List**: View uploaded documents with metadata
- **Brand Isolation**: Documents stored in `{brand-slug}` database
- **Metadata Injection**: Each chunk includes agent_id, brand_id, brand_slug

#### Step 5: RAG Configuration ✅
- **Enable/Disable RAG**: Toggle switch
- **Similarity Threshold**: Slider (0.0 - 1.0)
- **Top-K Results**: Number input (1 - 20)
- **Embedding Provider**: Voyage (default)

#### Step 6: Features & Security ✅
- **Feature Toggles**: 
  - WebSockets (real-time communication)
  - Streaming (token-level responses)
  - Conversation Memory (session persistence)
- **Rate Limiting**: Requests per minute (default: 60)
- **Session Settings**: Timeout in seconds (default: 1800)

#### Step 7: Review & Deploy ✅
- **Configuration Preview**: Review all settings before saving
- **Validation**: Automatic validation of required fields
- **Save**: Creates agent in system database
- **Immediate Availability**: Agent ready for use via API and widget
- 🚧 **Test Interface**: Coming soon

### Auto-Generated Configuration

The wizard automatically stores agent configuration in MongoDB with this structure:

```typescript
interface Agent {
  _id: string;
  name: string;
  description: string;
  brand_id: string;
  brand_slug: string;          // Database name for brand isolation
  agent_type: string;
  llm_config: {
    provider: string;
    model: string;
    temperature: number;
    max_tokens: number;
    streaming: boolean;
  };
  system_prompt: string;        // Full prompt with variables substituted
  rag_config: {
    enabled: boolean;
    top_k: number;
    similarity_threshold: number;
    embedding_provider: string;
  };
  features: {
    websockets: boolean;
    streaming: boolean;
    conversation_memory: boolean;
  };
  security: {
    rate_limit: number;
    session_timeout: number;
  };
  created_at: string;
  updated_at: string;
}
```

## 📚 Knowledge Base Management (Implemented ✅)

### Document Management Interface

The Knowledge Base Manager is **fully functional** within the Agent Builder Wizard (Step 4) and agent edit page.

#### Upload Interface ✅
- **Drag-and-Drop Zone**: Multi-file upload support
- **Bulk Upload**: Upload multiple documents simultaneously
- **Progress Tracking**: Real-time processing with status indicators
- **Error Handling**: Clear error messages with retry options
- **Brand Isolation**: Documents automatically stored in brand database

#### Document Processing ✅
- **Automatic Chunking**: 300-500 tokens per chunk, 60 token overlap
- **Embedding Generation**: Voyage embeddings created automatically
- **Vector Storage**: MongoDB Atlas Vector Search indexing
- **Metadata Injection**: Each chunk includes:
  ```json
  {
    "agent_id": "uuid",
    "brand_id": "uuid", 
    "brand_slug": "essco-bathware",
    "doc_id": "unique-doc-id",
    "section": "chunk-number",
    "content_type": "product|faq|manual|policy",
    "product_sku": "SKU123",      // For product documents
    "product_name": "Product Name", // For product documents
    "url": "source-url"
  }
  ```

#### Document List View ✅
- **Document Table**: Shows all uploaded documents for the agent
- **Brand Resolution**: Automatically resolves agent → brand_slug
- **Loading States**: Smooth loading experience with spinners
- **No Flickering**: Fixed race conditions in brand resolution

#### Supported File Types ✅
- PDF documents (.pdf)
- Markdown files (.md)
- Text files (.txt)
- Word documents (.docx)
- HTML files (.html)

### Knowledge Base Analytics (Planned)
- 🚧 **Document Count**: Total documents per agent
- 🚧 **Storage Usage**: Monitor vector storage consumption
- 🚧 **Query Analytics**: Most retrieved documents
- 🚧 **Performance Metrics**: Retrieval accuracy and speed

## ✍️ System Prompt Configuration (Implemented ✅)

### Template Library

The Agent Builder includes a comprehensive template library with 10+ industry-specific prompts.

#### Available Templates ✅
1. **Customer Support Agent** - General customer service
2. **Technical Support Specialist** - Technical troubleshooting
3. **Sales Assistant** - Sales and product recommendations
4. **E-commerce Product Advisor** - Online shopping assistance
5. **Healthcare Assistant** - Healthcare information (with disclaimers)
6. **Financial Advisor** - Financial guidance (with disclaimers)
7. **Legal Assistant** - Legal information (with disclaimers)
8. **Education Tutor** - Educational support
9. **HR Assistant** - HR and recruitment support
10. **General Knowledge Assistant** - General-purpose assistant

#### Variable Substitution ✅
Templates support dynamic brand variables:
- `{brand_name}` - Inserts brand name
- `{brand_tone}` - Inserts brand tone (e.g., "professional")
- `{brand_style}` - Inserts brand style (e.g., "helpful")

Example:
```
You are the {brand_name} AI Assistant, providing {brand_tone} and 
{brand_style} support to our customers...
```

#### Markdown Editor ✅
- **Full markdown support** - Format prompts with markdown
- **Syntax highlighting** - Clear visual editing experience
- **Large text area** - Comfortable editing space
- **Template selection** - Choose template, then customize

#### Planned Features (Not Implemented)
- 🚧 **Live Preview**: Real-time formatted preview
- 🚧 **Prompt Testing**: Test with sample queries before saving
- 🚧 **Version History**: Track prompt changes over time
- 🚧 **A/B Testing**: Compare different prompt versions

## ⚙️ LLM Provider Configuration (Implemented ✅)

### Provider Management

The Agent Builder supports multiple LLM providers with a simple dropdown interface.

#### Supported Providers ✅
- **OpenAI**: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo
- **Qwen**: qwen-max, qwen-plus, qwen-turbo
- **Gemini**: gemini-pro, gemini-1.5-pro
- **Anthropic**: claude-3-opus, claude-3-sonnet, claude-3-haiku (configured, not tested)

#### Configuration Interface ✅
- **Provider Selection**: Dropdown with available providers
- **Model Selection**: Dynamic model list based on selected provider
- **Temperature Control**: Slider (0.0 - 2.0) for response randomness
- **Max Tokens**: Input field (100 - 4000) for response length
- **Streaming Toggle**: Enable/disable token-level streaming

#### API Key Management ✅
- **Environment Variables**: API keys stored in `.env` file
- **Secure Storage**: Keys never exposed in frontend code
- **Per-Provider Keys**: Different keys for each provider
  - `OPENAI_API_KEY`
  - `QWEN_API_KEY`
  - `GEMINI_API_KEY`
  - `ANTHROPIC_API_KEY`

#### Model Configuration Structure

```typescript
interface LLMConfiguration {
  provider: 'openai' | 'qwen' | 'gemini' | 'anthropic';
  model: string;
  temperature: number;     // 0.0 - 2.0
  max_tokens: number;      // 100 - 4000
  streaming: boolean;      // Enable token streaming
}
```

### Planned Features (Not Implemented)
- 🚧 **Per-Brand API Keys**: Different keys per brand for cost tracking
- 🚧 **Usage Tracking**: Monitor token usage and costs
- 🚧 **Rate Limiting**: Per-brand or per-agent rate limits
- 🚧 **Fallback Providers**: Automatic failover to backup provider
- 🚧 **Custom Providers**: Support for custom API endpoints
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

### Current Status: Fully Operational ✅

The admin dashboard is **fully functional** and production-ready with the following capabilities:

1. ✅ **Brand Management**: Create, edit, delete brands with database isolation
2. ✅ **Agent Creation**: 7-step wizard for complete agent configuration
3. ✅ **Knowledge Base**: Upload and manage documents with automatic processing
4. ✅ **System Prompts**: Template library with variable substitution
5. ✅ **LLM Integration**: Multiple provider support with visual configuration

### Backwards Compatibility
- Manual YAML configuration is **no longer required**
- All configuration is stored in MongoDB
- Agents can be created and managed entirely through the UI
- API endpoints remain stable for existing integrations

### Future Development Roadmap
1. **Enhanced Validation** - Comprehensive form validation
2. **YAML Import/Export** - Import existing configurations
3. **Rich Text Editor** - Enhanced prompt editor with live preview
4. **Testing Interface** - Test agents before deployment
5. **Analytics Dashboard** - Usage metrics and performance tracking

## 📊 Current Status

- ✅ **Admin Dashboard**: Fully implemented and operational
- ✅ **Brand Management**: Multi-tenant support with brand-specific databases
- ✅ **Agent Builder Wizard**: Complete 7-step wizard with all configuration options
- ✅ **Knowledge Base Management**: Document upload, processing, and storage
- ✅ **System Prompt Templates**: 10+ professional templates with variable substitution
- ✅ **LLM Configuration**: Visual provider and model selection
- ✅ **Brand-Isolated Databases**: Complete data isolation per brand
- ✅ **Widget Integration**: Embedded chat widget with product cards and citations
- ✅ **Product Display**: E-commerce style product cards (200px, horizontal carousel)
- ✅ **Smart Citations**: Perplexity-style citations with product awareness
- ✅ **Streaming Responses**: WebSocket and SSE support for token-level streaming
- 🚧 **Form Validation**: Basic validation in place, comprehensive validation pending
- 🚧 **Prompt Testing**: Coming soon
- 🚧 **Analytics Dashboard**: Coming soon

## 🎯 Next Steps

### High Priority
1. **Form Validation** - Add comprehensive validation across all wizard steps
2. **Agent Testing Interface** - Test agents before deployment
3. **Error Handling** - Improve error messages and recovery

### Medium Priority
4. **YAML Import/Export** - Import existing agent configurations
5. **Rich Text Editor** - Enhanced prompt editor with live preview
6. **Document Organization** - Categories, tags, and advanced search
7. **Usage Analytics** - Track agent performance and usage

### Future Enhancements
8. **A/B Testing** - Compare different prompt versions
9. **Conversation History** - Review past conversations
10. **Webhook Integrations** - Connect to external systems
11. **Multi-language Support** - Internationalization
12. **Advanced Security** - Fine-grained access control

## 🗄️ Brand Database Architecture

**COMPLETED**: Each brand now has its own dedicated MongoDB database for complete data isolation:

- **System Database** (`system`): Brands, users, agents (centralized management)
- **Brand Databases** (`{brand-slug}`): Knowledge base, conversations, memory systems
- **Connection Manager**: Dynamic database routing based on agent/brand context
- **Migration Tools**: Scripts to migrate existing data to brand-specific structure

See `BRAND_DATABASE_IMPLEMENTATION.md` for complete details.

This architecture transforms the platform into a true multi-tenant system with enterprise-grade data isolation.
| `API_LOG_LEVEL` | No | `debug` \| `info` \| `warn` \| `error` |
| `CORS_ALLOW_ORIGINS` | No | `*` (tighten in prod) |
| `REDIS_URL` | Yes | Redis for KV cache |
| `MONGO_URI` | Yes | MongoDB Atlas connection (Vector Search enabled) |
| `MONGO_SYSTEM_DB` | No | `system` | System database name for brands/users |
| `EMBEDDINGS_PROVIDER` | Yes | `voyage` |
| `MODEL_PROVIDER` | Yes | `qwen` \| `gemini` \| `llama` \| `openai` \| `claude` |

### Database Naming Convention
- **System Database**: `system` (or `MONGO_SYSTEM_DB` env var)
- **Brand Databases**: `{brand_slug}` (e.g., `essco-bathware`, `acme-corp`)
- **Database Selection**: Dynamic based on agent's `brand_id` or API context

---

## 4. Architecture & Contracts (What to Enforce)

### Database Architecture (Brand Isolation)
Each brand has its **own dedicated MongoDB database** for complete data isolation:

```
MongoDB Atlas Cluster
├── essco-bathware/               ← Essco brand database
│   ├── knowledge_base           ← Product chunks, embeddings
│   ├── conversations            ← Chat history
│   ├── episodic_memory          ← User facts/preferences (PII vaulted)
│   ├── short_term_memory        ← Rolling buffer (TTL 72h)
│   ├── semantic_memory          ← Brand KB (chunked + embedded)
│   ├── graph_memory             ← Rules, policies, escalation
│   └── agents                   ← Brand's agent configurations
│
├── brand-2/                      ← Another brand's database
│   ├── knowledge_base
│   ├── conversations
│   └── ...
│
└── system/                       ← System-wide database
    ├── brands                   ← Brand registry and metadata
    ├── users                    ← Global user accounts
    └── audit_logs               ← System-wide audit trail
```

**Benefits:**
- ✅ **Complete data isolation** between brands
- ✅ **Independent scaling** per brand
- ✅ **Easier backup/restore** per brand
- ✅ **Better security** (no cross-brand data leakage)
- ✅ **Cleaner data management** and compliance

### Memory Layers (Per Brand Database)
- **Short‑Term**: rolling buffer, auto‑summary every 4 turns, TTL 72h.
- **Episodic**: user facts/preferences; **PII vaulted**; TTL 90d; write only if `confidence ≥ 0.70`.
- **Semantic**: brand KB (chunked + embedded) — version by `doc_id+section`.
- **Graph**: rules, policies, escalation.

### SOTA Agentic Loop (Orchestrator)
The platform now uses a **Plan-and-Execute** orchestrator instead of a linear pipeline:

1.  **Planning**: Decomposes user query into a step-by-step plan using a "Reasoning Model".
2.  **Execution**: Iterates through the plan, invoking specialized Tools.
    - **RetrievalTool**: Wraps the Hybrid RAG pipeline (Vector + BM25 + RRF).
    - **ComputeTool**: (Future) For calculations.
3.  **Refinement**: Aggregates results and self-corrects via a Critic/Reviewer step.

### Retrieval Algorithm (via RetrievalTool)
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
