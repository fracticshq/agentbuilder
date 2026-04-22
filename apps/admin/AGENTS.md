# Admin Dashboard - Agent Configuration

This document describes the admin dashboard for managing AI agents and brands in the Agent Builder Platform.

## 📋 Table of Contents

1. [Dashboard Overview](#dashboard-overview)
2. [Brand Management](#brand-management)
3. [Agent Builder Wizard](#agent-builder-wizard)
4. [Knowledge Base Management](#knowledge-base-management)
5. [System Configuration](#system-configuration)

## 🎯 Dashboard Overview

The admin dashboard provides a comprehensive interface for managing brands and AI agents without requiring manual YAML configuration.

### Key Features

- **Brand Management**: Create and manage multiple brands with their own configurations
- **Agent Builder**: Visual wizard for creating AI agents step-by-step
- **Knowledge Base**: Upload and manage documents for RAG functionality
- **Runtime Settings**: Manage encrypted provider credentials and Azure/Voyage runtime metadata from the dashboard
- **System Prompts**: Rich text editor for agent personality configuration
- **Analytics**: Real-time metrics and usage statistics

## 🏢 Brand Management

### Brand Configuration

Each brand represents a company or organization that can have multiple AI agents.

```typescript
interface Brand {
  id: string;
  name: string;              // e.g., "Essco Bathware"
  slug: string;              // e.g., "essco-bathware"
  description: string;
  logo_url?: string;
  website?: string;
  industry: string;
  contact_info: ContactInfo;
  brand_voice: BrandVoice;
  colors: BrandColors;
  created_at: string;
  updated_at: string;
}
```

### Brand Voice Configuration

```typescript
interface BrandVoice {
  tone: 'professional' | 'friendly' | 'casual' | 'formal';
  style: 'helpful' | 'authoritative' | 'consultative';
  personality: string[];     // e.g., ['knowledgeable', 'patient']
  language_style: string;    // e.g., 'clear and concise'
}
```

## 🤖 Agent Builder Wizard

### 7-Step Agent Creation Process

#### Step 1: Basic Information
- Agent name and description
- Brand selection
- Agent purpose and role

#### Step 2: LLM Configuration
- Provider is fixed to Azure OpenAI
- Deployment selection is loaded dynamically from the backend Azure deployment discovery endpoint
- Only currently deployed Azure OpenAI deployments should appear in the picker
- Temperature and token settings

#### Settings Page
- `/settings` is the operator control plane for runtime credentials
- Provider secrets are never rendered back in plaintext
- The page can save encrypted secrets, clear stored values, and run Azure OpenAI / Voyage connection tests
- Environment values are treated as bootstrap/fallback and should eventually be moved into stored settings

#### Step 3: System Prompt
- Rich text editor for agent personality
- Template library with pre-built prompts
- Brand voice integration

#### Step 4: Knowledge Base Setup
- Document upload interface
- File type validation (PDF, DOCX, TXT, MD)
- Chunking configuration

#### Step 5: RAG Configuration
- Embedding provider settings
- Retrieval parameters (top_k, similarity_threshold)
- Search optimization

#### Step 6: Features & Security
- Enable/disable features (websockets, file_upload, etc.)
- Rate limiting configuration
- Content filtering settings

#### Step 7: Review & Deploy
- Configuration preview
- YAML generation
- Test interface
- Deployment options

### Agent Configuration Schema

```typescript
interface Agent {
  id: string;
  brand_id: string;
  name: string;
  slug: string;
  description: string;
  configuration: {
    llm: {
      provider: string;
      model: string;
      temperature: number;
      max_tokens: number;
    };
    embedding: {
      provider: string;
      model: string;
    };
    rag: {
      enabled: boolean;
      top_k: number;
      similarity_threshold: number;
      knowledge_base_id: string;
    };
    features: {
      websockets: boolean;
      file_upload: boolean;
      conversation_memory: boolean;
      typing_indicators: boolean;
    };
    security: {
      rate_limiting: boolean;
      content_filtering: boolean;
      session_timeout: number;
    };
  };
  system_prompt: string;
  status: 'draft' | 'active' | 'inactive';
  created_at: string;
  updated_at: string;
}
```

## 📚 Knowledge Base Management

### Document Upload Interface

- **Drag-and-drop upload**: Modern file upload with progress tracking
- **Bulk operations**: Upload multiple documents simultaneously
- **File validation**: Automatic type checking and size limits
- **Preview functionality**: View document content before processing

### Document Processing Pipeline

1. **Upload**: Files stored in secure storage
2. **Text Extraction**: Content extracted from various formats
3. **Chunking**: Documents split into optimal chunks (300-500 tokens)
4. **Embedding Generation**: Vector embeddings created using Voyage AI
5. **Indexing**: Documents indexed in MongoDB Atlas for search

### Knowledge Base Organization

```typescript
interface KnowledgeDocument {
  id: string;
  agent_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  content: string;
  metadata: {
    title?: string;
    author?: string;
    category?: string;
    tags?: string[];
  };
  chunks: DocumentChunk[];
  embedding_status: 'pending' | 'processing' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
}
```

## ⚙️ System Configuration

### Environment Variables

```bash
# API Configuration
REACT_APP_API_URL=http://localhost:8000

# Authentication (future)
REACT_APP_AUTH_ENABLED=false

# Features
REACT_APP_ANALYTICS_ENABLED=true
REACT_APP_FILE_UPLOAD_MAX_SIZE=10485760  # 10MB
```

### API Endpoints

The admin dashboard communicates with the following API endpoints:

```typescript
// Brand Management
GET    /api/v1/admin/brands
POST   /api/v1/admin/brands
PUT    /api/v1/admin/brands/{id}
DELETE /api/v1/admin/brands/{id}

// Agent Management
GET    /api/v1/admin/agents
POST   /api/v1/admin/agents
PUT    /api/v1/admin/agents/{id}
DELETE /api/v1/admin/agents/{id}

// Azure OpenAI deployment discovery
GET    /api/v1/admin/llm/azure/deployments

// Runtime settings
GET    /api/v1/admin/settings/runtime
PUT    /api/v1/admin/settings/runtime
POST   /api/v1/admin/settings/runtime/test

// Knowledge Base
POST   /api/v1/admin/knowledge/{agent_id}
GET    /api/v1/admin/knowledge/{agent_id}
DELETE /api/v1/admin/knowledge/{doc_id}

// Templates
GET    /api/v1/admin/templates
POST   /api/v1/admin/templates
```

## 🎨 UI Components

### Component Structure

```
src/
├── components/
│   ├── Layout.tsx              # Main layout with sidebar
│   ├── BrandModal.tsx          # Brand creation/editing modal
│   ├── AgentWizard/            # 7-step agent creation wizard
│   │   ├── StepBasicInfo.tsx
│   │   ├── StepLLMConfig.tsx
│   │   ├── StepSystemPrompt.tsx
│   │   ├── StepKnowledgeBase.tsx
│   │   ├── StepRAGConfig.tsx
│   │   ├── StepFeatures.tsx
│   │   └── StepReview.tsx
│   ├── KnowledgeBase/          # Document management
│   │   ├── DocumentUpload.tsx
│   │   ├── DocumentList.tsx
│   │   └── DocumentPreview.tsx
│   └── forms/                  # Reusable form components
│       ├── FormField.tsx
│       ├── SelectField.tsx
│       └── RichTextEditor.tsx
├── pages/
│   ├── Dashboard.tsx           # Main dashboard overview
│   ├── Brands.tsx              # Brand listing and management
│   ├── BrandDetail.tsx         # Individual brand details
│   ├── Agents.tsx              # Agent listing
│   ├── AgentDetail.tsx         # Individual agent details
│   └── AgentWizard.tsx         # Agent creation wizard
└── api/
    └── client.ts               # API client with TypeScript types
```

## 🚀 Getting Started

### Prerequisites

- Node.js 18+ installed
- FastAPI backend running on port 8000
- MongoDB Atlas configured for data storage

### Installation

```bash
# Navigate to admin directory
cd apps/admin

# Install dependencies
npm install

# Start development server
npm start
```

### First Steps

1. **Access the dashboard** at `http://localhost:3000`
2. **Create your first brand** (e.g., "Essco Bathware")
3. **Set up an agent** using the wizard
4. **Upload knowledge base** documents
5. **Test the agent** in the preview interface

## 📊 Analytics & Monitoring

### Dashboard Metrics

- **Total Brands**: Number of configured brands
- **Active Agents**: Agents currently deployed
- **Total Conversations**: Message volume
- **Knowledge Documents**: Uploaded documents count

### Performance Tracking

- **Response Times**: Average and P95 latencies
- **Error Rates**: Failed requests and error types
- **Usage Patterns**: Peak hours and popular features
- **Cost Tracking**: LLM API usage and costs

## 🔒 Security & Access Control

### Authentication (Planned)

- **Role-based access**: Admin, Brand Manager, Agent Editor
- **Brand isolation**: Users can only access their assigned brands
- **Audit logging**: Track all configuration changes

### Data Protection

- **Secure uploads**: Virus scanning and file validation
- **PII detection**: Automatic redaction of sensitive data
- **Encryption**: All data encrypted at rest and in transit

---

This admin dashboard transforms the Agent Builder Platform from a developer tool requiring manual YAML editing into a user-friendly business platform accessible to non-technical stakeholders.
