# Vector Database & Storage Architecture

## Overview
The Agent Builder Platform uses **MongoDB Atlas Vector Search** for storing and retrieving document embeddings, similar to OpenAI Assistants' file storage system.

## 🗄️ Database Structure

### Collections

#### 1. **`knowledge_base`** (Primary Vector Store)
Stores all document chunks with their embeddings.

**Schema:**
```javascript
{
  _id: ObjectId("..."),                    // MongoDB unique ID
  job_id: "uuid-v4",                       // Ingestion job ID
  filename: "product-catalog.json",        // Original filename
  agent_id: "agent-uuid",                  // Agent this belongs to
  content: "This is the chunk text...",    // Actual text content
  embeddings: [0.123, -0.456, ...],       // 1024-dim vector (Voyage AI)
  metadata: {
    filename: "product-catalog.json",
    chunk_index: 0,                        // Position in document
    content_type: "application/json",
    start_char: 0,
    end_char: 500
  },
  created_at: "2024-10-24T12:00:00Z"
}
```

**Indexes:**
- Vector search index: `vector_index` on `embeddings` field (cosine similarity)
- Text search index: `text_search_index` on `content`, `filename`
- Filter indexes: `agent_id`, `job_id`, `created_at`

#### 2. **`agents`**
Stores agent configurations.

**Relevant Fields:**
```javascript
{
  id: "agent-uuid",
  name: "Essco Customer Support",
  configuration: {
    rag: {
      enabled: true,
      embedding: {
        provider: "voyage",
        model: "voyage-3-large"
      },
      retrieval: {
        top_k: 5,
        similarity_threshold: 0.7,
        context_window: 4000,
        rerank: {
          enabled: true,
          top_k: 3
        }
      },
      chunking: {
        strategy: "fixed",
        chunk_size: 500,
        chunk_overlap: 50
      }
    }
  }
}
```

## 🧬 Embeddings Model

### Voyage AI Configuration

**Provider:** Voyage AI  
**Model:** `voyage-3-large`  
**Dimensions:** 1024  
**API Endpoint:** `https://api.voyageai.com/v1/embeddings`

**Request Format:**
```json
POST https://api.voyageai.com/v1/embeddings
Authorization: Bearer VOYAGE_API_KEY

{
  "input": ["text to embed"],
  "model": "voyage-3-large"
}
```

**Response:**
```json
{
  "data": [
    {
      "embedding": [0.123, -0.456, ...],  // 1024 floats
      "index": 0
    }
  ],
  "model": "voyage-3-large",
  "usage": { "total_tokens": 15 }
}
```

## 📦 Document Processing Pipeline

### 1. Upload
```
POST /api/v1/ingest/documents
Content-Type: multipart/form-data

- files: File[]
- agent_id: string
- category: "knowledge_base"
- document_type: "product_data" | "faq_data" | "other"
```

### 2. Job Creation
```javascript
job_id = uuid.v4()
active_jobs[job_id] = {
  status: "pending",
  files_count: 3,
  processed_count: 0,
  agent_id: "agent-uuid",
  created_at: Date.now()
}
```

### 3. Text Extraction
- **JSON files:** Parse and convert to readable text
- **Text/Markdown:** Direct UTF-8 decode
- **Other:** Best-effort UTF-8 decode

### 4. Chunking
```javascript
chunk_size = 500 characters
chunk_overlap = 50 characters

chunks = []
start = 0
while (start < text.length) {
  chunk = text[start : start + chunk_size]
  chunks.push({
    content: chunk,
    metadata: {
      chunk_index: chunks.length,
      start_char: start,
      end_char: start + chunk_size
    }
  })
  start += (chunk_size - chunk_overlap)
}
```

### 5. Embedding Generation
For each chunk:
```python
response = await voyage_ai.embed(
  text=chunk.content,
  model="voyage-3-large"
)
chunk.embeddings = response.data[0].embedding  # 1024 floats
```

### 6. Storage
```javascript
await db.knowledge_base.insertOne({
  _id: uuid.v4(),
  job_id: job_id,
  filename: file.name,
  agent_id: agent_id,
  content: chunk.content,
  embeddings: chunk.embeddings,
  metadata: chunk.metadata,
  created_at: new Date().toISOString()
})
```

## 🔍 Vector Search (Retrieval)

### Query Flow

1. **User Query:**
   ```
   "What are the best bathroom fittings for small spaces?"
   ```

2. **Query Embedding:**
   ```javascript
   query_vector = await voyage_ai.embed(query)  // 1024-dim vector
   ```

3. **Vector Search:**
   ```javascript
   results = await db.knowledge_base.aggregate([
     {
       $vectorSearch: {
         index: "vector_index",           // Atlas vector index
         path: "embeddings",               // Field with vectors
         queryVector: query_vector,        // 1024 floats
         numCandidates: 100,               // Candidates to consider
         limit: 5,                         // Top-k results
         filter: { 
           agent_id: "agent-uuid"         // Filter by agent
         }
       }
     },
     {
       $project: {
         content: 1,
         filename: 1,
         score: { $meta: "vectorSearchScore" }
       }
     }
   ])
   ```

4. **Similarity Filtering:**
   ```javascript
   filtered = results.filter(r => r.score >= 0.7)  // Threshold
   ```

5. **Context Building:**
   ```javascript
   context = filtered.map(r => r.content).join("\n\n")
   ```

6. **LLM Prompt:**
   ```
   System: You are an Essco assistant. Use this context:
   ${context}
   
   User: What are the best bathroom fittings for small spaces?
   ```

## 📊 Viewing Configuration (Like OpenAI Assistants)

### In Admin Dashboard

**Location:** Navigate to `/agents/{agent_id}` → Scroll down to **"🔧 Technical Configuration"** section

This comprehensive panel shows:
- ✅ **Vector Database:** MongoDB Atlas, `knowledge_base` collection, `vector_index` index, agent filter query
- ✅ **Embeddings Model:** Voyage AI provider, `voyage-3-large` model, 1024 dimensions, API endpoint
- ✅ **Document Processing:** Chunking strategy (fixed/semantic), chunk size (500 chars), overlap (50 chars), total documents
- ✅ **RAG Configuration:** RAG enabled status, top-k (5), similarity threshold (0.7), context window, reranking settings
- ✅ **Document IDs Table:** Lists all documents with filename, job_id, chunks_count, upload timestamp
- ✅ **MongoDB Query Examples:** Copy-paste ready queries to inspect data directly
- ✅ **Storage Architecture Diagram:** Visual flow from Upload → Chunk → Embed → Store → Query
- ✅ Storage Architecture Diagram

### MongoDB Compass

Connect to your MongoDB Atlas cluster:

**Collections:**
```
agent-builder
├── agents              # Agent configs
├── brands              # Brand info
├── knowledge_base    # Vector embeddings ⭐
└── conversations       # Chat history
```

**Query Examples:**

```javascript
// Find all chunks for an agent
db.knowledge_base.find({ agent_id: "agent-uuid" })

// Count chunks per agent
db.knowledge_base.aggregate([
  { $group: { 
      _id: "$agent_id", 
      total_chunks: { $sum: 1 } 
  }}
])

// Find chunks from specific document
db.knowledge_base.find({ 
  agent_id: "agent-uuid",
  filename: "product-catalog.json"
})

// View embeddings (first 5 dimensions)
db.knowledge_base.findOne(
  { agent_id: "agent-uuid" },
  { embeddings: { $slice: 5 } }
)
```

## 🆚 Comparison with OpenAI Assistants

| Feature | OpenAI Assistants | Agent Builder Platform |
|---------|------------------|------------------------|
| **File Storage** | OpenAI managed storage | MongoDB Atlas `knowledge_base` |
| **File IDs** | `file-abc123` | `job_id` + `_id` |
| **Embeddings** | OpenAI ada-002 (1536-dim) | Voyage Large (1024-dim) |
| **Vector DB** | OpenAI internal | MongoDB Atlas Vector Search |
| **Chunking** | Automatic | Configurable (500 chars, 50 overlap) |
| **Retrieval** | Automatic | Configurable (top-k, threshold, rerank) |
| **Max Files** | 20 files per assistant | Unlimited (MongoDB) |
| **Max File Size** | 512 MB | Configurable (default 10 MB) |
| **File Types** | .pdf, .docx, .txt, etc | .json, .txt, .md, etc |
| **Cost** | $0.20/GB/day | Voyage AI: $0.12/1M tokens<br>MongoDB: Atlas pricing |

## 🔐 Data Lifecycle

### Creation
1. User uploads file → `/api/v1/ingest/documents`
2. Job created with `job_id`
3. File chunked → embedded → stored with `agent_id`

### Retrieval
1. User sends message → `/api/v1/messages/`
2. Query embedded → vector search in `knowledge_base`
3. Top-k chunks filtered by `agent_id`
4. Context sent to LLM

### Deletion
```javascript
// Delete all chunks for an agent
db.knowledge_base.deleteMany({ agent_id: "agent-uuid" })

// Delete specific document chunks
db.knowledge_base.deleteMany({ 
  agent_id: "agent-uuid",
  job_id: "job-uuid"
})
```

### Updates
- **Document update:** Delete old chunks → re-upload → new `job_id`
- **Agent config update:** Doesn't affect existing chunks
- **Embeddings update:** Re-run ingestion with new model

## 📈 Monitoring & Analytics

### Document Stats
```javascript
// Get document breakdown
db.knowledge_base.aggregate([
  { $match: { agent_id: "agent-uuid" } },
  { $group: { 
      _id: "$filename", 
      chunks: { $sum: 1 },
      first_upload: { $min: "$created_at" }
  }},
  { $sort: { chunks: -1 } }
])
```

### Storage Size
```javascript
// Get storage usage per agent
db.knowledge_base.aggregate([
  { $match: { agent_id: "agent-uuid" } },
  { $group: {
      _id: "$agent_id",
      total_chunks: { $sum: 1 },
      avg_content_length: { $avg: { $strLenCP: "$content" } }
  }}
])
```

### Performance
- **Vector Search:** ~50-200ms (MongoDB Atlas)
- **Embedding Generation:** ~100-500ms (Voyage AI API)
- **Full Retrieval Pipeline:** ~200-800ms

## 🛠️ Development Tools

### View Data in Admin UI
1. Navigate to `/agents/{agent_id}`
2. Scroll to **Technical Configuration**
3. See all details: vectors, embeddings, chunks, IDs

### MongoDB Atlas UI
1. Go to Atlas → Browse Collections
2. Select `knowledge_base`
3. Filter: `{ agent_id: "your-agent-id" }`
4. View chunks, embeddings, metadata

### API Endpoints
```bash
# Get all documents for agent
GET /api/v1/admin/documents?agent_id={id}

# Upload new documents
POST /api/v1/ingest/documents
Body: FormData with files + agent_id

# Check ingestion job status
GET /api/v1/ingest/jobs/{job_id}
```

## 📝 Best Practices

1. **Chunking Strategy:**
   - Small chunks (500 chars): Better precision
   - Large chunks (1500 chars): Better context
   - Overlap (50 chars): Avoid context breaks

2. **Similarity Threshold:**
   - High (0.8-0.9): Very precise, may miss relevant docs
   - Medium (0.6-0.7): Balanced
   - Low (0.4-0.5): More recall, less precision

3. **Top-K Selection:**
   - Small (3-5): Focused context, lower token cost
   - Medium (5-10): Balanced
   - Large (10-15): Comprehensive, higher cost

4. **Reranking:**
   - Enable for better result ordering
   - Adds 50-100ms latency
   - Improves relevance by 10-20%

## 🚀 Next Steps

- [ ] Implement file versioning (track updates)
- [ ] Add file metadata extraction (title, author, date)
- [ ] Support PDF, DOCX, HTML parsing
- [ ] Implement BM25 hybrid search (text + vector)
- [ ] Add cross-encoder reranking
- [ ] Cache frequent queries
- [ ] Add analytics dashboard for retrieval performance
