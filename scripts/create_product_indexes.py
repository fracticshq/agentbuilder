"""
Add indexes for product cards structured data.
Run this script to add new indexes to the knowledge_base collection.
"""

import os
import asyncio
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import structlog

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

logger = structlog.get_logger()


async def create_product_indexes():
    """Create indexes for product/dealer structured data."""
    
    # Get MongoDB URI from environment (same var name as config.py)
    mongodb_uri = os.getenv('MONGODB_URI')
    if not mongodb_uri:
        logger.error("MONGODB_URI not found in environment")
        return False
    
    try:
        # Connect to MongoDB
        logger.info("Connecting to MongoDB Atlas...")
        client = AsyncIOMotorClient(mongodb_uri)
        
        # Test connection
        await client.admin.command('ping')
        logger.info("Successfully connected to MongoDB Atlas!")
        
        # Get database
        db_name = "agent-builder"
        db = client[db_name]
        collection = db["knowledge_base"]
        
        logger.info("Creating indexes for product cards...")
        
        # 1. Content type + brand_id compound index (for filtering)
        logger.info("Creating content_type + brand_id index...")
        await collection.create_index([
            ("content_type", 1),
            ("agent_id", 1)
        ], name="content_type_agent_idx")
        logger.info("✅ content_type + agent_id index created")
        
        # 2. Product SKU index (for exact product lookups)
        logger.info("Creating product SKU index...")
        await collection.create_index(
            "product_data.sku",
            name="product_sku_idx",
            sparse=True  # Only index documents that have this field
        )
        logger.info("✅ product_data.sku index created")
        
        # 3. Product category index (for category filtering)
        logger.info("Creating product category index...")
        await collection.create_index(
            "product_data.category",
            name="product_category_idx",
            sparse=True
        )
        logger.info("✅ product_data.category index created")
        
        # 4. Product category + price compound index (for filtered searches)
        logger.info("Creating product category + price index...")
        await collection.create_index([
            ("product_data.category", 1),
            ("product_data.price", 1)
        ], name="product_filter_idx", sparse=True)
        logger.info("✅ product_data.category + price index created")
        
        # 5. Dealer city index (for location-based queries)
        logger.info("Creating dealer city index...")
        await collection.create_index(
            "dealer_data.city",
            name="dealer_city_idx",
            sparse=True
        )
        logger.info("✅ dealer_data.city index created")
        
        # 6. Dealer ID index (for exact dealer lookups)
        logger.info("Creating dealer ID index...")
        await collection.create_index(
            "dealer_data.dealer_id",
            name="dealer_id_idx",
            sparse=True
        )
        logger.info("✅ dealer_data.dealer_id index created")
        
        # List all indexes
        logger.info("\n=== Current Indexes ===")
        indexes = await collection.list_indexes().to_list(length=100)
        for idx in indexes:
            logger.info(f"  - {idx['name']}: {idx.get('key', {})}")
        
        logger.info("\n✅ All product card indexes created successfully!")
        
        # Close connection
        client.close()
        return True
        
    except Exception as e:
        logger.error("Error creating indexes", error=str(e), exc_info=True)
        return False


if __name__ == "__main__":
    import structlog
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer()
        ]
    )
    
    asyncio.run(create_product_indexes())
