#!/usr/bin/env python3
"""
Verify product chunks structure in MongoDB.
Checks if chunks have correct content_type and product_data fields.
"""

import os
import sys
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

def verify_chunks():
    """Verify product chunks in MongoDB."""
    
    # Connect to MongoDB
    mongo_uri = os.getenv('MONGODB_URI')
    if not mongo_uri or 'your-mongodb-uri-here' in mongo_uri:
        print("❌ Error: MONGODB_URI not configured in .env file")
        print("   Please update .env with your actual MongoDB Atlas URI")
        return False
    
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        # Test connection
        client.server_info()
        print("✅ Connected to MongoDB Atlas")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False
    
    db = client['essco_agent']
    collection = db['knowledge_base']
    
    brand_id = 'essco-bathware'
    
    print(f"\n{'='*80}")
    print(f"VERIFYING PRODUCT CHUNKS FOR: {brand_id}")
    print(f"{'='*80}\n")
    
    # Count all chunks
    total_chunks = collection.count_documents({'brand_id': brand_id})
    print(f"📊 Total chunks for {brand_id}: {total_chunks}")
    
    # Count product chunks (correct structure)
    product_chunks_correct = collection.count_documents({
        'brand_id': brand_id,
        'content_type': 'product',
        'product_data': {'$exists': True, '$ne': None}
    })
    print(f"✅ Chunks with content_type='product' AND product_data: {product_chunks_correct}")
    
    # Count chunks with wrong content_type
    wrong_content_type = collection.count_documents({
        'brand_id': brand_id,
        'content_type': {'$ne': 'product'}
    })
    print(f"⚠️  Chunks with content_type != 'product': {wrong_content_type}")
    
    # Count chunks missing product_data
    missing_product_data = collection.count_documents({
        'brand_id': brand_id,
        'content_type': 'product',
        'product_data': {'$exists': False}
    })
    print(f"⚠️  Product chunks missing product_data: {missing_product_data}")
    
    # Count chunks with null product_data
    null_product_data = collection.count_documents({
        'brand_id': brand_id,
        'content_type': 'product',
        'product_data': None
    })
    print(f"⚠️  Product chunks with null product_data: {null_product_data}")
    
    print(f"\n{'='*80}")
    print("SAMPLE CHUNKS INSPECTION")
    print(f"{'='*80}\n")
    
    # Show samples of correct chunks
    print("✅ Sample CORRECT product chunks (with product_data):")
    correct_samples = collection.find({
        'brand_id': brand_id,
        'content_type': 'product',
        'product_data': {'$exists': True, '$ne': None}
    }).limit(3)
    
    for i, chunk in enumerate(correct_samples, 1):
        print(f"\n  Chunk {i}:")
        print(f"    doc_id: {chunk.get('doc_id', 'N/A')}")
        print(f"    content_type: {chunk.get('content_type', 'N/A')}")
        print(f"    product_data.sku: {chunk.get('product_data', {}).get('sku', 'N/A')}")
        print(f"    product_data.name: {chunk.get('product_data', {}).get('name', 'N/A')}")
        print(f"    product_data.price: {chunk.get('product_data', {}).get('price', 'N/A')}")
        print(f"    product_data.currency: {chunk.get('product_data', {}).get('currency', 'N/A')}")
        print(f"    product_data.category: {chunk.get('product_data', {}).get('category', 'N/A')}")
        print(f"    product_data.in_stock: {chunk.get('product_data', {}).get('in_stock', 'N/A')}")
        print(f"    product_data.features: {len(chunk.get('product_data', {}).get('features', []))} items")
    
    # Show samples of incorrect chunks
    print("\n⚠️  Sample INCORRECT chunks (wrong content_type or missing product_data):")
    incorrect_samples = collection.find({
        'brand_id': brand_id,
        '$or': [
            {'content_type': {'$ne': 'product'}},
            {'product_data': {'$exists': False}},
            {'product_data': None}
        ]
    }).limit(3)
    
    incorrect_count = 0
    for i, chunk in enumerate(incorrect_samples, 1):
        incorrect_count += 1
        print(f"\n  Chunk {i}:")
        print(f"    doc_id: {chunk.get('doc_id', 'N/A')}")
        print(f"    content_type: {chunk.get('content_type', 'N/A')}")
        print(f"    has product_data: {'product_data' in chunk}")
        if 'product_data' in chunk:
            print(f"    product_data value: {chunk.get('product_data')}")
        print(f"    text preview: {chunk.get('content', '')[:100]}...")
    
    if incorrect_count == 0:
        print("  (No incorrect chunks found - All good! ✅)")
    
    print(f"\n{'='*80}")
    print("ANALYSIS & RECOMMENDATIONS")
    print(f"{'='*80}\n")
    
    if product_chunks_correct == 0:
        print("❌ CRITICAL: No correctly structured product chunks found!")
        print("\n📋 Action Required:")
        print("   1. Re-upload product_data.json via Admin Dashboard")
        print("   2. Select 'Product' as content type")
        print("   3. Map all fields correctly")
        print("   4. Wait for processing to complete")
        print("   5. Run this script again to verify")
        
    elif product_chunks_correct > 0 and (wrong_content_type > 0 or missing_product_data > 0 or null_product_data > 0):
        print("⚠️  WARNING: Mixed data - some correct, some incorrect chunks")
        print(f"\n   Correct chunks: {product_chunks_correct}")
        print(f"   Incorrect chunks: {wrong_content_type + missing_product_data + null_product_data}")
        print("\n📋 Recommendations:")
        print("   1. Clean up old chunks (optional):")
        print("      db.knowledge_base.deleteMany({")
        print(f"        'brand_id': '{brand_id}',")
        print("        '$or': [")
        print("          {'content_type': {$ne: 'product'}},")
        print("          {'product_data': {$exists: false}},")
        print("          {'product_data': null}")
        print("        ]")
        print("      })")
        print("   2. Product cards will only show products from correct chunks")
        print(f"   3. Currently {product_chunks_correct} products are ready for cards")
        
    else:
        print("✅ SUCCESS: All chunks are correctly structured!")
        print(f"\n   Total product chunks: {product_chunks_correct}")
        print("   All have content_type='product' AND populated product_data")
        print("\n🎉 Product cards should work correctly now!")
        print("\n📋 Next Steps:")
        print("   1. Test in widget: 'show me faucets under 5000'")
        print("   2. Check browser console for product data")
        print("   3. Verify ProductCard components render")
    
    print(f"\n{'='*80}\n")
    
    return product_chunks_correct > 0

if __name__ == '__main__':
    success = verify_chunks()
    sys.exit(0 if success else 1)
