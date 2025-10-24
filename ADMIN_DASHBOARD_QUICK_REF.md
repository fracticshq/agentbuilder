# Admin Dashboard - Quick Reference

## 🎯 What Changed

### ✅ Fixed Issues
1. **Removed Mock Data** - All API calls now use real database
2. **Fixed Status Updates** - Agent status properly saved to MongoDB
3. **Fixed Document Links** - Documents properly associated with agents via `agent_id`
4. **Enhanced Logging** - Console shows detailed deployment progress
5. **Better Errors** - User-friendly error messages with retry buttons

## 🚀 Testing Quick Commands

### Start Services
```bash
# Start MongoDB (if local)
mongod

# Start API server
cd apps/api && python run.py

# Start Admin Dashboard
cd apps/admin && npm start
```

### Verify Database
```bash
# Connect to MongoDB
mongosh

# Check collections
use agent_builder
db.brands.countDocuments()
db.agents.countDocuments()
db.knowledge_chunks.countDocuments()

# View an agent
db.agents.findOne()
```

## 📊 API Endpoints

### Brands
- `GET /api/v1/admin/brands/` - List all
- `POST /api/v1/admin/brands/` - Create
- `GET /api/v1/admin/brands/{id}` - Get one
- `PUT /api/v1/admin/brands/{id}` - Update
- `DELETE /api/v1/admin/brands/{id}` - Delete

### Agents
- `GET /api/v1/admin/agents/` - List all (filter: `?brand_id=xxx`)
- `POST /api/v1/admin/agents/` - Create
- `GET /api/v1/admin/agents/{id}` - Get one
- `PUT /api/v1/admin/agents/{id}` - Update (partial OK)
- `DELETE /api/v1/admin/agents/{id}` - Delete

### Documents
- `POST /api/v1/ingest/documents?agent_id={id}` - Upload
- `GET /api/v1/ingest/documents?agent_id={id}` - List
- `GET /api/v1/ingest/status/{job_id}` - Job status

## 🔍 Console Logging

Watch for these emojis in browser console:
- 🚀 = Starting deployment
- ✅ = Success
- ❌ = Error
- 📄 = Document upload

## ⚠️ Common Errors

### "Cannot connect to server"
**Cause**: API server not running  
**Fix**: `cd apps/api && python run.py`

### "Database not available"
**Cause**: MongoDB not connected  
**Fix**: Check `MONGO_URI` in `.env`

### "Unsupported file type"
**Cause**: Wrong file format  
**Fix**: Use .json, .txt, .md, .pdf, or .html

## ✅ Verification Steps

### After Agent Creation
1. Check `/agents` page - agent appears
2. Click agent - all fields populated
3. MongoDB: `db.agents.findOne({name: "Your Agent"})`
4. Verify `configuration` object is complete

### After Document Upload
1. Agent detail page shows documents
2. MongoDB: `db.knowledge_chunks.find({agent_id: "xxx"})`
3. Verify `agent_id` is set
4. Verify `embeddings` array exists

### After Status Toggle
1. UI updates immediately
2. Refresh page - status persists
3. MongoDB: `db.agents.findOne({id: "xxx"}, {status: 1})`

## 🐛 Debug Mode

```typescript
// In browser console
localStorage.setItem('debug', 'true')

// View saved draft
JSON.parse(localStorage.getItem('agent_wizard_draft'))

// Clear draft
localStorage.removeItem('agent_wizard_draft')
```

## 📁 Key Files

### Frontend
- `apps/admin/src/api/client.ts` - API calls
- `apps/admin/src/api/errorHandler.ts` - Error handling
- `apps/admin/src/pages/AgentWizard.tsx` - Agent creation
- `apps/admin/src/pages/Agents.tsx` - Agent list
- `apps/admin/src/pages/AgentDetail.tsx` - Agent view

### Backend
- `apps/api/app/api/v1/admin/agents.py` - Agent CRUD
- `apps/api/app/api/v1/admin/brands.py` - Brand CRUD
- `apps/api/app/api/v1/endpoints/ingestion.py` - Document upload
- `apps/api/app/services/ingestion_service.py` - Document processing

## 🔧 Environment Variables

### Required
```bash
MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/agent_builder
VOYAGE_API_KEY=your_voyage_key
```

### Optional
```bash
REACT_APP_API_URL=http://localhost:8000
CORS_ALLOW_ORIGINS=http://localhost:3000
API_LOG_LEVEL=info
```

## 📝 MongoDB Schema

### agents
```javascript
{
  id: "uuid",
  brand_id: "uuid",
  name: "string",
  description: "string",
  slug: "string",
  system_prompt: "string",
  configuration: {
    llm: {...},
    personality: {...},
    rag: {...},
    features: {...},
    security: {...}
  },
  status: "draft|active|inactive",
  created_at: Date,
  updated_at: Date
}
```

### knowledge_chunks
```javascript
{
  _id: "uuid",
  job_id: "uuid",
  filename: "string",
  agent_id: "uuid",  // 🔥 Critical
  content: "string",
  embeddings: [float...],  // 1024 dims
  metadata: {...},
  created_at: Date
}
```

## 🎓 Best Practices

1. **Always check console** - Look for 🚀 ✅ ❌ emojis
2. **Test with API down** - Verify error messages
3. **Check MongoDB after operations** - Confirm persistence
4. **Use agent_id filter** - When querying documents
5. **Watch background jobs** - Document processing is async

## 📞 Support

- Full audit: `ADMIN_DASHBOARD_AUDIT_COMPLETE.md`
- Architecture: `AGENTS.md`
- API docs: `docs/api/API_DOCUMENTATION.md`
