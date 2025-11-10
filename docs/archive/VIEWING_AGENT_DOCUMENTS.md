# 📄 Viewing Previously Uploaded Documents in Agent Dashboard

## ✅ Already Implemented!

The documents list is **already integrated** into both create and edit modes of the agent wizard.

---

## 🎯 How to View Documents

### Option 1: Edit Existing Agent

1. **Go to Agents List**
   ```
   http://localhost:3000/agents
   ```

2. **Click "Edit" on Any Agent**
   - Click the "✏️ Edit Agent" button on any agent card
   - OR click the agent name to view details, then click "✏️ Edit Agent"

3. **Navigate to Knowledge Base Step**
   - Click "Step 4: Knowledge Base" in the wizard navigation
   - OR click "Next" to advance through steps

4. **View Documents List**
   - Below the "Upload Document" button, you'll see:
     - **"Uploaded Documents"** section
     - List of all documents uploaded for this agent
     - Each document shows:
       - ✅ Document title/ID
       - ✅ Content type badge (color-coded)
       - ✅ Upload date and time
       - ✅ Number of chunks
       - ✅ Metadata preview (SKU/price for products, city/phone for dealers)
       - ✅ Delete button

---

### Option 2: During Agent Creation

1. **Create New Agent**
   ```
   http://localhost:3000/agents → Click "Create New Agent"
   ```

2. **Upload Documents in Step 4**
   - Fill in Steps 1-3 (or skip with placeholder data)
   - Go to Step 4: Knowledge Base
   - Upload some documents

3. **Documents Appear Immediately**
   - After upload completes, the documents list auto-refreshes
   - Newly uploaded documents appear in the list below

---

## 🔍 What You'll See

### Empty State (No Documents)
```
┌─────────────────────────────────────────┐
│  📄  No documents                       │
│                                         │
│  Upload your first document to get     │
│  started.                               │
└─────────────────────────────────────────┘
```

### With Documents
```
┌─────────────────────────────────────────────────────────────┐
│  Uploaded Documents                           [🔄 Refresh]  │
│  2 documents in knowledge base                              │
├─────────────────────────────────────────────────────────────┤
│  📄  Product Catalog 2024        [product]                  │
│      Uploaded: Oct 25, 2025, 2:30 PM • 45 chunks            │
│      SKU: FAU-001 | Price: INR 2999 | Category: Faucets     │
│                                              [🗑️ Delete]     │
├─────────────────────────────────────────────────────────────┤
│  📄  Dealer Network List         [dealer]                   │
│      Uploaded: Oct 25, 2025, 1:15 PM • 12 chunks            │
│      ID: DLR-001 | City: Mumbai | Phone: +91-22-1234567     │
│                                              [🗑️ Delete]     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎨 Content Type Badge Colors

The content type badges are color-coded for easy identification:

| Content Type | Badge Color | Example |
|--------------|-------------|---------|
| **product** | 🔵 Blue | `bg-blue-100 text-blue-800` |
| **dealer** | 🟢 Green | `bg-green-100 text-green-800` |
| **faq** | 🟣 Purple | `bg-purple-100 text-purple-800` |
| **office** | 🟡 Yellow | `bg-yellow-100 text-yellow-800` |
| **category** | 🩷 Pink | `bg-pink-100 text-pink-800` |
| **guide** | 🔵 Indigo | `bg-indigo-100 text-indigo-800` |

---

## 🔄 Auto-Refresh Behavior

The documents list automatically refreshes in these cases:

1. **After Upload Completes**
   - When you complete the upload wizard
   - New document appears in the list immediately

2. **After Delete**
   - When you delete a document
   - Document disappears from the list immediately

3. **Manual Refresh**
   - Click the "🔄 Refresh" button in the top-right
   - Reloads all documents from MongoDB

4. **Component Remount**
   - When you navigate back to Step 4
   - When you switch between agents

---

## 🗑️ Delete Functionality

### How to Delete a Document

1. **Find the Document** in the list
2. **Click "Delete" Button** (red button on the right)
3. **Confirm Deletion** in the browser dialog:
   ```
   Are you sure you want to delete "Product Catalog 2024"? 
   This will remove all associated chunks and cannot be undone.
   ```
4. **Document Removed**
   - All chunks with that `doc_id` are deleted from MongoDB
   - Document disappears from the list
   - List auto-refreshes

### What Gets Deleted

- ✅ All chunks for that document (from MongoDB `knowledge_base` collection)
- ✅ All embeddings for those chunks
- ✅ All metadata associated with the document

### What Doesn't Get Deleted

- ❌ Original uploaded file (not stored)
- ❌ Upload job history
- ❌ Other documents

---

## 🧪 Testing Guide

### Test Scenario 1: View Documents in Edit Mode

1. **Create a test agent** (if you don't have one)
2. **Upload some documents** in Step 4
3. **Save/Complete the wizard**
4. **Go back to Agents list** (`/agents`)
5. **Click "Edit" on the agent** you just created
6. **Navigate to Step 4**
7. **Verify**: You should see the documents you uploaded

### Test Scenario 2: Upload & View in Create Mode

1. **Create new agent** (`/agents/create`)
2. **Fill in Steps 1-3** with test data
3. **Go to Step 4**
4. **Upload a document** (use test JSON from UPLOAD_TESTING_GUIDE.md)
5. **Verify**: After upload, document appears in list below

### Test Scenario 3: Delete Document

1. **Edit an agent** with documents
2. **Go to Step 4**
3. **Click "Delete"** on any document
4. **Confirm** the dialog
5. **Verify**: Document disappears from list
6. **Check MongoDB** to confirm chunks deleted

---

## 🔧 Technical Details

### How It Works

**Component Structure**:
```
StepKnowledgeBase.tsx
├── Upload Button (shows DocumentUploadWizard)
└── DocumentsList Component
    ├── Fetches: GET /api/v1/knowledge/documents?brand_id={agentId}
    ├── Groups by: doc_id (not individual chunks)
    ├── Displays: Metadata preview based on content_type
    └── Delete: DELETE /api/v1/knowledge/documents/{doc_id}?brand_id={agentId}
```

**Brand ID Logic**:
```typescript
brandId={brandId || agentId || 'default'}
```

- **Creating agent** (no `agentId`): Uses `'default'`
- **Editing agent** (has `agentId`): Uses agent's ID
- **Brand override** (if `brandId` provided): Uses `brandId`

**API Endpoints Used**:
- `GET /api/v1/knowledge/documents?brand_id={id}` - List documents
- `DELETE /api/v1/knowledge/documents/{doc_id}?brand_id={id}` - Delete document

**MongoDB Query**:
```javascript
// Backend aggregation pipeline
{
  "$match": { "metadata.brand_id": agentId }
},
{
  "$group": {
    "_id": "$doc_id",
    "title": { "$first": "$title" },
    "content_type": { "$first": "$content_type" },
    "created_at": { "$first": "$metadata.created_at" },
    "chunks_count": { "$sum": 1 },
    "product_data": { "$first": "$product_data" },
    "dealer_data": { "$first": "$dealer_data" }
  }
}
```

This groups chunks by `doc_id` so you see each **document** once, not every chunk.

---

## 🐛 Troubleshooting

### "No documents" shown but I uploaded some

**Possible Causes**:
1. **Different brand_id** - Documents uploaded with different brand_id than current agent
2. **MongoDB connection issue** - Check API logs
3. **Backend error** - Check browser console (F12)

**How to Fix**:
```bash
# 1. Check API logs
tail -f /tmp/api.log

# 2. Check browser console
# F12 → Console tab → Look for errors

# 3. Verify MongoDB data
mongosh "mongodb+srv://..." --eval "
  db.knowledge_base.aggregate([
    { \$match: { 'metadata.brand_id': 'your-agent-id' } },
    { \$group: { _id: '\$doc_id', count: { \$sum: 1 } } }
  ])
"
```

### Delete button doesn't work

**Check**:
1. Browser console for errors (F12)
2. Network tab for failed DELETE request
3. API logs for backend errors

### Documents list not refreshing

**Try**:
1. Click the **🔄 Refresh** button
2. Navigate away and back to Step 4
3. Hard refresh browser (Cmd+Shift+R on Mac)

---

## ✅ Success Checklist

When viewing documents in edit mode, you should see:

- [ ] "Uploaded Documents" heading
- [ ] Count of documents (e.g., "2 documents in knowledge base")
- [ ] Refresh button in top-right
- [ ] Each document showing:
  - [ ] Title or doc_id
  - [ ] Content type badge (colored)
  - [ ] Upload timestamp
  - [ ] Chunks count
  - [ ] Metadata preview (if product/dealer)
  - [ ] Delete button
- [ ] Empty state if no documents
- [ ] Loading spinner while fetching
- [ ] Error message if fetch fails

---

## 📊 Expected Behavior

| Scenario | Expected Result |
|----------|----------------|
| Edit agent with documents | Documents list shows all uploads |
| Edit agent without documents | Shows empty state |
| Upload new document | Auto-refreshes and shows new doc |
| Delete document | Removes from list immediately |
| Click refresh | Reloads latest from MongoDB |
| Network error | Shows error with retry button |
| Multiple content types | Different color badges |
| Products | Shows SKU, price, category |
| Dealers | Shows ID, city, phone |

---

## 🎉 You're All Set!

The documents list is **already working** in both create and edit modes. Just:

1. Edit an existing agent
2. Go to Step 4: Knowledge Base
3. Scroll down to see the "Uploaded Documents" section

**No additional setup needed!** 🚀

---

## 📝 Next Steps

After viewing documents:

1. **Test uploading** a new document in edit mode
2. **Test deleting** an existing document
3. **Verify MongoDB** chunks are properly grouped
4. **Check performance** with many documents (pagination coming soon)
5. **Add MongoDB indexes** for faster queries (see todo list)

---

**Need Help?**
- Check browser console (F12) for errors
- Check API logs: `tail -f /tmp/api.log`
- Verify MongoDB connection in API startup logs
