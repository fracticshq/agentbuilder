# 🐛 Knowledge Base Upload Debugging Guide

## Issue
Files are validated and mapped correctly but not uploading to knowledge base.

## Debugging Steps

### 1. Open Browser Console
- Press `F12` or right-click → "Inspect" → "Console" tab
- Clear console (`Ctrl+L` or click 🚫 icon)

### 2. Start Upload Process
Go through the wizard:
1. **Step 1**: Select "Product" or "Dealer"
2. **Step 2**: Upload JSON file
3. **Step 3**: Map fields
4. **Step 4**: Review & Upload

### 3. Check Console Logs

Look for these log messages in order:

#### ✅ Step 2: JSON Upload
```
[JsonUpload] Passing 380 items to mapper
```
- **If you see this**: JSON parsing worked, data passed to mapper
- **If you DON'T see this**: JSON validation failed

#### ✅ Step 3: Field Mapping
```
[FieldMapper] Mapping data...
```
- **If you see this**: Field mapper received data
- **If you DON'T see this**: Data not passed from JSON upload

#### ✅ Step 4: Review Page Loads
```
[Review Step] Rendering review with: {
  contentType: "product",
  mappedDataLength: 380,
  brandId: "...",
  uploading: false
}
```
- **Check `mappedDataLength`**: Should match your item count
- **If `mappedDataLength: 0`**: Mapping failed or data lost
- **If you DON'T see this log**: Not reaching review step

#### ✅ Step 4: Click Upload Button
```
[Upload Button] Clicked! mappedData: 380 items
```
- **If you see this**: Button click registered
- **If you DON'T see this**: 
  - You didn't click the green "Upload" button
  - Button is disabled
  - JavaScript error preventing click

#### ✅ Upload Starts
```
[Upload] Starting upload: {
  contentType: "product",
  itemCount: 380,
  brandId: "...",
  firstItem: {...}
}
```
- **If you see this**: Upload function started
- **If you DON'T see this**: Check for validation error

#### ✅ API Call
```
[Upload] Calling API with data: {...}
```
- **If you see this**: About to send data to backend
- **If you DON'T see this**: Validation failed before API call

#### ✅ API Response
```
[Upload] API response received: {
  success: true,
  job_id: "...",
  message: "Bulk upload started: 380 products"
}
```
- **If you see this**: ✅ **UPLOAD SUCCESSFUL!**
- **If you DON'T see this**: API call failed (network/server error)

### 4. Common Issues & Fixes

#### Issue: `mappedDataLength: 0` in Review Step
**Cause**: Data lost during mapping
**Fix**: Check field mapper logs, ensure fields are mapped correctly

#### Issue: No "[Upload Button] Clicked!" log
**Cause**: Not clicking the upload button
**Fix**: Scroll down on review page, click the green "Upload X Items →" button

#### Issue: Validation error: "Missing required data"
**Cause**: `contentType` is empty or `mappedData.length === 0`
**Fix**: 
```
[Upload] Validation failed: {
  contentType: "product",  // Should NOT be null/undefined
  mappedDataLength: 380    // Should be > 0
}
```

#### Issue: Network error / API call fails
**Cause**: Backend not running or connection issue
**Check**:
```bash
# Test if API is running
curl http://localhost:8000/health

# Test bulk upload directly
curl -X POST http://localhost:8000/api/v1/knowledge/bulk-upload \
  -H "Content-Type: application/json" \
  -d '{
    "content_type": "product",
    "brand_id": "test",
    "items": [{"sku": "TEST", "name": "Test", "price": 100, "currency": "INR", "category": "test"}]
  }'
```

### 5. Success Confirmation

You should see:
1. ✅ Alert popup: "✅ Success! Upload completed."
2. ✅ Documents list refreshes with new items
3. ✅ Console shows API response with `job_id`

### 6. If Still Not Working

**Copy ALL console logs and share them.**

Look for:
- Red error messages
- Failed network requests (in Network tab)
- Any warnings about data

---

## Quick Test

Try uploading this minimal JSON to test:

```json
[
  {
    "product_id": "TEST-001",
    "product_title": "Test Faucet",
    "cost": 1000,
    "product_type": "faucets"
  }
]
```

**Expected flow**:
1. Upload → See "1 products found"
2. Map fields → sku, name, price, category
3. Review → See "1 items to upload"
4. Click "Upload 1 Items →"
5. See success alert
6. Document appears in list

If this works, your main JSON file has an issue. If this doesn't work, there's a system issue.

---

## Backend Status Check

```bash
# 1. Check API is running
curl http://localhost:8000/health

# 2. Check documents endpoint
curl "http://localhost:8000/api/v1/knowledge/documents?brand_id=YOUR_BRAND_ID"

# 3. Check API logs
tail -f logs/api.log
```
