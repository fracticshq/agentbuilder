# 🧪 JSON Field Mapping - Testing Guide

## Flow Overview

```
Step 1: Upload JSON (any structure)
   ↓
Step 2: Basic Validation (structure only, not field names)
   ↓
Step 3: Field Mapper UI (auto-detects & maps fields)
   ↓
Step 4: Confirm Mapping
   ↓
Step 5: Upload Complete
```

## How to Test

### 1. Navigate to Knowledge Base
- Open http://localhost:3000/agents
- Click on an existing agent OR create new
- Go to **Step 4: Knowledge Base**
- Click **"Upload Document with Structured Metadata"**

### 2. Select Bulk JSON Import
- Click **"📦 Bulk JSON Import"** tab
- Choose **🛍️ Products** or **🏪 Dealers**

### 3. Test Auto-Mapping with Custom Field Names

#### Test Case 1: Shopify-style JSON (Auto-maps perfectly)
Paste this JSON:
```json
[
  {
    "product_id": "SHOP-001",
    "product_title": "Chrome Bathroom Faucet",
    "cost": 3499,
    "curr": "INR",
    "product_type": "faucets",
    "image": "https://example.com/faucet.jpg",
    "stock_available": true,
    "tags": ["chrome", "modern"]
  },
  {
    "product_id": "SHOP-002",
    "product_title": "Rainfall Shower Head",
    "cost": 4799,
    "curr": "INR",
    "product_type": "showers",
    "stock_available": true,
    "tags": ["rainfall", "brass"]
  }
]
```

**Expected Auto-Mapping**:
- ✅ `product_id` → `sku`
- ✅ `product_title` → `name`
- ✅ `cost` → `price`
- ✅ `curr` → `currency`
- ✅ `product_type` → `category`

**Manual Mapping Needed**:
- `image` → `image_url` (optional)
- `stock_available` → `in_stock` (optional)
- `tags` → `features` (optional)

#### Test Case 2: ERP-style JSON (Completely different names)
```json
[
  {
    "item_code": "ERP-FAU-001",
    "description": "Premium Bathroom Faucet",
    "retail_price_cents": 3499,
    "price_currency": "INR",
    "item_category": "bathroom-faucets"
  }
]
```

**Expected Auto-Mapping**:
- 🟡 No exact matches (shows dropdown to manually map)

**Manual Steps**:
1. Map `item_code` → `sku`
2. Map `description` → `name`
3. Map `retail_price_cents` → `price`
4. Map `price_currency` → `currency`
5. Map `item_category` → `category`

#### Test Case 3: Perfect Match (No mapping needed)
```json
[
  {
    "sku": "ESSCO-FAU-001",
    "name": "AquaFlow Chrome Faucet",
    "price": 3499,
    "currency": "INR",
    "category": "faucets",
    "image_url": "https://example.com/faucet.jpg",
    "in_stock": true,
    "features": ["chrome", "ceramic disc"]
  }
]
```

**Expected Auto-Mapping**:
- ✅ All fields auto-mapped (exact match)
- ✅ Validation passes immediately
- ✅ Ready to upload!

## What to Verify

### Field Mapper UI Should Show:

1. **Detected Fields Section** (top)
   ```
   📋 Detected 8 fields in your JSON
   [product_id (string)] [product_title (string)] [cost (number)] ...
   ```

2. **Required Field Mappings** (middle)
   - 5 rows for products (sku, name, price, currency, category)
   - Each row shows:
     - Left: Required field with description
     - Center: Arrow (→)
     - Right: Dropdown to select source field
   - Auto-selected values should be pre-filled
   - Sample value shown below dropdown

3. **Optional Field Mappings** (collapsible)
   - Shows additional fields (image_url, product_url, in_stock, features)
   - Can skip these

4. **Validation Status**
   - ✅ Green if all required fields mapped
   - ❌ Red if missing required mappings
   - Shows error list

5. **Preview Section**
   - Shows first 3 items in mapped format
   - Green background with checkmark

6. **Mapping Summary**
   ```
   📊 Mapping Summary
   Total Items: 2
   Required Fields Mapped: 5/5 ✅
   Optional Fields Mapped: 3/4
   Validation Status: ✅ Valid
   ```

7. **Action Buttons**
   - "← Back to JSON Upload" (left)
   - "Confirm Mapping & Continue →" (right, enabled when valid)

## Expected Behavior

### Auto-Mapping Logic
The system detects these common aliases:

**For Products**:
- `sku` ← `product_id`, `productId`, `id`, `code`, `item_id`, `item_code`
- `name` ← `title`, `product_name`, `product_title`, `description`
- `price` ← `amount`, `cost`, `product_price`, `retail_price_cents`
- `currency` ← `curr`, `currency_code`, `price_currency`
- `category` ← `cat`, `product_category`, `product_type`, `item_category`

**For Dealers**:
- `dealer_id` ← `id`, `dealerId`, `dealer_code`
- `city` ← `location`, `town`
- `phone` ← `tel`, `telephone`, `mobile`, `contact`

### Validation Rules
1. All required fields MUST be mapped
2. Mapped fields must exist in source JSON
3. First 10 items checked for required values
4. Type checking (price must be number)
5. Clear error messages for each issue

### After Confirming Mapping
- Returns to Document Upload Wizard
- Shows mapped data in Step 4 (Review)
- Ready to upload to backend

## Troubleshooting

### "No auto-mapping suggestions"
- Check field names don't match any aliases
- Manually select fields from dropdowns
- System is flexible - ANY field can map to ANY required field

### "Required field not mapped" error
- Look for red-bordered field boxes
- Select a source field from dropdown
- Must map all 5 required fields

### "Missing value for required field" error
- Some items in JSON missing data
- Check JSON for null/empty values
- Fix JSON or remove incomplete items

### Field mapper doesn't appear
- Check JSON is valid (no syntax errors)
- Check array is not empty
- Look for validation errors in upload step
- Try "Paste JSON" tab instead of file upload

## Success Criteria

✅ Field mapper appears after clicking "Next: Map Fields →"  
✅ Common field names auto-mapped correctly  
✅ Dropdown shows all detected fields  
✅ Sample values visible below each mapping  
✅ Validation errors clear and actionable  
✅ Preview shows correctly mapped JSON  
✅ Can go back and try different JSON  
✅ Confirm button enabled only when valid  
✅ Returns to wizard with mapped data  

## Backend Integration (Pending)

Once backend is ready, the mapped data will be:
1. Sent to `/api/v1/knowledge/bulk-upload`
2. Chunked (each product becomes chunks)
3. Embedded using Voyage
4. Stored in MongoDB with:
   - `content_type`: "product"
   - `product_data`: {sku, name, price, ...}
   - `embedding`: [vector]
   - `metadata.brand_id`: agent's brand

---

**Status**: ✅ UI Complete & Ready for Testing  
**Backend**: ⏳ Pending Implementation  
**Next**: Test all scenarios above, then build backend API
