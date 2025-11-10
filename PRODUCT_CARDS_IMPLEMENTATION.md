# 🎯 Product Cards Implementation Plan

**Status**: 📋 Ready for Implementation  
**Compliance**: ✅ Follows AGENTS.md Architecture  
**Approach**: Enhanced knowledge_base collection (no new collections)

---

## 📊 Current System Status

### ✅ What We Have (Working)
1. **Knowledge Base Collection** (`knowledge_base`) in MongoDB
   - Stores document chunks with embeddings
   - Vector search enabled (MongoDB Atlas Vector Search)
   - Voyage AI embeddings (1024 dimensions)
   
2. **Retrieval Pipeline** (`packages/retrieval/src/retrieval/pipeline.py`)
   - Vector Search (MongoDB Atlas)
   - BM25 Text Search
   - RRF Fusion (~top 50)
   - Cross-encoder Rerank (top 12)
   - Brand/Page Boosts
   - Deduplication (MinHash)

3. **Admin Dashboard Upload**
   - Bulk JSON upload working
   - Field mapping for products/dealers
   - Type parsing (boolean, array, number) ✅ JUST FIXED
   
4. **Streaming Responses**
   - WebSockets + SSE
   - Token-level streaming
   - Citations support

### ❌ What's Missing (To Build)

1. **Structured Metadata in KB**
   - `content_type` field (product, dealer, faq, office, category, guide)
   - `product_data` field (SKU, price, features, etc.)
   - `dealer_data` field (ID, location, contact)
   
2. **Content-Type Aware Retrieval**
   - Filter by `content_type` during search
   - Extract structured data from chunks
   - Build product-specific context

3. **Grounded Product Prompts**
   - Inject structured JSON into prompts
   - Forbid LLM from inventing SKUs/prices
   - Validate responses against catalog

4. **Product Card UI Components**
   - Widget product card display
   - Dealer card display
   - Citation with structured data

---

## 🏗️ Implementation Phases

### Phase 1: Enhance Knowledge Base Schema (3 days)

#### 1.1 Update MongoDB Schema

**File**: Extend existing `knowledge_base` collection

**New Fields** (backward compatible):
```javascript
{
  "_id": ObjectId("..."),
  "job_id": "uuid",
  "filename": "product_data.json",
  "agent_id": "agent-uuid",
  "content": "chunk text...",
  "embeddings": [0.123, ...],  // Existing
  
  // ✨ NEW FIELDS (Phase 1)
  "content_type": "product",   // product | dealer | faq | office | category | guide
  
  "product_data": {            // Only when content_type="product"
    "sku": "FAU-001",
    "name": "Chrome Faucet",
    "price": 299900,           // Integer (paise)
    "currency": "INR",
    "category": "faucets",
    "image_url": "https://...",
    "product_url": "https://...",
    "in_stock": true,
    "features": ["chrome", "ceramic disc"]
  },
  
  "dealer_data": {             // Only when content_type="dealer"
    "dealer_id": "DLR-001",
    "name": "Mumbai Store",
    "city": "Mumbai",
    "state": "Maharashtra",
    "phone": "+91-22-1234567",
    "email": "store@example.com",
    "address": "123 Main St"
  },
  
  // Existing fields
  "metadata": {
    "filename": "...",
    "chunk_index": 0,
    "content_type": "application/json"
  },
  "created_at": ISODate
}
```

#### 1.2 Create Indexes

**File**: `scripts/setup_mongodb_indexes.py`

Add indexes:
```python
# Content type filtering (fast product/dealer queries)
await collection.create_index([
    ("content_type", 1),
    ("metadata.brand_id", 1)
], name="content_type_brand_idx")

# Product queries
await collection.create_index("product_data.sku", name="product_sku_idx")
await collection.create_index("product_data.category", name="product_category_idx")
await collection.create_index([
    ("product_data.category", 1),
    ("product_data.price", 1)
], name="product_filter_idx")

# Dealer queries
await collection.create_index("dealer_data.city", name="dealer_city_idx")
await collection.create_index("dealer_data.dealer_id", name="dealer_id_idx")
```

#### 1.3 Update Ingestion Service

**File**: `apps/api/app/services/ingestion_service.py`

Modify `process_document()` to extract and store structured data:

```python
async def process_document(
    self,
    file: UploadFile,
    job_id: str,
    agent_id: Optional[str] = None,
    content_type: Optional[str] = None  # NEW parameter
) -> Dict[str, Any]:
    """Process document and extract structured metadata."""
    
    # Existing chunking logic...
    chunks = self._chunk_text(text)
    
    # NEW: Extract structured data for products/dealers
    structured_data = None
    if content_type == "product":
        structured_data = self._extract_product_data(text)
    elif content_type == "dealer":
        structured_data = self._extract_dealer_data(text)
    
    # Store chunks with structured metadata
    for chunk in chunks:
        doc = {
            "job_id": job_id,
            "filename": file.filename,
            "agent_id": agent_id,
            "content": chunk["text"],
            "embeddings": embedding,
            "content_type": content_type,  # NEW
            "product_data": structured_data if content_type == "product" else None,  # NEW
            "dealer_data": structured_data if content_type == "dealer" else None,   # NEW
            "metadata": {...},
            "created_at": datetime.utcnow()
        }
        await collection.insert_one(doc)
```

Add helper methods:
```python
def _extract_product_data(self, text: str) -> Optional[Dict]:
    """Extract product fields from JSON/text."""
    try:
        data = json.loads(text) if text.strip().startswith('{') else {}
        return {
            "sku": data.get("sku"),
            "name": data.get("name"),
            "price": data.get("price"),
            "currency": data.get("currency", "INR"),
            "category": data.get("category"),
            "image_url": data.get("image_url"),
            "product_url": data.get("product_url"),
            "in_stock": data.get("in_stock", True),
            "features": data.get("features", [])
        }
    except:
        return None

def _extract_dealer_data(self, text: str) -> Optional[Dict]:
    """Extract dealer fields from JSON/text."""
    try:
        data = json.loads(text) if text.strip().startswith('{') else {}
        return {
            "dealer_id": data.get("dealer_id"),
            "name": data.get("name"),
            "city": data.get("city"),
            "state": data.get("state"),
            "phone": data.get("phone"),
            "email": data.get("email"),
            "address": data.get("address")
        }
    except:
        return None
```

#### 1.4 Update Admin Upload API

**File**: `apps/api/app/api/v1/endpoints/knowledge.py`

Modify bulk upload endpoint to accept `content_type`:

```python
@router.post("/bulk-upload")
async def bulk_upload_json(
    request: BulkUploadRequest,
    brand_id: str = Query(...),
    content_type: str = Query("other")  # NEW: product, dealer, faq, etc.
):
    """Bulk upload with content type awareness."""
    
    # Pass content_type to ingestion
    job_id = await ingestion_service.ingest_json_bulk(
        items=request.items,
        brand_id=brand_id,
        content_type=content_type  # NEW
    )
```

---

### Phase 2: Content-Type Aware Retrieval (1 week)

#### 2.1 Enhance Retrieval Pipeline

**File**: `packages/retrieval/src/retrieval/pipeline.py`

Add content-type filtering:

```python
class RetrievalPipeline:
    async def retrieve(
        self,
        query: str,
        brand_id: str,
        page_context: Optional[PageContext] = None,
        content_types: Optional[List[str]] = None  # NEW
    ) -> RetrievalContext:
        """Retrieve with content-type filtering."""
        
        # Detect query intent
        intent = self._detect_intent(query)
        
        # Filter by content type if specified
        filters = {"metadata.brand_id": brand_id}
        if content_types:
            filters["content_type"] = {"$in": content_types}
        
        # Vector search with filters
        vector_results = await self.vector_search.search(
            query=query,
            filters=filters,
            top_k=self.config.initial_retrieval_k
        )
        
        # BM25 search with filters
        bm25_results = await self.bm25_search.search(
            query=query,
            filters=filters,
            top_k=self.config.initial_retrieval_k
        )
        
        # Existing fusion + rerank...
        
        # NEW: Extract structured data
        enriched_chunks = self._enrich_with_structured_data(final_chunks)
        
        return RetrievalContext(
            chunks=enriched_chunks,
            intent=intent,
            # ...
        )
```

Add intent detection:
```python
def _detect_intent(self, query: str) -> str:
    """Detect if query is product/dealer search."""
    query_lower = query.lower()
    
    # Product indicators
    if any(word in query_lower for word in ['faucet', 'shower', 'price', 'under', 'buy', 'product']):
        return "product_search"
    
    # Dealer indicators
    if any(word in query_lower for word in ['store', 'dealer', 'near', 'location', 'city']):
        return "dealer_search"
    
    return "general"
```

Add structured data enrichment:
```python
def _enrich_with_structured_data(
    self,
    chunks: List[DocumentChunk]
) -> List[DocumentChunk]:
    """Attach product/dealer data to chunks."""
    for chunk in chunks:
        if chunk.metadata.get("content_type") == "product":
            chunk.product_data = chunk.raw_data.get("product_data")
        elif chunk.metadata.get("content_type") == "dealer":
            chunk.dealer_data = chunk.raw_data.get("dealer_data")
    return chunks
```

#### 2.2 Update Retrieval Types

**File**: `packages/retrieval/src/retrieval/types.py`

Add structured data to DocumentChunk:

```python
@dataclass
class DocumentChunk:
    content: str
    score: float
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None
    
    # NEW: Structured data
    content_type: Optional[str] = None
    product_data: Optional[Dict] = None
    dealer_data: Optional[Dict] = None
```

---

### Phase 3: Grounded Prompt Generation (3 days)

#### 3.1 Create Prompt Builder Service

**File**: `packages/llm/src/prompts/grounded_builder.py` (NEW)

```python
class GroundedPromptBuilder:
    """Build grounded prompts with structured data injection."""
    
    def build_product_prompt(
        self,
        query: str,
        chunks: List[DocumentChunk],
        system_prompt: str
    ) -> str:
        """Build prompt for product queries with JSON injection."""
        
        # Extract products from chunks
        products = []
        for chunk in chunks:
            if chunk.product_data:
                products.append(chunk.product_data)
        
        if not products:
            return self._build_generic_prompt(query, chunks, system_prompt)
        
        # Build grounded prompt
        prompt = f"""
{system_prompt}

CRITICAL INSTRUCTIONS:
- Use ONLY the product data provided below
- DO NOT invent SKUs, prices, or product names
- If a product is not in the list, say "not available in our catalog"
- All prices, features, and URLs must come from the JSON below

VERIFIED PRODUCT DATA:
```json
{json.dumps(products, indent=2)}
```

USER QUERY: {query}

Respond with product recommendations using EXACT data from the JSON above.
Include product cards with accurate SKU, price, and features.
"""
        return prompt
    
    def build_dealer_prompt(
        self,
        query: str,
        chunks: List[DocumentChunk],
        system_prompt: str
    ) -> str:
        """Build prompt for dealer queries."""
        
        dealers = []
        for chunk in chunks:
            if chunk.dealer_data:
                dealers.append(chunk.dealer_data)
        
        if not dealers:
            return self._build_generic_prompt(query, chunks, system_prompt)
        
        prompt = f"""
{system_prompt}

CRITICAL INSTRUCTIONS:
- Use ONLY the dealer data provided below
- DO NOT invent phone numbers, addresses, or store names
- All contact info must come from the JSON below

VERIFIED DEALER DATA:
```json
{json.dumps(dealers, indent=2)}
```

USER QUERY: {query}

Provide dealer information using EXACT data from the JSON above.
"""
        return prompt
    
    def _build_generic_prompt(
        self,
        query: str,
        chunks: List[DocumentChunk],
        system_prompt: str
    ) -> str:
        """Standard prompt for non-product/dealer queries."""
        context = "\n\n".join([chunk.content for chunk in chunks])
        
        return f"""
{system_prompt}

CONTEXT:
{context}

USER QUERY: {query}

Provide a helpful response based on the context above.
"""
```

#### 3.2 Integrate with Message Service

**File**: `apps/api/app/services/message_service.py`

Update `_build_prompt()`:

```python
from llm.prompts.grounded_builder import GroundedPromptBuilder

class MessageService:
    def __init__(self):
        self.prompt_builder = GroundedPromptBuilder()
    
    async def _build_prompt(
        self,
        query: str,
        retrieval_context: RetrievalContext,
        conversation_history: List[Dict],
        agent_config: AgentConfig
    ) -> str:
        """Build context-aware prompt."""
        
        # Detect content type from retrieval
        has_products = any(c.product_data for c in retrieval_context.chunks)
        has_dealers = any(c.dealer_data for c in retrieval_context.chunks)
        
        system_prompt = agent_config.system_prompt
        
        if has_products:
            return self.prompt_builder.build_product_prompt(
                query=query,
                chunks=retrieval_context.chunks,
                system_prompt=system_prompt
            )
        
        elif has_dealers:
            return self.prompt_builder.build_dealer_prompt(
                query=query,
                chunks=retrieval_context.chunks,
                system_prompt=system_prompt
            )
        
        else:
            return self.prompt_builder._build_generic_prompt(
                query=query,
                chunks=retrieval_context.chunks,
                system_prompt=system_prompt
            )
```

---

### Phase 4: Response Validation (3 days)

#### 4.1 Create Product Validator

**File**: `packages/commons/src/validators/product_validator.py` (NEW)

```python
class ProductResponseValidator:
    """Validate LLM responses don't hallucinate product data."""
    
    def validate_product_response(
        self,
        response_text: str,
        known_products: List[Dict]
    ) -> Tuple[bool, List[str]]:
        """
        Validate response against known product catalog.
        
        Returns:
            (is_valid, errors)
        """
        errors = []
        
        # Extract SKUs mentioned in response
        mentioned_skus = self._extract_skus(response_text)
        known_skus = {p["sku"] for p in known_products}
        
        # Check for unknown SKUs
        unknown_skus = mentioned_skus - known_skus
        if unknown_skus:
            errors.append(f"Hallucinated SKUs: {unknown_skus}")
        
        # Extract prices and validate
        mentioned_prices = self._extract_prices(response_text)
        known_prices = {p["sku"]: p["price"] for p in known_products}
        
        for sku, mentioned_price in mentioned_prices.items():
            if sku in known_prices:
                actual_price = known_prices[sku]
                if abs(mentioned_price - actual_price) > 100:  # 1 rupee tolerance
                    errors.append(
                        f"Wrong price for {sku}: said {mentioned_price}, "
                        f"actual {actual_price}"
                    )
        
        return len(errors) == 0, errors
    
    def _extract_skus(self, text: str) -> Set[str]:
        """Extract SKU patterns from text."""
        # Match patterns like FAU-001, SHW-123, etc.
        import re
        pattern = r'\b[A-Z]{3}-\d{3}\b'
        return set(re.findall(pattern, text))
    
    def _extract_prices(self, text: str) -> Dict[str, int]:
        """Extract prices mentioned with SKUs."""
        # Implementation to extract price mentions
        pass
```

#### 4.2 Add Validation to Message Service

```python
from commons.validators.product_validator import ProductResponseValidator

class MessageService:
    def __init__(self):
        self.validator = ProductResponseValidator()
    
    async def generate_response(
        self,
        query: str,
        retrieval_context: RetrievalContext,
        # ...
    ) -> Dict[str, Any]:
        """Generate and validate response."""
        
        # Generate response
        response = await self.llm_service.generate(prompt)
        
        # Validate if products involved
        products = [c.product_data for c in retrieval_context.chunks if c.product_data]
        if products:
            is_valid, errors = self.validator.validate_product_response(
                response_text=response["text"],
                known_products=products
            )
            
            if not is_valid:
                logger.error("Product hallucination detected", errors=errors)
                # Retry with stricter prompt or return error
                response["text"] = self._build_fallback_response(errors)
        
        return response
```

---

### Phase 5: Frontend Product Cards (1 week)

#### 5.1 Create Product Card Component

**File**: `apps/widget/src/components/ProductCard.tsx` (NEW)

```typescript
interface ProductCardProps {
  product: {
    sku: string;
    name: string;
    price: number;
    currency: string;
    category: string;
    image_url?: string;
    product_url?: string;
    in_stock: boolean;
    features: string[];
  };
}

export function ProductCard({ product }: ProductCardProps) {
  const formattedPrice = (product.price / 100).toLocaleString('en-IN', {
    style: 'currency',
    currency: product.currency
  });
  
  return (
    <div className="border rounded-lg p-4 hover:shadow-lg transition-shadow">
      {product.image_url && (
        <img
          src={product.image_url}
          alt={product.name}
          className="w-full h-48 object-cover rounded-md mb-3"
        />
      )}
      
      <h3 className="font-semibold text-lg mb-1">{product.name}</h3>
      <p className="text-sm text-gray-500 mb-2">SKU: {product.sku}</p>
      
      <div className="flex justify-between items-center mb-3">
        <span className="text-xl font-bold text-primary-600">
          {formattedPrice}
        </span>
        <span className={`px-2 py-1 rounded text-xs ${
          product.in_stock 
            ? 'bg-green-100 text-green-800' 
            : 'bg-red-100 text-red-800'
        }`}>
          {product.in_stock ? 'In Stock' : 'Out of Stock'}
        </span>
      </div>
      
      {product.features.length > 0 && (
        <div className="mb-3">
          <p className="text-sm font-medium mb-1">Features:</p>
          <ul className="text-sm text-gray-600 space-y-1">
            {product.features.slice(0, 3).map((feature, idx) => (
              <li key={idx} className="flex items-start">
                <span className="mr-2">•</span>
                {feature}
              </li>
            ))}
          </ul>
        </div>
      )}
      
      {product.product_url && (
        <a
          href={product.product_url}
          target="_blank"
          rel="noopener noreferrer"
          className="block w-full text-center bg-primary-600 text-white py-2 rounded-md hover:bg-primary-700 transition-colors"
        >
          View Details
        </a>
      )}
    </div>
  );
}
```

#### 5.2 Update Chat Response Renderer

**File**: `apps/widget/src/components/ChatMessage.tsx`

```typescript
import { ProductCard } from './ProductCard';
import { DealerCard } from './DealerCard';

function ChatMessage({ message }: ChatMessageProps) {
  // Parse response for structured data
  const structuredData = parseStructuredData(message.text);
  
  return (
    <div className="chat-message">
      {/* Regular text response */}
      <div className="prose">
        {message.text}
      </div>
      
      {/* Product cards if present */}
      {structuredData.products.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
          {structuredData.products.map(product => (
            <ProductCard key={product.sku} product={product} />
          ))}
        </div>
      )}
      
      {/* Dealer cards if present */}
      {structuredData.dealers.length > 0 && (
        <div className="space-y-3 mt-4">
          {structuredData.dealers.map(dealer => (
            <DealerCard key={dealer.dealer_id} dealer={dealer} />
          ))}
        </div>
      )}
      
      {/* Citations */}
      {message.citations && (
        <div className="mt-4">
          <Citations items={message.citations} />
        </div>
      )}
    </div>
  );
}
```

---

## 🧪 Testing Strategy

### Test Cases

#### 1. Product Search
```
Query: "show me chrome faucets under 5000"

Expected:
- content_type filter applied: ["product"]
- Only product chunks retrieved
- product_data extracted and injected
- Response contains product cards
- All SKUs validated
- Prices match exactly
```

#### 2. Dealer Search
```
Query: "find stores in Mumbai"

Expected:
- content_type filter: ["dealer"]
- dealer_data extracted
- Response contains dealer cards
- All contact info validated
```

#### 3. Mixed Query
```
Query: "tell me about faucet installation and where to buy"

Expected:
- Retrieves both "guide" and "product" content types
- Installation guide in text
- Product cards at bottom
```

#### 4. Hallucination Prevention
```
Test: Inject fake SKU in prompt
Expected: Validator catches and rejects
```

---

## 📊 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Hallucination Rate** | 0% | SKU/price validator |
| **Product Retrieval Precision** | >90% | Relevant products in top 5 |
| **Response Time P95** | <2s | End-to-end latency |
| **Structured Data Extraction** | >95% | Products with complete data |
| **User Satisfaction** | >4.5/5 | Post-chat ratings |

---

## 📁 Files to Create/Modify

### New Files
- [ ] `packages/llm/src/prompts/grounded_builder.py`
- [ ] `packages/commons/src/validators/product_validator.py`
- [ ] `apps/widget/src/components/ProductCard.tsx`
- [ ] `apps/widget/src/components/DealerCard.tsx`

### Modified Files
- [ ] `apps/api/app/services/ingestion_service.py` (add structured extraction)
- [ ] `apps/api/app/api/v1/endpoints/knowledge.py` (add content_type param)
- [ ] `packages/retrieval/src/retrieval/pipeline.py` (add content filtering)
- [ ] `packages/retrieval/src/retrieval/types.py` (add product_data fields)
- [ ] `apps/api/app/services/message_service.py` (integrate grounded prompts)
- [ ] `apps/widget/src/components/ChatMessage.tsx` (render product cards)
- [ ] `scripts/setup_mongodb_indexes.py` (add new indexes)

---

## 🚀 Implementation Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Phase 1: Schema | 3 days | KB with content_type + structured data |
| Phase 2: Retrieval | 1 week | Content-aware retrieval working |
| Phase 3: Prompts | 3 days | Grounded prompt injection |
| Phase 4: Validation | 3 days | Hallucination detection |
| Phase 5: Frontend | 1 week | Product cards rendering |
| **Total** | **~3 weeks** | **Production-ready** |

---

## ✅ Next Steps

1. **Review this plan** - Ensure alignment with AGENTS.md
2. **Phase 1**: Start with schema enhancement
3. **Test ingestion**: Upload products with new fields
4. **Phase 2**: Implement content-type filtering
5. **Phase 3**: Build grounded prompts
6. **Phase 4**: Add validation
7. **Phase 5**: Build UI components

---

**Follows AGENTS.md Architecture**: ✅ YES
- Hybrid retrieval (Vector + BM25) ✅
- RRF Fusion ✅
- Cross-encoder rerank ✅
- Brand/page boosts ✅
- Schema-locked outputs ✅
- Citation coverage ✅
- No hallucinations (validation) ✅

**Ready to start?** Begin with Phase 1! 🚀
