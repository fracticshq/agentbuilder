"""
Clean up knowledge base and prepare for fresh document upload.
"""

import os
import sys
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv('apps/api/.env')

def main():
    client = MongoClient(os.getenv('MONGODB_URI'))
    db = client['agent-builder']
    
    print("=" * 80)
    print("KNOWLEDGE BASE CLEANUP")
    print("=" * 80)
    
    # Clean up knowledge_base collection
    kb = db.knowledge_base
    
    print("\n1. Current state:")
    total = kb.count_documents({})
    with_agent = kb.count_documents({'agent_id': {'$ne': None}})
    without_agent = kb.count_documents({'agent_id': None})
    
    print(f"   Total chunks: {total}")
    print(f"   With agent_id: {with_agent}")
    print(f"   Without agent_id: {without_agent}")
    
    # Show chunks without agent_id
    if without_agent > 0:
        print("\n2. Chunks without agent_id:")
        for chunk in kb.find({'agent_id': None}).limit(10):
            print(f"   - {chunk.get('filename', 'unknown')} (doc_id: {chunk.get('doc_id')})")
    
    # Ask for confirmation to delete
    if without_agent > 0:
        print(f"\n3. Ready to delete {without_agent} chunks without agent_id")
        response = input("   Delete these chunks? (yes/no): ")
        
        if response.lower() == 'yes':
            result = kb.delete_many({'agent_id': None})
            print(f"   ✅ Deleted {result.deleted_count} chunks")
        else:
            print("   ⏭️  Skipped deletion")
    
    # Clean up documents collection (metadata)
    docs = db.documents
    corrupted = docs.count_documents({'doc_id': None})
    
    if corrupted > 0:
        print(f"\n4. Found {corrupted} corrupted document records")
        result = docs.delete_many({'doc_id': None})
        print(f"   ✅ Deleted {result.deleted_count} corrupted records")
    
    # Final state
    print("\n" + "=" * 80)
    print("FINAL STATE")
    print("=" * 80)
    final_total = kb.count_documents({})
    final_with_agent = kb.count_documents({'agent_id': {'$ne': None}})
    
    print(f"Total chunks: {final_total}")
    print(f"Chunks with agent_id: {final_with_agent}")
    
    # Show documents by agent
    print("\n" + "=" * 80)
    print("DOCUMENTS BY AGENT")
    print("=" * 80)
    
    pipeline = [
        {'$match': {'agent_id': {'$ne': None}}},
        {'$group': {
            '_id': '$agent_id',
            'chunk_count': {'$sum': 1},
            'filenames': {'$addToSet': '$filename'}
        }},
        {'$sort': {'chunk_count': -1}}
    ]
    
    for doc in kb.aggregate(pipeline):
        print(f"\nAgent: {doc['_id']}")
        print(f"  Total chunks: {doc['chunk_count']}")
        print(f"  Files: {', '.join(doc['filenames'][:5])}")
    
    client.close()
    
    print("\n" + "=" * 80)
    print("✅ CLEANUP COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Go to: http://localhost:3000/agents/<your-agent-id>")
    print("2. Upload your documents (they will now be properly associated with the agent)")
    print("3. Check that documents appear in the knowledge base list")
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
