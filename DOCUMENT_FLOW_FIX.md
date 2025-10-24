# Knowledge Base Document Flow - Complete Fix

## 🎯 Problem Identified

**Issue:** Documents uploaded during agent creation weren't visible when returning to the dashboard.

**Root Cause:** Documents were being uploaded in Step 4 (Knowledge Base) WITHOUT an `agent_id` because the agent doesn't exist yet. The agent is only created in Step 7 (Deploy).

## 🔧 Solution Implemented

### 1. Two-Phase Document Upload Strategy

#### **Phase 1: Creating NEW Agent**
- User adds documents in Step 4
- Documents are stored locally with `status: 'ready'` and `file: File` object
- **NO upload happens yet** (agent_id doesn't exist)
- Documents are queued for upload after agent creation

#### **Phase 2: Agent Deployed (Step 7)**
- Agent is created via API → receives `agent_id`
- All queued documents are uploaded with correct `agent_id`
- Documents are linked to the agent in MongoDB

#### **Editing EXISTING Agent**
- When `agentId` prop exists, documents upload immediately
- This ensures edits to existing agents work correctly

### 2. Code Changes

#### A. `StepKnowledgeBase.tsx` - Conditional Upload Logic

```typescript
// Only upload immediately if we have an agentId (editing existing agent)
if (agentId) {
  // Upload to API with agent_id
  await documentApi.uploadDocuments([file], {
    agent_id: agentId,
    category: 'knowledge_base',
    document_type: 'other'
  });
} else {
  // For new agents, documents will be uploaded after agent creation
  console.log(`📋 Queued file for upload after agent creation: ${file.name}`);
}
```

**Key Changes:**
- Documents for NEW agents: `status: 'ready'`, stored with `file` object
- Documents for EXISTING agents: uploaded immediately with `agent_id`
- Clear console logging with emojis for debugging

#### B. `AgentWizard.tsx` - handleDeploy Upload After Creation

```typescript
// Upload documents if any exist with File objects
if (agentData.documents && agentData.documents.length > 0) {
  const filesToUpload = agentData.documents
    .filter((doc): doc is typeof doc & { file: File } => !!doc.file)
    .map(doc => doc.file);
  
  if (filesToUpload.length > 0) {
    console.log('📄 Uploading documents for agent:', createdAgent.id);
    await documentApi.uploadDocuments(filesToUpload, {
      agent_id: createdAgent.id,  // ✅ Correct agent_id
      category: 'knowledge_base',
      document_type: 'other'
    });
  }
}
```

**Key Changes:**
- Filters documents with `file` objects (new uploads)
- Uploads ALL queued documents after agent creation
- Uses the newly created `agent_id`
- Graceful error handling (doesn't fail entire deployment)

#### C. Document Loading for Existing Agents

```typescript
useEffect(() => {
  if (id && existingAgent) {
    const loadDocuments = async () => {
      const { documentApi } = await import('../api/client');
      const docs = await documentApi.getKnowledgeDocuments(id);
      
      // Map to wizard format
      const mappedDocs = docs.map(doc => ({
        id: doc.id,
        filename: doc.filename,
        size: doc.file_size || 0,
        type: doc.file_type,
        status: 'ready' as const,
        // No file object for existing docs (already uploaded)
      }));
      
      setAgentData(prev => ({ ...prev, documents: mappedDocs }));
    };
    loadDocuments();
  }
}, [id, existingAgent]);
```

**Key Changes:**
- Loads existing documents when editing agent
- Maps API response to wizard format
- Shows "Existing" badge in UI for previously uploaded docs

#### D. AgentId Prop Passing

```typescript
// In AgentWizard.tsx renderCurrentStep
case 4:
  return (
    <StepKnowledgeBase
      data={agentData}
      onChange={handleDataChange}
      agentId={id}  // ✅ Pass agent ID
    />
  );
```

## 📊 Document Flow Diagram

```
NEW AGENT CREATION:
┌─────────────┐
│   Step 1-3  │ User enters basic info, LLM config, system prompt
└─────────────┘
       ↓
┌─────────────┐
│   Step 4    │ User uploads documents
│ Knowledge   │ → Store File objects locally
│    Base     │ → Status: 'ready'
└─────────────┘ → NO API upload (no agent_id yet)
       ↓
┌─────────────┐
│   Step 5-6  │ RAG config, features
└─────────────┘
       ↓
┌─────────────┐
│   Step 7    │ 1. Create agent → get agent_id
│   Deploy    │ 2. Upload ALL queued documents with agent_id
└─────────────┘ 3. Documents linked in MongoDB
       ↓
┌─────────────┐
│  Dashboard  │ Documents visible (loaded via API)
└─────────────┘

EDITING EXISTING AGENT:
┌─────────────┐
│   Open      │ Agent has ID
│   Agent     │ → Load existing documents from API
└─────────────┘ → Show "Existing" badges
       ↓
┌─────────────┐
│   Step 4    │ Add new document
│ Knowledge   │ → Upload immediately with agent_id
│    Base     │ → Status: uploading → processing → ready
└─────────────┘
       ↓
┌─────────────┐
│   Save      │ All documents associated correctly
└─────────────┘
```

## 🧪 Testing Checklist

### Test Case 1: Create New Agent with Documents
- [ ] Start from agent list
- [ ] Click "Create Agent"
- [ ] Fill Steps 1-3 (basic info, LLM, prompt)
- [ ] **Step 4:** Upload 2-3 documents
  - [ ] Check console: "📋 Queued file for upload after agent creation"
  - [ ] Documents show in UI with "ready" status
- [ ] Complete Steps 5-6 (RAG, features)
- [ ] **Step 7:** Click "Deploy Agent"
  - [ ] Check console: "📄 Uploading documents for agent: [agent_id]"
  - [ ] Check console: "✅ Documents uploaded successfully"
- [ ] Navigate back to agent list
- [ ] Open the created agent
- [ ] **Verify:** All 2-3 documents are visible in Knowledge Base tab
- [ ] Check MongoDB `knowledge_chunks` collection: `agent_id` should match

### Test Case 2: Edit Existing Agent - Add Documents
- [ ] Open existing agent with no documents
- [ ] Navigate to Knowledge Base step
- [ ] Upload 1 document
  - [ ] Check console: "📤 Uploading file immediately (editing mode)"
  - [ ] Document shows "uploading" → "processing" → "ready"
- [ ] Save changes
- [ ] Navigate away and return to agent
- [ ] **Verify:** Document is visible with "Existing" badge
- [ ] Check MongoDB: document has correct `agent_id`

### Test Case 3: Edit Existing Agent - View Existing Documents
- [ ] Create agent with documents (Test Case 1)
- [ ] Navigate to agent list
- [ ] Open the agent
- [ ] Navigate to Knowledge Base step
- [ ] **Verify:** All previously uploaded documents visible
- [ ] **Verify:** Documents have "Existing" badge
- [ ] Check console: "✅ Loaded X documents into wizard"

### Test Case 4: MongoDB Verification
```bash
# Connect to MongoDB
mongosh "your_mongodb_uri"

# Switch to database
use agent_builder

# Check documents for specific agent
db.knowledge_chunks.find({ agent_id: "agent_id_here" })

# Verify fields:
# - agent_id: matches your agent
# - metadata.filename: correct filename
# - embedding_status: should be "completed"
# - chunks: array of embedded chunks
```

## 🚨 Edge Cases Handled

1. **Upload fails during deployment:**
   - Agent is created successfully
   - User sees alert: "Agent created but some documents failed to upload"
   - Documents can be added later by editing agent

2. **No documents added:**
   - Agent deploys normally
   - Documents array is empty or filtered out

3. **Editing without changing documents:**
   - Existing documents remain unchanged
   - No duplicate uploads

4. **Network errors:**
   - Clear error messages to user
   - Document status shows "error"
   - Can retry by re-adding document

## 📝 Console Logging Guide

### What to Look For

**Creating New Agent:**
```
📋 Queued file for upload after agent creation: document.pdf
🚀 Deploying agent with complete payload: {...}
✅ Agent created successfully: {...}
📄 Uploading documents for agent: abc123
✅ Documents uploaded successfully
```

**Editing Existing Agent:**
```
📄 Loading documents for agent: abc123
📦 Raw documents from API: [...]
✅ Loaded 3 documents into wizard
📤 Uploading file immediately (editing mode): new-doc.pdf
✅ Upload result: {...}
```

**Viewing Agent with Documents:**
```
🔍 Fetching knowledge documents with params: { agent_id: 'abc123' }
📥 API Response: { status: 200, data: [...] }
✨ Transformed documents: [...]
```

## 🎯 Success Criteria

✅ **NEW agent creation:**
- Documents upload AFTER agent creation with correct `agent_id`
- All documents visible when returning to dashboard

✅ **EDIT existing agent:**
- Existing documents load and display correctly
- New documents upload immediately with `agent_id`

✅ **Database integrity:**
- All documents in MongoDB have valid `agent_id`
- No orphaned documents (documents without agent_id)

✅ **User experience:**
- Clear status indicators during upload
- "Existing" badges for previously uploaded docs
- Error messages when uploads fail

## 🔄 API Endpoints Used

### 1. Upload Documents
```
POST /api/v1/ingest/documents?agent_id={id}
Content-Type: multipart/form-data

Form Data:
- files: File[]
- category: "knowledge_base"
- document_type: "other"
```

### 2. Get Documents
```
GET /api/v1/admin/documents?agent_id={id}

Response:
[{
  id: string,
  agent_id: string,
  filename: string,
  file_size: number,
  file_type: string,
  embedding_status: string,
  ...
}]
```

### 3. Create Agent
```
POST /api/v1/admin/agents

Payload: CreateAgentRequest
Response: Agent with id
```

## 🏁 Next Steps

1. **Start all servers:**
   ```bash
   ./start-all.sh
   ```

2. **Test complete flow:**
   - Create new agent with documents
   - Verify documents visible in dashboard
   - Edit agent and add more documents
   - Check MongoDB for correct associations

3. **Monitor console logs:**
   - Look for 📄 📋 ✅ ❌ emojis
   - Verify document flow matches expected pattern

4. **Production considerations:**
   - Add progress tracking for large file uploads
   - Implement retry logic for failed uploads
   - Add batch upload limits
   - Consider background job status polling

## 📚 Related Files

- `apps/admin/src/components/AgentWizard/StepKnowledgeBase.tsx` - Document upload UI
- `apps/admin/src/pages/AgentWizard.tsx` - Main wizard logic
- `apps/admin/src/api/client.ts` - API client with document endpoints
- `apps/api/app/api/v1/endpoints/ingestion.py` - Backend upload handler
- `apps/api/app/api/v1/endpoints/admin.py` - Agent CRUD endpoints

---

**Status:** ✅ Implementation complete  
**Testing:** 🔄 Ready for testing  
**Deployment:** ⏳ Pending verification
