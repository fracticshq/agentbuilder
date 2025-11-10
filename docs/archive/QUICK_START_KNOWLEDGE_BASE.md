# Quick Start: Re-Upload Your Knowledge Base Files

## 🔧 Step 1: Configure Environment (2 minutes)

Add your API keys to `.env` file:

```bash
cd /Users/anantmendiratta/Desktop/anant2/agent-builder

# Create .env file with your keys
cat > .env << 'EOF'
VOYAGE_API_KEY=pa-YOUR-VOYAGE-KEY-HERE
OPENAI_API_KEY=sk-proj-YOUR-OPENAI-KEY-HERE
MONGODB_URI=mongodb+srv://YOUR-MONGODB-URI
REDIS_URL=redis://localhost:6379
EOF
```

## 🚀 Step 2: Restart API Server (1 minute)

```bash
# Kill old process
lsof -ti :8000 | xargs kill -9

# Start with new environment
nohup python3 apps/api/run.py > /tmp/api.log 2>&1 & echo $! > logs/api.pid

# Verify it's running
sleep 3
curl http://localhost:8000/health
```

Expected: `{"status": "healthy", "service": "agent-builder-api"}`

## 📤 Step 3: Upload Your Files (2 minutes)

### Method A: Using cURL (Fastest)

```bash
# Navigate to your data directory
cd /path/to/your/json/files

# Upload all files at once
curl -X POST "http://localhost:8000/api/v1/ingest/documents?agent_id=f168131d-7833-4f9c-ac8e-8a19b22c16f3" \
  -F "files=@essco_faq.json" \
  -F "files=@product_data.json" \
  -F "files=@office_data.json" \
  -F "files=@dealers_data.json" \
  -F "files=@category_data.json" \
  -F "files=@area_representative_data.json"
```

### Method B: Using Admin Dashboard

1. Open: http://localhost:3000/agents/new
2. Fill in the wizard steps
3. At Step 4 (Knowledge Base), drag and drop your 6 JSON files
4. Click "Deploy Agent"

## ✅ Step 4: Verify Upload (1 minute)

Check documents were saved:

```bash
curl "http://localhost:8000/api/v1/ingest/documents?agent_id=f168131d-7833-4f9c-ac8e-8a19b22c16f3" | python3 -m json.tool
```

Expected output:
```json
{
  "documents": [
    {
      "filename": "essco_faq.json",
      "chunks_count": 13,
      "agent_id": "f168131d-7833-4f9c-ac8e-8a19b22c16f3",
      ...
    },
    {
      "filename": "product_data.json",
      "chunks_count": 277,
      ...
    }
    // ... more files
  ],
  "count": 6
}
```

## 🔍 Step 5: Check Embeddings (1 minute)

Verify Voyage AI generated embeddings:

```bash
tail -100 /tmp/api.log | grep -i "voyage\|embedding"
```

Expected:
```
Generated embeddings dimensions=1024
Stored chunk in MongoDB chunk_id=...
```

---

## ⚠️ Troubleshooting

### Problem: "VOYAGE_API_KEY not set" in logs

**Solution:** Make sure you created the `.env` file in the project root and restarted the API server.

### Problem: Documents show count: 0

**Solution:** Check API logs for errors:
```bash
tail -50 /tmp/api.log | grep -i error
```

### Problem: MongoDB not connected

**Solution:** Verify your MONGODB_URI is correct in `.env` file.

### Problem: Upload succeeds but no embeddings

**Solution:** 
1. Check Voyage API key is valid
2. Check internet connection
3. Look for Voyage API errors in logs:
   ```bash
   tail -100 /tmp/api.log | grep -i "voyage api error"
   ```

---

## 📊 What Happens During Upload

1. ✅ Files are uploaded via HTTP POST
2. ✅ Text is extracted from JSON
3. ✅ Content is chunked (500 chars per chunk, 50 char overlap)
4. ✅ **Voyage AI generates 1024-dim embeddings** for each chunk
5. ✅ **Chunks stored in MongoDB** `knowledge_chunks` collection
6. ✅ Linked to your agent ID
7. ✅ Ready for RAG retrieval!

---

## Total Time: ~7 minutes

1. Configure .env - 2 min
2. Restart API - 1 min  
3. Upload files - 2 min
4. Verify - 1 min
5. Check embeddings - 1 min

**Your knowledge base will be ready to use!** 🎉
