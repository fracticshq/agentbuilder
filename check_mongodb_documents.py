#!/usr/bin/env python3
"""
Quick MongoDB Document Check Script

Usage:
  python check_mongodb_documents.py
  python check_mongodb_documents.py --brand-id default
  python check_mongodb_documents.py --content-type product
"""

import os
import sys
from pymongo import MongoClient
from datetime import datetime
from typing import Optional

def get_mongo_client():
    """Get MongoDB client from environment"""
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("❌ MONGO_URI not set in environment")
        print("\nSet it with:")
        print("  export MONGO_URI='your-mongodb-uri'")
        sys.exit(1)
    
    try:
        client = MongoClient(mongo_uri)
        # Test connection
        client.admin.command('ping')
        print("✅ Connected to MongoDB")
        return client
    except Exception as e:
        print(f"❌ Failed to connect to MongoDB: {e}")
        sys.exit(1)

def check_documents(brand_id: Optional[str] = None, content_type: Optional[str] = None):
    """Check documents in knowledge_base collection"""
    client = get_mongo_client()
    db = client['agent-builder']
    collection = db['knowledge_base']
    
    # Build query
    query = {}
    if brand_id:
        query['metadata.brand_id'] = brand_id
    if content_type:
        query['metadata.content_type'] = content_type
    
    # Get counts
    total_chunks = collection.count_documents(query)
    
    print(f"\n📊 Document Statistics")
    print("=" * 60)
    
    if brand_id:
        print(f"Brand ID: {brand_id}")
    if content_type:
        print(f"Content Type: {content_type}")
    
    print(f"\nTotal Chunks: {total_chunks}")
    
    if total_chunks == 0:
        print("\n⚠️  No documents found!")
        print("\nPossible reasons:")
        print("  1. No uploads have been made yet")
        print("  2. brand_id doesn't match (check your agent ID)")
        print("  3. Upload failed validation (check API logs)")
        return
    
    # Group by doc_id to get unique documents
    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": "$metadata.doc_id",
            "content_type": {"$first": "$metadata.content_type"},
            "brand_id": {"$first": "$metadata.brand_id"},
            "chunk_count": {"$sum": 1},
            "created_at": {"$first": "$created_at"}
        }},
        {"$sort": {"created_at": -1}},
        {"$limit": 10}
    ]
    
    documents = list(collection.aggregate(pipeline))
    
    print(f"\nUnique Documents: {len(documents)}")
    print("\n📁 Recent Documents:")
    print("=" * 60)
    
    for doc in documents:
        doc_id = doc['_id'] or 'untitled'
        content_type = doc.get('content_type', 'unknown')
        brand_id = doc.get('brand_id', 'default')
        chunks = doc.get('chunk_count', 0)
        created = doc.get('created_at', 'unknown')
        
        if isinstance(created, datetime):
            created_str = created.strftime('%Y-%m-%d %H:%M:%S')
        else:
            created_str = str(created)
        
        print(f"\n📄 {doc_id}")
        print(f"   Type: {content_type} | Brand: {brand_id} | Chunks: {chunks}")
        print(f"   Created: {created_str}")
    
    # Content type breakdown
    print(f"\n📊 Content Type Breakdown:")
    print("=" * 60)
    
    type_pipeline = [
        {"$match": query},
        {"$group": {
            "_id": "$metadata.content_type",
            "chunk_count": {"$sum": 1},
            "doc_count": {"$addToSet": "$metadata.doc_id"}
        }},
        {"$project": {
            "content_type": "$_id",
            "chunk_count": 1,
            "doc_count": {"$size": "$doc_count"}
        }}
    ]
    
    types = list(collection.aggregate(type_pipeline))
    for t in types:
        content_type = t.get('content_type') or t.get('_id', 'unknown')
        doc_count = t.get('doc_count', 0)
        chunk_count = t.get('chunk_count', 0)
        print(f"  {content_type:12s}: {doc_count:3d} documents, {chunk_count:4d} chunks")
    
    # Sample document
    print(f"\n📝 Sample Document Chunk:")
    print("=" * 60)
    
    sample = collection.find_one(query)
    if sample:
        print(f"doc_id: {sample['metadata'].get('doc_id', 'N/A')}")
        print(f"content_type: {sample['metadata'].get('content_type', 'N/A')}")
        print(f"brand_id: {sample['metadata'].get('brand_id', 'N/A')}")
        print(f"\nText preview:")
        text = sample.get('text', '')[:200]
        print(f"  {text}...")
        
        if 'metadata' in sample:
            print(f"\nMetadata keys: {list(sample['metadata'].keys())}")
    
    client.close()

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Check MongoDB knowledge base documents')
    parser.add_argument('--brand-id', help='Filter by brand ID (e.g., default)')
    parser.add_argument('--content-type', help='Filter by content type (e.g., product, dealer)')
    
    args = parser.parse_args()
    
    check_documents(brand_id=args.brand_id, content_type=args.content_type)

if __name__ == '__main__':
    main()
