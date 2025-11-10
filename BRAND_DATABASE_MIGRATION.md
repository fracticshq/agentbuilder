# Brand-Specific Database Architecture - COMPLETE ✅

**Date**: October 27, 2024  
**Changes**: Migrated from single database to brand-specific databases

---

## 🏗️ New Architecture

### Database Isolation

Each brand/agent now has its **own dedicated MongoDB database**:

```
MongoDB Atlas Cluster
├── essco-bathware/               ← Essco brand database
│   ├── knowledge_base           ← Product chunks, embeddings
│   ├── conversations            ← Chat history
│   ├── episodic_memory          ← User facts
│   └── ...
│
├── brand-2/                      ← Another brand
│   ├── knowledge_base
│   └── ...
│
└── brand-3/
    └── ...
```

**Benefits:**
- ✅ **Complete data isolation** per brand
- ✅ **Independent scaling** per brand
- ✅ **Easier backup/restore** per brand
- ✅ **Better security** (no cross-brand data leakage)
- ✅ **Cleaner data management**

---

## 🔧 Changes Made

### 1. Knowledge Service (`apps/api/app/services/knowledge_service.py`)

**Added brand-specific database support:**

```python
def _get_brand_database(self, brand_id: str):
    """Get brand-specific database (use brand_id as database name)."""
    if brand_id not in self.db_cache:
        mongo_client = connection_manager.mongodb_client
        db_name = brand_id.replace('.', '_')[:63]  # Sanitize for MongoDB
        self.db_cache[brand_id] = mongo_client[db_name]
    return self.db_cache[brand_id]

async def _ensure_connection(self, brand_id: Optional[str] = None):
    """Ensure MongoDB connection for specific brand."""
    if brand_id:
        self.db = self._get_brand_database(brand_id)  # Brand-specific DB
        self.collection = self.db["knowledge_base"]
```

**Updated all methods to pass brand_id:**
- `process_document_upload()` → `await self._ensure_connection(brand_id)`
- `process_bulk_upload()` → `await self._ensure_connection(brand_id)`
- `list_documents()` → `await self._ensure_connection(brand_id)`
- `delete_document()` → `await self._ensure_connection(brand_id)`

---

### 2. Atlas Vector Search (`packages/retrieval/src/retrieval/vector/atlas_search.py`)

**Added brand_id parameter:**

```python
def __init__(
    self,
    collection_name: str = "knowledge_base",
    index_name: str = "vector_index",
    voyage_client: Optional[VoyageClient] = None,
    brand_id: Optional[str] = None  # NEW: Brand ID for database isolation
):
    # Use brand_id as database name
    if brand_id:
        db_name = brand_id.replace('.', '_')[:63]
    else:
        db_name = os.getenv("MONGODB_DATABASE", "agent-builder")
    
    self.db = self.client[db_name]  # Brand-specific database
    self.brand_id = brand_id
```

---

### 3. BM25 Search (`packages/retrieval/src/retrieval/bm25/text_search.py`)

**Added brand_id parameter:**

```python
def __init__(
    self,
    collection_name: str = "knowledge_base",
    text_index_name: str = "text_index",
    brand_id: Optional[str] = None  # NEW: Brand ID for database isolation
):
    # Use brand_id as database name
    if brand_id:
        db_name = brand_id.replace('.', '_')[:63]
    else:
        db_name = os.getenv("MONGODB_DATABASE", "agent-builder")
    
    self.db = self.client[db_name]  # Brand-specific database
    self.brand_id = brand_id
```

---

### 4. Retrieval Pipeline (`packages/retrieval/src/retrieval/pipeline.py`)

**Pass brand_id to search components:**

```python
def __init__(
    self,
    config: Optional[RetrievalConfig] = None,
    brand_id: Optional[str] = None
):
    self.brand_id = brand_id
    
    # Initialize with brand_id
    self.vector_search = AtlasVectorSearch(brand_id=brand_id)
    self.bm25_search = BM25Search(brand_id=brand_id)
```

---

## 📊 MongoDB Structure

### Before (Single Database)

```
agent-builder/                    ← One database for all
├── knowledge_base (6330 docs)    ← Mixed brands
│   ├── agent_id: "essco"
│   ├── agent_id: "brand-2"
│   └── agent_id: "brand-3"
└── conversations (mixed)
```

**Problems:**
- ❌ All brands share one database
- ❌ Difficult to query per brand
- ❌ No data isolation
- ❌ Scaling issues

### After (Brand-Specific Databases)

```
essco-bathware/                   ← Essco's database
├── knowledge_base (379 docs)     ← Only Essco products
│   ├── content_type: "product"
│   ├── product_data: {...}
│   └── embedding: [...]
└── conversations (Essco only)

brand-2/                          ← Brand 2's database
├── knowledge_base
└── conversations

brand-3/                          ← Brand 3's database
├── knowledge_base
└── conversations
```

**Benefits:**
- ✅ Complete isolation
- ✅ Fast queries (no filtering needed)
- ✅ Independent backups
- ✅ Clear ownership

---

## 🗑️ Data Cleanup

Dropped all old data to start fresh:

```bash
python3 drop_all_data.py
```

**Dropped databases:**
- `agent-builder` (6330 mixed documents)
- `sample_mflix` (sample data)

---

## 🔄 Migration Steps

### For Essco Bathware

1. ✅ **Drop old data** - Completed
2. ✅ **Update code** for brand-specific databases - Completed
3. ⏳ **Re-upload products** via Admin Dashboard
   - Brand ID: `essco-bathware`
   - Content Type: `product`
   - Database created: `essco_bathware`
4. ⏳ **Verify** chunks have correct structure
5. ⏳ **Test** product cards in widget

---

## 📋 Next Steps

### 1. Re-upload Product Data

Use Admin Dashboard:
1. Go to: http://localhost:3000
2. Knowledge Base → Upload Document
3. Select: "Product" content type
4. Upload: `product_data.json`
5. Map fields:
   - SKU → sku
   - Name → name
   - Price → price
   - Currency → currency (Fixed: "INR")
   - Category → category
   - In Stock → in_stock (Fixed: true)
   - Features → features
   - Image URL → image_url
   - Product URL → product_url

### 2. Verify Upload

```bash
python3 -c "
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv('apps/api/.env')
client = MongoClient(os.getenv('MONGODB_URI'))

# Check Essco database
db = client['essco_bathware']
kb = db['knowledge_base']

total = kb.count_documents({})
products = kb.count_documents({
    'content_type': 'product',
    'product_data': {'\$exists': True, '\$ne': None}
})

print(f'Total chunks: {total}')
print(f'Product chunks with product_data: {products}')

if products > 0:
    sample = kb.find_one({'content_type': 'product'})
    print(f\"Sample SKU: {sample['product_data']['sku']}\")
    print(f\"Sample Name: {sample['product_data']['name']}\")
"
```

**Expected Output:**
```
Total chunks: 379
Product chunks with product_data: 379
Sample SKU: ECS-WHT-551PNPP184NLZ
Sample Name: EWC P Trap
```

### 3. Test Product Cards

1. Open widget: http://localhost:5173
2. Query: "show me faucets under 5000"
3. Verify: Product cards render with images, prices, SKUs

---

## 🎯 Benefits

### Data Isolation
- Each brand's data is completely separate
- No risk of cross-brand data leakage
- Easy to manage per-brand permissions

### Performance
- Faster queries (no cross-brand filtering)
- Better indexing (smaller datasets per database)
- Independent scaling per brand

### Management
- Easy backup/restore per brand
- Clear data ownership
- Simple compliance (GDPR, data residency)

### Development
- Cleaner codebase
- Easier testing (per-brand test databases)
- Better debugging (isolated data)

---

## 🔍 Verification Checklist

- [x] Drop all old data
- [x] Update knowledge_service.py
- [x] Update atlas_search.py
- [x] Update bm25/text_search.py
- [x] Update retrieval pipeline
- [x] Restart API server
- [ ] Re-upload product data
- [ ] Verify chunks structure
- [ ] Test product cards
- [ ] Test dealer cards
- [ ] Test retrieval performance

---

**Status**: Architecture migration complete, ready for data upload ✅
