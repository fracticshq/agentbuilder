#!/usr/bin/env python3
"""
Clean up old product data chunks that don't have the correct Phase 5 structure.

This script will DELETE chunks that:
1. Have content_type != "product" (old text chunks)
2. Don't have a product_data field
3. Have product_data = null

After cleanup, you can re-upload product_data.json via Admin Dashboard
to create correctly structured chunks.
"""

import os
import sys
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

def cleanup_old_data():
    """Clean up old incorrectly structured chunks."""
    
    # Connect to MongoDB
    mongo_uri = os.getenv('MONGODB_URI')
    if not mongo_uri or 'your-mongodb-uri-here' in mongo_uri:
        print("❌ Error: MONGODB_URI not configured in .env file")
        print("   Please update .env with your actual MongoDB Atlas URI")
        return False
    
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=10000)
        # Test connection
        client.server_info()
        print("✅ Connected to MongoDB Atlas\n")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False
    
    db = client['essco_agent']
    collection = db['knowledge_base']
    
    brand_id = 'essco-bathware'
    
    print(f"{'='*80}")
    print(f"CLEANING UP OLD DATA FOR: {brand_id}")
    print(f"{'='*80}\n")
    
    # Count what we're about to delete
    print("📊 Analyzing current data...\n")
    
    total_chunks = collection.count_documents({'brand_id': brand_id})
    print(f"   Total chunks: {total_chunks}")
    
    # Count correct chunks (we'll keep these)
    correct_chunks = collection.count_documents({
        'brand_id': brand_id,
        'content_type': 'product',
        'product_data': {'$exists': True, '$ne': None}
    })
    print(f"   ✅ Correct chunks (will KEEP): {correct_chunks}")
    
    # Count chunks we'll delete
    delete_query = {
        'brand_id': brand_id,
        '$or': [
            {'content_type': {'$ne': 'product'}},
            {'product_data': {'$exists': False}},
            {'product_data': None}
        ]
    }
    
    chunks_to_delete = collection.count_documents(delete_query)
    print(f"   ❌ Incorrect chunks (will DELETE): {chunks_to_delete}")
    
    if chunks_to_delete == 0:
        print("\n✅ No cleanup needed! All chunks are already correctly structured.")
        return True
    
    print(f"\n{'='*80}")
    print("PREVIEW OF CHUNKS TO BE DELETED")
    print(f"{'='*80}\n")
    
    # Show samples of what will be deleted
    samples = collection.find(delete_query).limit(5)
    for i, chunk in enumerate(samples, 1):
        print(f"Sample {i}:")
        print(f"  doc_id: {chunk.get('doc_id', 'N/A')}")
        print(f"  content_type: {chunk.get('content_type', 'N/A')}")
        print(f"  has product_data: {'product_data' in chunk}")
        if 'product_data' in chunk:
            print(f"  product_data value: {chunk.get('product_data')}")
        print(f"  text preview: {chunk.get('content', '')[:80]}...")
        print()
    
    # Confirmation prompt
    print(f"{'='*80}")
    print("⚠️  CONFIRMATION REQUIRED")
    print(f"{'='*80}\n")
    print(f"This will DELETE {chunks_to_delete} chunks from MongoDB.")
    print(f"Correct chunks ({correct_chunks}) will be preserved.")
    print()
    print("After cleanup, you should:")
    print("  1. Re-upload product_data.json via Admin Dashboard")
    print("  2. Select 'Product' as content type")
    print("  3. Map all fields correctly")
    print()
    
    response = input("⚠️  Type 'DELETE' (in uppercase) to confirm: ")
    
    if response != 'DELETE':
        print("\n❌ Cleanup cancelled. No data was deleted.")
        return False
    
    print(f"\n{'='*80}")
    print("DELETING OLD CHUNKS...")
    print(f"{'='*80}\n")
    
    try:
        result = collection.delete_many(delete_query)
        deleted_count = result.deleted_count
        
        print(f"✅ Successfully deleted {deleted_count} chunks")
        
        # Verify final state
        remaining = collection.count_documents({'brand_id': brand_id})
        correct_remaining = collection.count_documents({
            'brand_id': brand_id,
            'content_type': 'product',
            'product_data': {'$exists': True, '$ne': None}
        })
        
        print(f"\n{'='*80}")
        print("CLEANUP COMPLETE")
        print(f"{'='*80}\n")
        print(f"   Deleted: {deleted_count} chunks")
        print(f"   Remaining total: {remaining} chunks")
        print(f"   Remaining correct: {correct_remaining} chunks")
        
        if remaining == correct_remaining:
            print("\n✅ SUCCESS! All remaining chunks have correct structure.")
        
        print(f"\n{'='*80}")
        print("NEXT STEPS")
        print(f"{'='*80}\n")
        print("1. Open Admin Dashboard: http://localhost:3000")
        print("2. Go to Knowledge Base → Upload Document")
        print("3. Select content type: 'Product'")
        print("4. Upload product_data.json")
        print("5. Map fields:")
        print("   - SKU → sku")
        print("   - Name → name")
        print("   - Price → price")
        print("   - Currency → currency (or Fixed Value: 'INR')")
        print("   - Category → category")
        print("   - In Stock → in_stock (or Fixed Value: true)")
        print("   - Features → features")
        print("   - Image URL → image_url")
        print("   - Product URL → product_url")
        print("6. Review and confirm upload")
        print("7. Wait for processing to complete")
        print("8. Test in widget: 'show me faucets under 5000'")
        print()
        
        return True
        
    except Exception as e:
        print(f"\n❌ Deletion failed: {e}")
        return False

if __name__ == '__main__':
    success = cleanup_old_data()
    sys.exit(0 if success else 1)
