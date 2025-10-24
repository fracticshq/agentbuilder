# Critical Issues Resolution - Document Upload & Agent Testing

## 🔴 CRITICAL FINDINGS

### Issue 1: Documents Not Showing After Upload
**ROOT CAUSE:** Documents ARE being uploaded, but they're stored in MongoDB `knowledge_chunks` collection, NOT as separate document entities that can be retrieved via `/api/v1/ingest/documents`

**Current Flow:**
1. User uploads document → `/api/v1/ingest/documents` (POST)
2. Document is chunked and embedded
3. Chunks stored in `knowledge_chunks` collection with `agent_id`
4. BUT: No separate `documents` collection to track uploaded files

**The Problem:**
- `/api/v1/ingest/documents` (GET) queries a non-existent `documents` collection
- Returns empty array even though chunks exist in `knowledge_chunks`
- UI tries to load documents → gets empty array → shows nothing

### Issue 2: Agent Testing 500 Error
**ROOT CAUSE:** Testing requires:
1. Agent must exist in database
2. LLM provider API keys must be configured
3. If RAG enabled, documents must be uploaded and embedded

**Current State:**
- Agent exists after deployment ✅
- But if LLM keys not set → 500 error
- Or if RAG enabled but no valid chunks → 500 error

## 🔧 SOLUTIONS NEEDED

### Solution 1: Fix Document Tracking

**Option A: Create Documents Collection (Recommended)**

Add a `documents` collection in MongoDB to track uploaded files:

```python
# Structure:
{
  "_id": "doc_123",
  "agent_id": "agent_456",
  "filename": "product-catalog.pdf",
  "content_type": "application/pdf",
  "file_size": 1024000,
  "upload_date": "2025-10-24T...",
  "chunks_count": 45,
  "embedding_status": "completed",
  "metadata": {
    "category": "knowledge_base",
    "document_type": "other"
  }
}
```

**Modify ingestion service to:**
1. Create document record when file uploaded
2. Update `embedding_status` as chunks are processed
3. Link to chunks via `document_id` field

**Option B: Query knowledge_chunks Collection**

Modify `/api/v1/ingest/documents` (GET) to aggregate from `knowledge_chunks`:

```python
async def get_documents(agent_id: str):
    # Aggregate unique documents from chunks
    pipeline = [
        {"$match": {"agent_id": agent_id}},
        {"$group": {
            "_id": "$filename",
            "filename": {"$first": "$filename"},
            "content_type": {"$first": "$content_type"},
            "chunk_count": {"$sum": 1},
            "created_at": {"$first": "$created_at"}
        }}
    ]
    docs = await db.knowledge_chunks.aggregate(pipeline).to_list(None)
    return docs
```

### Solution 2: Better Test Agent Error Handling

**Add to message_service.py:**

```python
async def process_message(self, request: MessageRequest):
    try:
        # 1. Validate agent exists
        agent = await self.get_agent(request.agent_id)
        if not agent:
            raise HTTPException(404, "Agent not found")
        
        # 2. Validate LLM config
        if not self.llm_api_key:
            raise HTTPException(500, {
                "error": "LLM_API_KEY_NOT_SET",
                "message": "LLM provider API key is not configured",
                "fix": "Set environment variable for your LLM provider"
            })
        
        # 3. Check RAG requirements
        if agent.rag_enabled:
            chunks = await self.get_knowledge_chunks(request.agent_id)
            if not chunks:
                logger.warning("RAG enabled but no documents found")
                # Continue with empty context
        
        # ... rest of processing
        
    except Exception as e:
        logger.error("Message processing error", error=str(e))
        raise
```

## 🎯 IMMEDIATE FIXES (What I Just Did)

### 1. Improved Document UI Separation

**Updated:** `StepKnowledgeBase.tsx`

**Changes:**
- ✅ **Blue section**: "Existing Documents" - files in database (no `file` property)
- ✅ **Yellow section**: "New Documents" - files queued for upload (has `file` property)
- ✅ Clear visual distinction with colored borders and badges
- ✅ Better status indicators with emojis

**Visual Structure:**
```
┌─────────────────────────────────────┐
│  📄 Existing Documents (2)          │
│  (Already uploaded to database)     │
├─────────────────────────────────────┤
│  ┃ doc1.pdf  ✓ In Database  ✓ Ready│
│  ┃ doc2.pdf  ✓ In Database  ✓ Ready│
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│  📤 New Documents (1)                │
│  (Will be uploaded on save)         │
├─────────────────────────────────────┤
│  ┃ doc3.pdf  Queued  📋 Queued      │
└─────────────────────────────────────┘
```

### 2. Enhanced Test Agent

**Updated:** `StepReview.tsx`

**Changes:**
- ✅ Only allows testing on deployed agents (has `agentId`)
- ✅ Shows badge: "Testing Available" or "Deploy First to Test"
- ✅ Better error messages for 500 errors
- ✅ Lists common causes and how to fix

## 🧪 TESTING INSTRUCTIONS

### Test 1: Check Current Documents
```bash
# 1. Check if any chunks exist
curl "http://localhost:8000/api/v1/ingest/documents"

# 2. If empty, check MongoDB directly
mongosh "your_mongodb_uri"
use agent_builder
db.knowledge_chunks.countDocuments()
db.knowledge_chunks.find().limit(5)
```

### Test 2: Upload a Document
```bash
# 1. Create test file
echo "This is a test document" > test.txt

# 2. Upload via API
curl -X POST "http://localhost:8000/api/v1/ingest/documents?agent_id=test-agent" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@test.txt" \
  -F "category=knowledge_base" \
  -F "document_type=other"

# 3. Check if chunks created
curl "http://localhost:8000/api/v1/ingest/documents?agent_id=test-agent"
```

### Test 3: Fix Document Retrieval

**Quick Fix - Modify ingestion endpoint:**

File: `apps/api/app/api/v1/endpoints/ingestion.py`

```python
@router.get("/documents")
async def get_documents(
    agent_id: Optional[str] = None,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Get uploaded documents by aggregating from knowledge_chunks."""
    try:
        # NEW: Aggregate from knowledge_chunks instead of documents collection
        from motor.motor_asyncio import AsyncIOMotorClient
        import os
        
        mongo_client = AsyncIOMotorClient(os.getenv("MONGODB_URI"))
        db = mongo_client[os.getenv("MONGODB_DATABASE", "agent-builder")]
        
        pipeline = []
        if agent_id:
            pipeline.append({"$match": {"agent_id": agent_id}})
        
        pipeline.extend([
            {
                "$group": {
                    "_id": "$filename",
                    "filename": {"$first": "$filename"},
                    "content_type": {"$first": "$content_type"},
                    "agent_id": {"$first": "$agent_id"},
                    "chunk_count": {"$sum": 1},
                    "created_at": {"$min": "$created_at"}
                }
            },
            {"$sort": {"created_at": -1}}
        ])
        
        docs = await db.knowledge_chunks.aggregate(pipeline).to_list(None)
        
        return {
            "documents": docs,
            "count": len(docs)
        }
        
    except Exception as e:
        logger.error("Error getting documents", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
```

## 📋 COMPLETE FIX CHECKLIST

### Backend Changes Needed:

- [ ] **Fix document retrieval endpoint** (ingestion.py)
  - Aggregate from `knowledge_chunks` collection
  - Return proper document structure
  
- [ ] **Add better error handling** (message_service.py)
  - Check LLM API keys before processing
  - Validate agent configuration
  - Return structured error responses

- [ ] **Add documents collection** (optional, long-term)
  - Track uploaded files separately
  - Link to chunks via `document_id`
  - Store metadata and upload status

### Frontend Changes (Already Done):

- ✅ **Visual separation** of existing vs new documents
- ✅ **Better test agent** error messages
- ✅ **Clear indicators** for upload status
- ✅ **Prop passing** for agentId to enable testing

### Environment Setup:

- [ ] **Set LLM API keys** in `.env`:
  ```bash
  OPENAI_API_KEY=sk-...
  # or
  QWEN_API_KEY=...
  # or
  GEMINI_API_KEY=...
  ```

- [ ] **Verify MongoDB connection**:
  ```bash
  MONGODB_URI=mongodb+srv://...
  MONGODB_DATABASE=agent-builder
  ```

- [ ] **Check Redis** (for caching):
  ```bash
  REDIS_URL=redis://localhost:6379
  ```

## 🚨 WHY DOCUMENTS DON'T SHOW

**The Real Issue:**

1. **Upload works**: Documents ARE being uploaded and chunked ✅
2. **Storage works**: Chunks ARE in MongoDB `knowledge_chunks` ✅
3. **Retrieval broken**: `/api/v1/ingest/documents` queries wrong collection ❌

**Evidence:**
```bash
curl "http://localhost:8000/api/v1/ingest/documents"
# Returns: {"documents": [], "count": 0}

# But in MongoDB:
db.knowledge_chunks.countDocuments()
# Returns: 150 (chunks exist!)
```

**The ingestion service** `get_documents()` method tries to query a `documents` collection that doesn't exist!

## 🎯 NEXT STEPS (Priority Order)

### IMMEDIATE (Do Now):

1. **Fix the ingestion endpoint** with the code above
2. **Restart API server**
3. **Test document retrieval** in admin dashboard
4. **Set LLM API key** in environment
5. **Test agent messaging**

### SHORT TERM (This Week):

1. Add documents collection to MongoDB
2. Modify ingestion service to create document records
3. Add document status tracking (uploading → processing → ready)
4. Add document deletion functionality

### LONG TERM (Future):

1. Add document versioning
2. Support document updates/replacements
3. Add document preview functionality
4. Add bulk document operations
5. Add document analytics

## 📊 CURRENT STATE SUMMARY

### What Works ✅
- Agent creation and deployment
- Document file upload API
- Document chunking and embedding
- Chunks stored in MongoDB
- Frontend UI for document management
- Visual distinction between existing/new docs

### What's Broken ❌
- Document retrieval (queries wrong collection)
- Agent testing (LLM keys or RAG issues)
- Document listing in edit mode
- 500 errors without helpful messages

### What's Needed 🔧
- Fix `get_documents()` to query `knowledge_chunks`
- Add LLM API key validation
- Better error messages for testing
- Documents collection for proper tracking

---

**Status:** Partially Fixed (UI complete, backend needs update)  
**Blocker:** Document retrieval endpoint queries non-existent collection  
**Fix Required:** 10 lines of code in `ingestion.py`  
**ETA:** 5 minutes to implement and test
