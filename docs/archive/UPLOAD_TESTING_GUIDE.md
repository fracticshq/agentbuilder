# 🧪 Knowledge Base Upload Testing Guide

## ✅ Status: Ready to Test!

All components are built and servers are running. Here's how to test the complete upload flow.

---

## 🚀 Quick Start

### 1. Verify Servers Running

```bash
# Check all servers
ps aux | grep -E "(react-scripts|uvicorn)" | grep -v grep

# Expected output:
# - Admin (port 3000): react-scripts start
# - API (port 8000): uvicorn app.main:app
```

### 2. Access Admin Dashboard

Open browser: **http://localhost:3000/agents**

---

## 📋 Test Flow: Upload Products

### Step-by-Step Instructions

1. **Navigate to Knowledge Base**
   - Click "Create Agent" (or edit existing agent)
   - Go to "Step 4: Knowledge Base"
   - You should see:
     - "Upload Document with Structured Metadata" button
     - "Uploaded Documents" section (empty initially)

2. **Start Upload Wizard**
   - Click the **Upload Document** button
   - Wizard opens with 4 steps

3. **Step 1: Select Content Type**
   - Choose **"Product"**
   - Wizard auto-advances to Step 2

4. **Step 2: Upload JSON**
   - **Option A: Paste JSON**
     ```json
     [
       {
         "sku": "FAU-001",
         "name": "Chrome Faucet",
         "price": 299900,
         "category": "Faucets",
         "image_url": "https://example.com/faucet.jpg",
         "in_stock": true,
         "features": ["Chrome finish", "Water-saving", "Easy install"]
       },
       {
         "sku": "SHW-002",
         "name": "Rain Shower Head",
         "price": 599900,
         "category": "Showers",
         "in_stock": true,
         "features": ["8-inch diameter", "Anti-clog nozzles"]
       }
     ]
     ```
   
   - **Option B: Upload File**
     - Create a `.json` file with the above content
     - Click "Upload File" tab
     - Select your file
   
   - Click **Continue** → Wizard auto-advances to Step 3

5. **Step 3: Field Mapping** ⭐ KEY FEATURE
   
   Auto-mapping should already be done! But verify:
   
   - **SKU**: Should show "sku" (mapped)
   - **Name**: Should show "name" (mapped)
   - **Price**: Should show "price" (mapped)
   - **Currency**: ❗ **Test Fixed Value Here!**
     - Click "Use Fixed Value" button
     - Enter: `INR`
     - This sets currency="INR" for ALL items
   - **Category**: Should show "category" (mapped)
   - **Image URL**: Should show "image_url" (optional)
   - **Product URL**: Can skip (optional)
   - **In Stock**: Should show "in_stock" (mapped)
   - **Features**: Should show "features" (mapped)
   
   - Click **Continue** → Wizard auto-advances to Step 4

6. **Step 4: Review & Upload**
   
   Verify the preview:
   - See 2 items listed
   - Check currency shows "INR" (from fixed value)
   - Check all fields mapped correctly
   
   Click **Upload** 🚀

7. **Check Results**
   
   **Browser Console** (F12 → Console):
   ```javascript
   // Should see:
   {
     success: true,
     job_id: "...",
     message: "Upload job started",
     items_count: 2,
     status: "processing"
   }
   ```
   
   **Documents List** (below wizard):
   - Should auto-refresh and show your uploaded document
   - Content type badge: "product" (blue)
   - Chunks count: ~2 chunks
   - Preview shows: SKU, Price (INR), Category

---

## 🧪 Test Scenarios

### Scenario A: Products with Fixed Currency ✅
**Purpose**: Test fixed value mapping when JSON doesn't have currency

```json
[
  {
    "sku": "TEST-001",
    "name": "Test Product",
    "price": 100000,
    "category": "Testing",
    "in_stock": true,
    "features": ["Test feature"]
  }
]
```

**Field Mapping**:
- Use **"Use Fixed Value"** for Currency → `INR`
- All other fields auto-map

**Expected**: Currency="INR" applied to all items

---

### Scenario B: Dealers ✅
**Purpose**: Test dealer upload flow

```json
[
  {
    "dealer_id": "DLR-001",
    "name": "Mumbai Bathware Store",
    "city": "Mumbai",
    "state": "Maharashtra",
    "phone": "+91-22-1234567",
    "email": "mumbai@bathware.com",
    "address": "123 Main St, Mumbai"
  }
]
```

**Steps**:
1. Select content type: **Dealer**
2. Upload JSON (auto-advance)
3. Field mapping shows dealer fields
4. Upload

---

### Scenario C: FAQ (No Mapping) ✅
**Purpose**: Test auto-skip for content types that don't need mapping

```json
[
  {
    "question": "What is the warranty period?",
    "answer": "All products come with 5-year warranty",
    "category": "warranty"
  }
]
```

**Steps**:
1. Select content type: **FAQ**
2. Upload JSON
3. **Wizard skips Step 3** (no field mapper!)
4. Goes directly to Review & Upload

---

### Scenario D: Large Dataset 📊
**Purpose**: Test bulk upload performance

```bash
# Create 100 products
cat > test_large.json << 'EOF'
[
  $(for i in {1..100}; do
    echo "{\"sku\":\"BULK-$i\",\"name\":\"Product $i\",\"price\":$((i*1000)),\"currency\":\"INR\",\"category\":\"Bulk\",\"in_stock\":true,\"features\":[\"Feature 1\"]}"
    [[ $i -lt 100 ]] && echo ","
  done)
]
EOF
```

Upload this file and check:
- Processing time
- All 100 items appear in MongoDB
- Chunks created (~100 chunks)

---

## 🔍 Verification Checklist

### Frontend (Browser)
- [ ] Wizard opens successfully
- [ ] Content type selection works
- [ ] JSON validates correctly
- [ ] Field mapper shows all fields
- [ ] Fixed value mode works
- [ ] Auto-progression works
- [ ] Upload succeeds (no errors)
- [ ] Documents list refreshes
- [ ] New document appears

### Backend (API Logs)
```bash
# Check API logs
tail -f /tmp/api.log

# Should see:
# - Bulk upload request received
# - Validation passed
# - Job created
# - Processing started
```

### Database (MongoDB)
```bash
# Query uploaded documents
mongosh "mongodb+srv://..." --eval "
  use agent_builder;
  db.knowledge_base.find({
    'metadata.brand_id': 'default',
    'content_type': 'product'
  }).pretty()
"

# Check for:
# - doc_id field present
# - content_type = 'product'
# - product_data.currency = 'INR' (if you used fixed value)
# - product_data.sku matches your JSON
# - chunks created
```

---

## 🗑️ Test Delete Functionality

1. **Find Document in List**
   - Uploaded documents show below wizard
   - Each has a red **Delete** button

2. **Delete Document**
   - Click **Delete** on any document
   - Confirm deletion in dialog
   - Document disappears from list
   - Check MongoDB: all chunks with that doc_id removed

3. **Verify**
   ```bash
   # Check chunks count decreased
   db.knowledge_base.countDocuments({'doc_id': 'your-doc-id'})
   # Should return 0
   ```

---

## 🐛 Troubleshooting

### "Error: Validation error"
**Cause**: Required fields missing or wrong format

**Fix**:
1. Check field mapping - all required fields mapped?
2. Check console for details: `F12 → Console`
3. Verify JSON structure matches expected format

### "Failed to load documents"
**Cause**: API not responding or MongoDB connection issue

**Fix**:
```bash
# Check API running
curl http://localhost:8000/health

# Check API logs
tail -20 /tmp/api.log

# Restart API if needed
pkill -f "uvicorn"
cd apps/api && python run.py > /tmp/api.log 2>&1 &
```

### Upload succeeds but no documents shown
**Cause**: brand_id mismatch or MongoDB query issue

**Fix**:
1. Check browser console for job_id
2. Query MongoDB directly for that job
3. Verify brand_id in metadata matches what you're querying

### Delete button doesn't work
**Cause**: API delete endpoint not receiving brand_id

**Fix**: Already fixed in code! brandId is passed in query params.

---

## 📊 Expected Performance

| Metric | Target | Actual |
|--------|--------|--------|
| Upload validation | < 1s | ? |
| Job creation | < 500ms | ? |
| Processing 10 items | < 5s | ? |
| Processing 100 items | < 30s | ? |
| Delete operation | < 1s | ? |
| List documents | < 1s | ? |

Test and fill in "Actual" column!

---

## 🎯 What to Test Next

After basic upload works:

1. **Test all content types**: product, dealer, faq, office, category, guide
2. **Test field mapping modes**: 
   - Map from JSON
   - Use Fixed Value
   - Skip (optional fields only)
3. **Test error cases**:
   - Invalid JSON
   - Missing required fields
   - Empty arrays
   - Very large files (>10MB)
4. **Test MongoDB queries**:
   - Filter by content_type
   - Search by SKU
   - Search by category
   - Price range queries
5. **Test RAG retrieval**:
   - Query API with product questions
   - Verify correct chunks retrieved
   - Check citation accuracy

---

## 📝 Test Report Template

```markdown
# Upload Test Report

**Date**: 2025-10-25
**Tester**: [Your name]
**Environment**: Local dev

## Test Results

### Scenario A: Products with Fixed Currency
- Status: ✅ Pass / ❌ Fail
- Upload time: X seconds
- Items uploaded: X / X
- Issues: None / [describe]

### Scenario B: Dealers
- Status: ✅ Pass / ❌ Fail
- Upload time: X seconds
- Items uploaded: X / X
- Issues: None / [describe]

### Scenario C: FAQ (No Mapping)
- Status: ✅ Pass / ❌ Fail
- Upload time: X seconds
- Auto-skip worked: Yes / No
- Issues: None / [describe]

### Delete Functionality
- Status: ✅ Pass / ❌ Fail
- Confirmation dialog shown: Yes / No
- Chunks deleted: X
- Issues: None / [describe]

## Overall Status: ✅ All Pass / ⚠️ Some Issues / ❌ Failed

## Notes:
[Any observations, suggestions, or issues found]
```

---

## 🎉 Success Criteria

The upload system is working correctly if:

✅ All 6 content types can be uploaded
✅ Field mapping works for products and dealers
✅ Fixed value mode correctly applies to all items
✅ FAQ/office/category/guide skip field mapper
✅ Documents appear in list after upload
✅ Delete removes all chunks for that doc_id
✅ MongoDB contains correct data structure
✅ No validation errors with valid data
✅ Upload completes in < 30s for 100 items

---

**Ready to test! Start with Scenario A (Products with Fixed Currency) and let me know the results!** 🚀
