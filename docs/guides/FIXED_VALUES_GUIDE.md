# 📝 Quick Guide: Using Fixed Values in Knowledge Base Upload

## What Are Fixed Values?

When uploading JSON data, you might need to add fields that don't exist in your source data. **Fixed values** let you add the same value to all uploaded items.

## Common Use Cases

### ✅ Adding Stock Status
Your JSON doesn't have `in_stock` field, but you want to mark all products as available:
- **Fixed value**: `true`

### ✅ Adding Product Features
Your JSON lacks `features` array, but you want to add common features:
- **Fixed value**: `["Warranty Included", "Free Shipping"]`

### ✅ Setting Default Category
Your JSON has no `category` field, but all items belong to "Electronics":
- **Fixed value**: `Electronics`

### ✅ Setting Currency
Your JSON has `price` but no `currency`:
- **Fixed value**: `INR`

## How to Enter Fixed Values

### 1️⃣ Boolean Fields (true/false)

**Field**: `in_stock`

**How to enter TRUE**:
- Type: `true` or `TRUE` or `1` or `yes`

**How to enter FALSE**:
- Type: `false` or `FALSE` or `0` or `no`

**Example**:
```
Field: in_stock
Mode: Use Fixed Value
Value: true
Result: All products marked as in stock ✅
```

### 2️⃣ Array Fields (lists)

**Field**: `features`

**Option A - JSON Array** (recommended):
```json
["Waterproof", "LED Display", "Bluetooth"]
```

**Option B - Comma-Separated**:
```
Waterproof, LED Display, Bluetooth
```

**Option C - Single Item**:
```
Waterproof
```
(Auto-wrapped in array: `["Waterproof"]`)

**Option D - Empty Array**:
```
(leave blank)
```
(Results in: `[]`)

**Example**:
```
Field: features
Mode: Use Fixed Value
Value: ["Warranty", "Free Shipping"]
Result: All products get these features ✅
```

### 3️⃣ Number Fields

**Field**: `price`

**How to enter**:
- Whole numbers: `100`
- Decimals: `99.99`
- Large numbers: `1500000`

**Example**:
```
Field: price
Mode: Use Fixed Value
Value: 99.99
Result: All products priced at 99.99 ✅
```

### 4️⃣ Text Fields

**Field**: `currency`, `category`, etc.

**How to enter**: Just type the text as-is

**Example**:
```
Field: currency
Mode: Use Fixed Value
Value: INR
Result: All products use INR currency ✅
```

## Step-by-Step Example

### Scenario: Product Upload

**Your JSON**:
```json
[
  {
    "product_id": "ABC123",
    "product_name": "Smart Watch",
    "cost": 2999
  }
]
```

**Required Fields** (from platform):
- sku ✅
- name ✅
- price ✅
- currency ❌ (missing!)
- category ❌ (missing!)

**Optional Fields** you want:
- in_stock ❌ (missing!)
- features ❌ (missing!)

### Field Mapping:

| Platform Field | Mode | Value/Source |
|---|---|---|
| `sku` | Map from JSON | `product_id` |
| `name` | Map from JSON | `product_name` |
| `price` | Map from JSON | `cost` |
| `currency` | **Use Fixed Value** | `INR` |
| `category` | **Use Fixed Value** | `Electronics` |
| `in_stock` | **Use Fixed Value** | `true` |
| `features` | **Use Fixed Value** | `["Bluetooth", "Waterproof"]` |

### Result:
```json
[
  {
    "sku": "ABC123",
    "name": "Smart Watch",
    "price": 2999,
    "currency": "INR",
    "category": "Electronics",
    "in_stock": true,
    "features": ["Bluetooth", "Waterproof"]
  }
]
```

## Common Mistakes & Solutions

### ❌ Mistake 1: Array as comma-separated WITHOUT spaces
```
Wrong: "WiFi,Bluetooth,USB"
Right: "WiFi, Bluetooth, USB"
       ^    ^          ^
     (spaces after commas)
```

### ❌ Mistake 2: Boolean as text
```
Wrong: "yes" or "available" or "Y"
Right: "true" or "1" or "yes"
```

### ❌ Mistake 3: JSON array with single quotes
```
Wrong: '["WiFi", "Bluetooth"]'  (single quotes outside)
Right: ["WiFi", "Bluetooth"]    (no outer quotes in input field)
```

### ❌ Mistake 4: Number as text with currency symbol
```
Wrong: "₹99.99" or "$100"
Right: "99.99"  (just the number)
```

## Validation Checks

The platform automatically validates your fixed values:

✅ **Boolean fields**: Must be true/false (or equivalents)
✅ **Array fields**: Must be valid JSON array OR comma-separated text
✅ **Number fields**: Must be valid number (decimals allowed)
✅ **Text fields**: Any text accepted

**Error messages** will appear if validation fails.

## Preview Your Data

After mapping fields, check the **Preview** section:

```
Preview (3 items):

1. {
  "sku": "ABC123",
  "in_stock": true,        ← Shows as boolean, not "true"
  "features": ["WiFi"],     ← Shows as array, not '"WiFi"'
  ...
}
```

**Look for**:
- ✅ Booleans shown as `true`/`false` (not `"true"`/`"false"`)
- ✅ Arrays shown as `[...]` (not `"[...]"`)
- ✅ Numbers shown without quotes

## Debug Console

Open browser console (F12) to see type conversions:

```javascript
[JsonFieldMapper] Fixed field "in_stock": "true" → type: boolean, value: true
[JsonFieldMapper] Fixed field "features": '["WiFi"]' → type: object, value: ["WiFi"]
```

This confirms your fixed values are being parsed correctly.

## Tips & Best Practices

### 💡 Tip 1: Use JSON Format for Arrays
For complex arrays, use JSON format:
```json
["Feature 1", "Feature 2", "Feature 3"]
```

### 💡 Tip 2: Check Preview Before Upload
Always review the preview to ensure types are correct.

### 💡 Tip 3: Use Lowercase for Booleans
While `TRUE` works, `true` is clearer:
```
Preferred: true
Also works: TRUE, True, 1, yes
```

### 💡 Tip 4: Empty Arrays for Optional Fields
If you want to include the field but leave it empty:
```
Field: features
Mode: Use Fixed Value
Value: (leave blank or type: [])
```

## Quick Reference Table

| Field Type | Example Input | Parsed Output | Type |
|---|---|---|---|
| Boolean | `true` | `true` | boolean |
| Boolean | `1` | `true` | boolean |
| Boolean | `false` | `false` | boolean |
| Array (JSON) | `["WiFi", "Bluetooth"]` | `["WiFi", "Bluetooth"]` | array |
| Array (CSV) | `WiFi, Bluetooth` | `["WiFi", "Bluetooth"]` | array |
| Array (Single) | `WiFi` | `["WiFi"]` | array |
| Array (Empty) | *(blank)* | `[]` | array |
| Number | `99.99` | `99.99` | number |
| String | `INR` | `"INR"` | string |

## Need Help?

If upload fails:

1. **Check browser console** (F12) for parsing errors
2. **Review the preview** - does data look correct?
3. **Check validation messages** - what fields are failing?
4. **Try simpler format** - use comma-separated for arrays instead of JSON

---

**Last Updated**: 2024-01-15
**Status**: ✅ Working - All type parsing implemented
