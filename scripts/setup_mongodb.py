"""
MongoDB Atlas setup script for Agent Builder Platform.
"""

import os
import sys
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

# Add packages to path
sys.path.append('/Users/anantmendiratta/Desktop/agent-builder/packages')

def setup_mongodb():
    """Initialize MongoDB Atlas with required collections and indexes."""
    
    # Get connection string from environment
    mongodb_uri = os.getenv('MONGODB_URI')
    if not mongodb_uri:
        print("❌ MONGODB_URI not found in environment variables")
        return False
    
    try:
        # Connect to MongoDB
        print("🔌 Connecting to MongoDB Atlas...")
        client = MongoClient(mongodb_uri)
        
        # Test connection
        client.admin.command('ping')
        print("✅ Successfully connected to MongoDB Atlas!")
        
        # Get database
        db_name = os.getenv('MONGODB_DATABASE', 'agent-builder')
        db = client[db_name]
        
        # Create collections
        collections_to_create = [
            'documents',           # Document storage
            'conversations',       # Conversation memory
            'episodic_memory',     # Episodic memory layer
            'semantic_memory',     # Semantic memory layer
            'procedural_memory',   # Procedural memory layer
            'users',              # User data
            'sessions',           # Session data
            'metrics'             # Analytics data
        ]
        
        print("📁 Creating collections...")
        for collection_name in collections_to_create:
            if collection_name not in db.list_collection_names():
                db.create_collection(collection_name)
                print(f"   ✅ Created collection: {collection_name}")
            else:
                print(f"   ℹ️  Collection already exists: {collection_name}")
        
        # Create indexes for better performance
        print("📊 Creating indexes...")
        
        # Documents collection indexes
        documents = db.documents
        documents.create_index([("content", "text")])  # Text search
        documents.create_index([("metadata.url", 1)])  # URL lookups
        documents.create_index([("created_at", -1)])   # Time-based queries
        
        # Conversations collection indexes
        conversations = db.conversations
        conversations.create_index([("conversation_id", 1)])
        conversations.create_index([("created_at", -1)])
        conversations.create_index([("conversation_id", 1), ("created_at", -1)])
        
        # Memory collections indexes
        for memory_type in ['episodic_memory', 'semantic_memory', 'procedural_memory']:
            memory_collection = db[memory_type]
            memory_collection.create_index([("conversation_id", 1)])
            memory_collection.create_index([("created_at", -1)])
            memory_collection.create_index([("type", 1)])
        
        print("✅ All indexes created successfully!")
        
        # Insert sample data for testing
        print("📝 Inserting sample data...")
        
        # Sample document
        sample_doc = {
            "content": "This is a sample document for testing the Agent Builder Platform.",
            "metadata": {
                "title": "Sample Document",
                "url": "http://example.com/sample",
                "type": "documentation"
            },
            "created_at": "2024-08-28T00:00:00Z",
            "embeddings": []  # Will be populated by embedding service
        }
        
        if documents.count_documents({"metadata.url": "http://example.com/sample"}) == 0:
            documents.insert_one(sample_doc)
            print("   ✅ Inserted sample document")
        
        print("🎉 MongoDB Atlas setup completed successfully!")
        print(f"📊 Database: {db_name}")
        print(f"📈 Collections created: {len(collections_to_create)}")
        
        return True
        
    except ConnectionFailure as e:
        print(f"❌ Failed to connect to MongoDB: {e}")
        return False
    except Exception as e:
        print(f"❌ Error setting up MongoDB: {e}")
        return False

if __name__ == "__main__":
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv('/Users/anantmendiratta/Desktop/agent-builder/apps/api/.env')
    
    success = setup_mongodb()
    if success:
        print("\n🚀 Your MongoDB Atlas database is ready!")
        print("   You can now run your Agent Builder Platform.")
    else:
        print("\n❌ Setup failed. Please check your configuration.")