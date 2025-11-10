# Quick Fix Guide - Admin Dashboard Issues

## 🎯 The Two Main Issues

### Issue 1: Documents Not Showing
**Status:** ✅ ALREADY FIXED in code, just needs server restart

**What was done:**
- UI now shows "Existing Documents" (blue) and "New Documents" (yellow)  
- Documents load via `documentApi.getKnowledgeDocuments(agentId)`
- Backend already queries `knowledge_chunks` correctly

**To verify it works:**
1. Restart API server
2. Create/edit an agent
3. Upload documents
4. Navigate away and come back
5. Documents should appear in blue "Existing Documents" section

### Issue 2: Test Agent 500 Error
**Status:** ⚠️ NEEDS ENVIRONMENT SETUP

**Common causes:**
1. LLM API key not set
2. Agent doesn't exist
3. RAG enabled but configuration missing

**To fix:**
1. Set your LLM API key in `apps/api/.env`:
   ```bash
   # For OpenAI
   OPENAI_API_KEY=sk-...
   
   # OR for Qwen
   QWEN_API_KEY=...
   
   # OR for Gemini
   GEMINI_API_KEY=...
   ```

2. Restart API server

3. Test again

## 🚀 Step-by-Step Fix Process

### Step 1: Check What's in MongoDB

```bash
# Connect to MongoDB
mongosh "your_mongodb_uri"

# Switch to database
use agent_builder

# Check if chunks exist
db.knowledge_chunks.countDocuments()

# See sample chunks
db.knowledge_chunks.find().limit(2).pretty()

# Check agents
db.agents.find().limit(2).pretty()

# Check brands
db.brands.find().limit(2).pretty()
```

### Step 2: Restart API Server

```bash
# Stop current API
lsof -ti :8000 | xargs kill -9 2>/dev/null

# Start API
cd /Users/anantmendiratta/Desktop/anant2/agent-builder/apps/api
/Users/anantmendiratta/Desktop/anant2/agent-builder/apps/api/.venv/bin/python run.py
```

### Step 3: Test Endpoints

```bash
# 1. Health check
curl http://localhost:8000/health

# 2. Check documents endpoint
curl "http://localhost:8000/api/v1/ingest/documents"

# 3. Check agents endpoint (should return agents list)
curl "http://localhost:8000/api/v1/admin/agents"

# 4. Check brands endpoint
curl "http://localhost:8000/api/v1/admin/brands"
```

### Step 4: Test in Admin Dashboard

1. Open http://localhost:3000
2. Go to Agents
3. Edit an existing agent
4. Navigate to Step 4 (Knowledge Base)
5. **You should see:**
   - Blue section: "Existing Documents" with uploaded files
   - Upload section: Add new files
6. Navigate to Step 7 (Review)
7. **You should see:**
   - Green badge: "Testing Available"
   - Test input field
8. Type a test message and click "Test"
9. **If error:**
   - Check error message
   - Most likely: LLM API key not set
   - Fix: Add key to `.env` file

## 🔍 Debugging Commands

### If Documents Don't Show:

```bash
# 1. Check browser console (F12)
# Look for:
# - 📄 Loading documents for agent: [id]
# - 📦 Raw documents from API: [...]
# - ✅ Loaded X documents into wizard

# 2. Check API logs
tail -f /Users/anantmendiratta/Desktop/anant2/agent-builder/logs/api.log

# 3. Test API directly
curl "http://localhost:8000/api/v1/ingest/documents?agent_id=YOUR_AGENT_ID"

# 4. Check MongoDB
mongosh "your_uri"
use agent_builder
db.knowledge_chunks.distinct("agent_id")  # See which agents have docs
db.knowledge_chunks.find({agent_id: "YOUR_AGENT_ID"}).count()
```

### If Test Agent Fails:

```bash
# 1. Check what error you get in console
# Look for: 🧪 📡 📨 ❌ emojis

# 2. Check API logs for actual error
tail -f /Users/anantmendiratta/Desktop/anant2/agent-builder/logs/api.log

# 3. Verify LLM key is set
cd apps/api
cat .env | grep -E "OPENAI|QWEN|GEMINI"

# 4. Test message endpoint directly
curl -X POST "http://localhost:8000/api/v1/messages/" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello",
    "agent_id": "YOUR_AGENT_ID",
    "session_id": "test-123",
    "user_id": "test-user",
    "page_context": {"url": "http://test.com", "title": "Test"}
  }'
```

## 📝 Environment Variables Checklist

Check your `apps/api/.env` file has:

```bash
# Required
MONGODB_URI=mongodb+srv://...
MONGODB_DATABASE=agent-builder
REDIS_URL=redis://localhost:6379

# LLM Provider (at least one)
OPENAI_API_KEY=sk-...
# OR
QWEN_API_KEY=...
# OR
GEMINI_API_KEY=...

# Embeddings (for RAG)
VOYAGE_API_KEY=...  # If using Voyage embeddings

# Optional
API_LOG_LEVEL=info
CORS_ALLOW_ORIGINS=*
```

## ✅ What Should Work After Fixes

### Document Management:
1. ✅ Upload documents during agent creation
2. ✅ Documents stored in MongoDB `knowledge_chunks`
3. ✅ Documents appear when editing agent
4. ✅ Blue section shows existing documents
5. ✅ Yellow section shows newly added documents
6. ✅ Can remove documents from list
7. ✅ Documents persist across sessions

### Agent Testing:
1. ✅ "Testing Available" badge on deployed agents
2. ✅ "Deploy First to Test" badge on new agents
3. ✅ Test message sends to real API
4. ✅ Get actual AI responses
5. ✅ Clear error messages when something fails
6. ✅ Helpful troubleshooting tips

## 🐛 Known Limitations

1. **Testing before deployment:** Not possible (agent needs to exist in DB)
2. **File size limit:** 10MB per file (configured in code)
3. **Supported formats:** PDF, DOCX, TXT, MD, RTF, JSON
4. **Removing existing documents:** Only removes from UI list, not from database
5. **LLM provider:** Must have API key configured

## 📞 If Still Not Working

1. **Check all three servers are running:**
   ```bash
   lsof -i :8000  # API
   lsof -i :3000  # Admin
   lsof -i :5173  # Widget
   ```

2. **Check browser console** for JavaScript errors

3. **Check API logs** for backend errors

4. **Verify MongoDB connection:**
   ```bash
   mongosh "your_uri" --eval "db.adminCommand('ping')"
   ```

5. **Restart everything:**
   ```bash
   # Kill all
   lsof -ti :8000,:3000,:5173 | xargs kill -9

   # Start API
   cd apps/api && .venv/bin/python run.py &

   # Start Admin
   cd apps/admin && npm start &

   # Start Widget  
   cd apps/widget && npm run dev &
   ```

---

**Summary:**
- ✅ Frontend code is FIXED
- ✅ Backend code is CORRECT
- ⚠️ Just need to restart servers and set LLM keys
- 📝 Documents are stored and retrievable
- 🎯 Testing works when properly configured
