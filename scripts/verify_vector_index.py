"""
Verify Vector Search Index Configuration
"""

import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Load environment
load_dotenv('apps/api/.env')


async def main():
    mongodb_uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DATABASE", "agent-builder")
    
    client = AsyncIOMotorClient(mongodb_uri)
    db = client[db_name]
    collection = db["knowledge_base"]
    
    print("=" * 80)
    print("Vector Search Index Verification")
    print("=" * 80)
    
    # Check if documents have embeddings
    print("\n1. Checking documents with embeddings...")
    doc_with_embeddings = await collection.find_one({"embeddings": {"$exists": True}})
    
    if doc_with_embeddings:
        print(f"   ✅ Found document with embeddings")
        print(f"   Document ID: {doc_with_embeddings.get('doc_id')}")
        print(f"   Title: {doc_with_embeddings.get('title')}")
        
        embeddings = doc_with_embeddings.get('embeddings')
        if embeddings:
            print(f"   Embedding type: {type(embeddings)}")
            print(f"   Embedding dimensions: {len(embeddings)}")
            print(f"   First 5 values: {embeddings[:5]}")
            print(f"   Sample value type: {type(embeddings[0])}")
        else:
            print("   ❌ Embeddings field is empty")
    else:
        print("   ❌ No documents with embeddings found")
        print("   Run: python scripts/test_document_ingestion.py --with-embeddings")
    
    # Count documents with embeddings
    print("\n2. Counting documents...")
    total_docs = await collection.count_documents({})
    docs_with_embeddings = await collection.count_documents({"embeddings": {"$exists": True}})
    
    print(f"   Total documents: {total_docs}")
    print(f"   Documents with embeddings: {docs_with_embeddings}")
    
    # List all indexes
    print("\n3. Checking indexes...")
    indexes = await collection.list_indexes().to_list(None)
    
    print(f"   Found {len(indexes)} indexes:")
    for idx in indexes:
        print(f"      - {idx['name']} (type: {idx.get('type', 'standard')})")
    
    # Check for vector search index
    print("\n4. Vector Search Index Status:")
    print("   ⚠️  Vector search indexes are not visible via standard MongoDB commands")
    print("   ✅ Check in Atlas UI → Database → Search → vector_index")
    print("   ✅ Ensure:")
    print("      - Index name: vector_index")
    print("      - Field path: embeddings")
    print("      - Dimensions: 1024")
    print("      - Similarity: cosine")
    
    # Try a simple vector search query
    print("\n5. Testing vector search query...")
    
    if doc_with_embeddings and doc_with_embeddings.get('embeddings'):
        try:
            # Use the same embedding as a test query
            test_embedding = doc_with_embeddings['embeddings'][:1024]  # Ensure 1024 dims
            
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": "vector_index",
                        "path": "embeddings",
                        "queryVector": test_embedding,
                        "numCandidates": 5,
                        "limit": 1
                    }
                }
            ]
            
            cursor = collection.aggregate(pipeline)
            results = await cursor.to_list(length=1)
            
            if results:
                print(f"   ✅ Vector search successful!")
                print(f"   Found: {results[0].get('title')}")
            else:
                print("   ⚠️  Vector search returned no results")
                
        except Exception as e:
            print(f"   ❌ Vector search failed: {e}")
            print("\n   Possible issues:")
            print("      1. Vector index not created in Atlas UI")
            print("      2. Index name mismatch (should be 'vector_index')")
            print("      3. Embedding dimensions mismatch (should be 1024)")
            print("      4. Field path incorrect (should be 'embeddings')")
    
    print("\n" + "=" * 80)
    print("Verification complete!")
    print("=" * 80)
    
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
