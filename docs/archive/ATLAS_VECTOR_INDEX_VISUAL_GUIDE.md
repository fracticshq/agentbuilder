# MongoDB Atlas Vector Search Index - Visual Editor Guide

## ⚠️ RECOMMENDED: Use Visual Editor (Not JSON Editor)

The Visual Editor is much more reliable than the JSON Editor. Follow these exact steps:

---

## Step-by-Step Instructions

### 1. Navigate to Atlas Search
- Go to your MongoDB Atlas cluster
- Click **"Search"** in the left sidebar
- Click **"Create Search Index"**

### 2. Select Configuration Method
- Choose **"Visual Editor"** (NOT JSON Editor)
- Click **"Next"**

### 3. Select Database & Collection
- **Database**: `agent-builder`
- **Collection**: `knowledge_base`
- Click **"Next"**

### 4. Name Your Index
- **Index Name**: `vector_index`
- Click **"Next"**

### 5. Configure Vector Field (CRITICAL STEP)

In the Visual Editor:

#### Add Vector Field:
1. Click **"Add Field"**
2. **Field Name**: `embeddings`
3. **Data Type**: Select **"knnVector"** from dropdown
4. **Dimensions**: `1024`
5. **Similarity Function**: Select **"cosine"**

#### Add Filter Fields (Optional but Recommended):
6. Click **"Add Field"** again
7. **Field Name**: `agent_id`
8. **Data Type**: Select **"token"**

9. Click **"Add Field"** again
10. **Field Name**: `doc_id`
11. **Data Type**: Select **"token"**

### 6. Refine Your Index
- Leave **"Dynamic Mapping"** turned **OFF** (disabled)
- Review your configuration:
  - ✅ `embeddings` field → knnVector, 1024 dimensions, cosine
  - ✅ `agent_id` field → token
  - ✅ `doc_id` field → token
- Click **"Next"**

### 7. Create Index
- Review the final configuration
- Click **"Create Search Index"**

### 8. Wait for Index to Build
- Status will show **"Initial Sync"** (2-5 minutes)
- Wait until status changes to **"Active"**
- ✅ **DONE!** Your vector search is now enabled

---

## Alternative: Atlas CLI (Advanced)

If the UI is giving you trouble, you can create the index via Atlas CLI:

```bash
# Install Atlas CLI (if not already installed)
brew install mongodb-atlas

# Login
atlas auth login

# Create the index
atlas clusters search indexes create \
  --clusterName <YOUR_CLUSTER_NAME> \
  --file /tmp/atlas_vector_index.json
```

Create `/tmp/atlas_vector_index.json`:
```json
{
  "name": "vector_index",
  "type": "vectorSearch",
  "collectionName": "knowledge_base",
  "database": "agent-builder",
  "fields": [
    {
      "type": "vector",
      "path": "embeddings",
      "numDimensions": 1024,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "agent_id"
    },
    {
      "type": "filter",
      "path": "doc_id"
    }
  ]
}
```

---

## Verification

After index is **Active**, test it:

```bash
# From your project root
curl -s -X POST http://localhost:8000/api/v1/messages/ \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Show me faucets under 5000 rupees",
    "user_id": "test-user-vector",
    "conversation_id": "test-vector-001",
    "agent_id": "f168131d-7833-4f9c-ac8e-8a19b22c16f3"
  }' | python3 -m json.tool
```

Check the API logs - you should see:
- ✅ `Vector search completed` (not "Vector search error")
- ✅ `Retrieved 10+ chunks` (not just 1)
- ✅ `context_used > 5` in the response

---

## Troubleshooting

### "Index creation failed"
- Make sure you selected **"knnVector"** not "vector"
- Verify dimensions = 1024 (not 1536 or other)
- Ensure similarity = "cosine"

### "Invalid field type"
- Use **Visual Editor**, not JSON Editor
- The JSON Editor syntax varies between Atlas versions

### "Cannot find collection"
- Verify database name is exactly: `agent-builder`
- Verify collection name is exactly: `knowledge_base`
- Check that the collection has documents (should have 4,901)

---

## What This Enables

With the vector index active:
- ✅ **Semantic search** across all 4,901 document chunks
- ✅ **Hybrid retrieval**: BM25 text search + vector similarity search
- ✅ **Better answers**: Agent can find relevant products even with different wording
- ✅ **Full RAG pipeline**: 50 candidates → 12 reranked → 10 used in response

**This is the final piece to make your RAG system fully functional!**
