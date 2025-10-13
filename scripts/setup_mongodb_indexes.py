"""
MongoDB Atlas Setup Script
Creates necessary indexes for Agent Builder Platform
"""

import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import structlog

logger = structlog.get_logger()


class MongoDBSetup:
    """Setup MongoDB Atlas collections and indexes."""
    
    def __init__(self):
        mongodb_uri = os.getenv("MONGODB_URI")
        if not mongodb_uri:
            raise ValueError("MONGODB_URI environment variable not set")
        
        db_name = os.getenv("MONGODB_DATABASE", "agent-builder")
        
        self.client = AsyncIOMotorClient(mongodb_uri)
        self.db = self.client[db_name]
        logger.info("MongoDB setup initialized", database=db_name)
    
    async def create_vector_search_index(self):
        """
        Create vector search index for MongoDB Atlas.
        
        Note: This requires Atlas Vector Search to be enabled on your cluster.
        The index must be created through the Atlas UI or Atlas CLI.
        """
        logger.info("=== Vector Search Index Setup ===")
        logger.info("Vector search indexes must be created through MongoDB Atlas UI")
        logger.info("Follow these steps:")
        logger.info("1. Go to MongoDB Atlas Console")
        logger.info("2. Navigate to your cluster → Search → Create Search Index")
        logger.info("3. Select 'JSON Editor' and use this configuration:")
        
        vector_index_config = {
            "mappings": {
                "dynamic": True,
                "fields": {
                    "embeddings": {
                        "dimensions": 1024,  # Voyage-large-2-instruct dimensions
                        "similarity": "cosine",
                        "type": "knnVector"
                    },
                    "content": {
                        "type": "string"
                    },
                    "title": {
                        "type": "string"
                    },
                    "metadata": {
                        "type": "document",
                        "dynamic": True
                    }
                }
            }
        }
        
        print("\n--- Vector Search Index Configuration (JSON) ---")
        import json
        print(json.dumps(vector_index_config, indent=2))
        print("\n4. Name the index: 'vector_index'")
        print("5. Apply it to collection: 'knowledge_base'")
        print("6. Create the index\n")
        
        return vector_index_config
    
    async def create_text_indexes(self):
        """Create text search indexes for BM25-like search."""
        try:
            collection = self.db["knowledge_base"]
            
            # Create text index on content, title, and section
            logger.info("Creating text search index...")
            await collection.create_index(
                [
                    ("content", "text"),
                    ("title", "text"),
                    ("section", "text")
                ],
                name="text_search_index",
                weights={
                    "title": 10,
                    "section": 5,
                    "content": 1
                },
                default_language="english"
            )
            logger.info("✅ Text search index created successfully")
            
        except Exception as e:
            if "already exists" in str(e):
                logger.info("ℹ️  Text search index already exists")
            else:
                logger.error("Failed to create text index", error=str(e))
                raise
    
    async def create_metadata_indexes(self):
        """Create indexes on commonly queried metadata fields."""
        try:
            collection = self.db["knowledge_base"]
            
            # Index on doc_id for lookups
            logger.info("Creating doc_id index...")
            await collection.create_index("doc_id", name="doc_id_idx")
            logger.info("✅ doc_id index created")
            
            # Index on chunk_id for unique lookups
            logger.info("Creating chunk_id index...")
            await collection.create_index("chunk_id", unique=True, name="chunk_id_idx")
            logger.info("✅ chunk_id index created")
            
            # Compound index for filtering by metadata
            logger.info("Creating metadata compound index...")
            await collection.create_index(
                [
                    ("metadata.content_type", 1),
                    ("metadata.brand_id", 1),
                    ("created_at", -1)
                ],
                name="metadata_filter_idx"
            )
            logger.info("✅ Metadata compound index created")
            
        except Exception as e:
            if "already exists" in str(e):
                logger.info("ℹ️  Metadata indexes already exist")
            else:
                logger.error("Failed to create metadata indexes", error=str(e))
                raise
    
    async def create_conversation_indexes(self):
        """Create indexes for conversation and memory collections."""
        try:
            # Conversations collection
            conversations = self.db["conversations"]
            
            logger.info("Creating conversation indexes...")
            await conversations.create_index("conversation_id", name="conversation_id_idx")
            await conversations.create_index("user_id", name="user_id_idx")
            await conversations.create_index(
                [("conversation_id", 1), ("created_at", -1)],
                name="conversation_timeline_idx"
            )
            logger.info("✅ Conversation indexes created")
            
            # User memory collection
            user_memory = self.db["user_memory"]
            
            logger.info("Creating user memory indexes...")
            await user_memory.create_index("user_id", name="memory_user_id_idx")
            await user_memory.create_index(
                [("user_id", 1), ("created_at", -1)],
                name="memory_timeline_idx"
            )
            logger.info("✅ User memory indexes created")
            
        except Exception as e:
            if "already exists" in str(e):
                logger.info("ℹ️  Conversation indexes already exist")
            else:
                logger.error("Failed to create conversation indexes", error=str(e))
                raise
    
    async def create_admin_indexes(self):
        """Create indexes for admin collections (brands, agents)."""
        try:
            # Brands collection
            brands = self.db["brands"]
            
            logger.info("Creating brands indexes...")
            await brands.create_index("slug", unique=True, name="brand_slug_idx")
            await brands.create_index("name", name="brand_name_idx")
            logger.info("✅ Brands indexes created")
            
            # Agents collection
            agents = self.db["agents"]
            
            logger.info("Creating agents indexes...")
            await agents.create_index(
                [("brand_id", 1), ("slug", 1)],
                unique=True,
                name="agent_brand_slug_idx"
            )
            await agents.create_index("brand_id", name="agent_brand_id_idx")
            await agents.create_index("status", name="agent_status_idx")
            logger.info("✅ Agents indexes created")
            
        except Exception as e:
            if "already exists" in str(e):
                logger.info("ℹ️  Admin indexes already exist")
            else:
                logger.error("Failed to create admin indexes", error=str(e))
                raise
    
    async def verify_indexes(self):
        """Verify all indexes were created successfully."""
        logger.info("\n=== Verifying Indexes ===")
        
        collections = [
            "knowledge_base",
            "conversations",
            "user_memory",
            "brands",
            "agents"
        ]
        
        for collection_name in collections:
            collection = self.db[collection_name]
            indexes = await collection.list_indexes().to_list(length=100)
            
            logger.info(f"\n{collection_name} indexes:")
            for idx in indexes:
                logger.info(f"  - {idx['name']}: {idx.get('key', {})}")
    
    async def setup_all(self):
        """Run complete setup."""
        logger.info("Starting MongoDB Atlas setup...")
        
        try:
            # Vector search index (manual setup required)
            await self.create_vector_search_index()
            
            # Text search indexes
            await self.create_text_indexes()
            
            # Metadata indexes
            await self.create_metadata_indexes()
            
            # Conversation indexes
            await self.create_conversation_indexes()
            
            # Admin indexes
            await self.create_admin_indexes()
            
            # Verify all indexes
            await self.verify_indexes()
            
            logger.info("\n✅ MongoDB setup completed successfully!")
            logger.info("⚠️  Remember to create the vector search index manually in Atlas UI")
            
        except Exception as e:
            logger.error("Setup failed", error=str(e), exc_info=True)
            raise
        finally:
            self.client.close()


async def main():
    """Main setup function."""
    # Configure logging
    import structlog
    structlog.configure(
        processors=[
            structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    setup = MongoDBSetup()
    await setup.setup_all()


if __name__ == "__main__":
    # Load environment variables
    from pathlib import Path
    env_file = Path(__file__).parent.parent / "apps" / "api" / ".env"
    
    if env_file.exists():
        print(f"Loading environment from {env_file}")
        from dotenv import load_dotenv
        load_dotenv(env_file)
    else:
        print("⚠️  No .env file found, using system environment variables")
    
    # Run setup
    asyncio.run(main())
