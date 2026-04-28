#!/usr/bin/env python3
"""
Setup script for brand-specific database architecture.

This script:
1. Creates the system database with brands, users, and agents collections
2. Creates sample brand databases
3. Sets up required indexes for optimal performance

Usage:
    python scripts/setup_brand_databases.py --create-sample-data
    python scripts/setup_brand_databases.py --brands essco-bathware,acme-corp
"""

import asyncio
import argparse
import os
from typing import List
from motor.motor_asyncio import AsyncIOMotorClient
import structlog
from datetime import datetime

# Configure logging
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


class BrandDatabaseSetup:
    """Sets up brand-specific database architecture."""
    
    def __init__(self, mongodb_uri: str, system_db_name: str = "system"):
        self.mongodb_uri = mongodb_uri
        self.system_db_name = system_db_name
        self.client = None
        
    async def connect(self):
        """Initialize MongoDB connection."""
        self.client = AsyncIOMotorClient(self.mongodb_uri)
        await self.client.admin.command('ping')
        logger.info("Connected to MongoDB", uri=self.mongodb_uri.split('@')[-1])
        
    async def disconnect(self):
        """Close MongoDB connection."""
        if self.client:
            self.client.close()
            logger.info("Disconnected from MongoDB")
    
    async def setup_system_database(self):
        """Create system database with required collections."""
        system_db = self.client[self.system_db_name]
        
        logger.info("Setting up system database", database=self.system_db_name)
        
        # Brands collection
        brands_collection = system_db.brands
        await brands_collection.create_index("slug", unique=True)
        await brands_collection.create_index("name")
        await brands_collection.create_index("industry")
        await brands_collection.create_index("created_at")
        
        # Users collection (global users across all brands)
        users_collection = system_db.users
        await users_collection.create_index("email", unique=True)
        await users_collection.create_index("created_at")
        await users_collection.create_index("status")
        
        # Agents collection (centralized agent management)
        agents_collection = system_db.agents
        await agents_collection.create_index("id", unique=True)
        await agents_collection.create_index("brand_slug")
        await agents_collection.create_index([("brand_slug", 1), ("name", 1)])
        await agents_collection.create_index("status")
        await agents_collection.create_index("created_at")
        
        # Audit logs collection
        audit_collection = system_db.audit_logs
        await audit_collection.create_index([("timestamp", -1)])
        await audit_collection.create_index("brand_slug")
        await audit_collection.create_index("action")
        await audit_collection.create_index("user_id")
        
        logger.info("System database setup complete")
    
    async def setup_brand_database(self, brand_slug: str):
        """Create brand-specific database with required collections."""
        brand_db = self.client[brand_slug]
        logger.info("Setting up brand database", brand=brand_slug)
        
        # Knowledge base collection (documents, chunks, embeddings)
        kb_collection = brand_db.knowledge_base
        await kb_collection.create_index([("embeddings", "2dsphere")])  # Vector search
        await kb_collection.create_index("doc_id")
        await kb_collection.create_index("chunk_id")
        await kb_collection.create_index("metadata.url")
        await kb_collection.create_index("metadata.sku")
        await kb_collection.create_index("metadata.category")
        await kb_collection.create_index("created_at")
        
        # Conversations collection (chat history)
        conversations = brand_db.conversations
        await conversations.create_index("conversation_id")
        await conversations.create_index("user_id")
        await conversations.create_index([("conversation_id", 1), ("timestamp", 1)])
        await conversations.create_index([("user_id", 1), ("timestamp", -1)])
        await conversations.create_index("agent_id")
        
        # Short-term memory (conversation context)
        short_term = brand_db.short_term_memory
        await short_term.create_index("conversation_id")
        await short_term.create_index([("conversation_id", 1), ("timestamp", 1)])
        await short_term.create_index("expires_at", expireAfterSeconds=0)  # TTL index
        
        # Episodic memory (user facts and preferences)
        episodic = brand_db.episodic_memory
        await episodic.create_index("user_id")
        await episodic.create_index([("user_id", 1), ("confidence", -1)])
        await episodic.create_index("fact_type")
        await episodic.create_index("created_at")
        await episodic.create_index("expires_at", expireAfterSeconds=0)  # TTL index
        
        # Semantic memory (knowledge base versioning)
        semantic = brand_db.semantic_memory
        await semantic.create_index("doc_id")
        await semantic.create_index("version")
        await semantic.create_index([("doc_id", 1), ("version", -1)])
        await semantic.create_index("created_at")
        
        # Graph memory (rules, policies, escalations)
        graph = brand_db.graph_memory
        await graph.create_index("rule_type")
        await graph.create_index("severity")
        await graph.create_index("category")
        await graph.create_index("active")
        
        logger.info("Brand database setup complete", brand=brand_slug)
    
    async def create_sample_brand(self, brand_slug: str, brand_name: str):
        """Create a sample brand with basic configuration."""
        system_db = self.client[self.system_db_name]
        
        # Check if brand already exists
        existing_brand = await system_db.brands.find_one({"slug": brand_slug})
        if existing_brand:
            logger.info("Brand already exists", brand_slug=brand_slug)
            return
        
        # Create brand document
        brand_doc = {
            "id": brand_slug,
            "slug": brand_slug,
            "name": brand_name,
            "description": f"Sample brand: {brand_name}",
            "industry": "Technology",
            "website": f"https://{brand_slug}.com",
            "contact_info": {
                "email": f"info@{brand_slug}.com",
                "phone": "+1-555-0123"
            },
            "brand_voice": {
                "tone": "professional",
                "style": "helpful",
                "personality": ["expert", "approachable", "solution-oriented"]
            },
            "colors": {
                "primary": "#2563eb",
                "secondary": "#64748b",
                "accent": "#059669"
            },
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await system_db.brands.insert_one(brand_doc)
        logger.info("Sample brand created", brand_slug=brand_slug, brand_name=brand_name)
        
        # Create sample agent for this brand
        agent_doc = {
            "id": f"{brand_slug}-agent-001",
            "name": f"{brand_name} Assistant",
            "description": f"AI assistant for {brand_name} customer support",
            "brand_slug": brand_slug,
            "system_prompt": f"""You are the {brand_name} AI Assistant, a knowledgeable customer service representative.

Your role:
- Help customers find the right products and services
- Provide helpful guidance and support
- Answer questions professionally and accurately
- Maintain {brand_name}'s brand voice and values

Guidelines:
- Always be professional, helpful, and solution-oriented
- Use the knowledge base to provide accurate information
- If you don't know something, direct customers to human support
- Focus on {brand_name}'s quality and customer satisfaction""",
            "configuration": {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "temperature": 0.7,
                    "max_tokens": 1000
                },
                "embedding": {
                    "provider": "voyage",
                    "model": "voyage-3-large"
                },
                "rag": {
                    "enabled": True,
                    "top_k": 5,
                    "similarity_threshold": 0.7
                }
            },
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await system_db.agents.insert_one(agent_doc)
        logger.info("Sample agent created", agent_id=agent_doc["id"], brand_slug=brand_slug)
    
    async def setup(self, brand_slugs: List[str], create_sample_data: bool = False):
        """Setup complete brand database architecture."""
        try:
            await self.connect()
            
            # Setup system database
            await self.setup_system_database()
            
            # Setup brand databases
            for brand_slug in brand_slugs:
                await self.setup_brand_database(brand_slug)
                
                if create_sample_data:
                    brand_name = brand_slug.replace('-', ' ').title()
                    await self.create_sample_brand(brand_slug, brand_name)
            
            logger.info("Brand database architecture setup complete",
                       system_db=self.system_db_name,
                       brand_databases=brand_slugs)
            
        except Exception as e:
            logger.error("Setup failed", error=str(e), exc_info=True)
            raise
        finally:
            await self.disconnect()


async def main():
    parser = argparse.ArgumentParser(description="Setup brand-specific databases")
    parser.add_argument("--system-db", default="system", help="System database name")
    parser.add_argument("--brands", help="Comma-separated list of brand slugs to create")
    parser.add_argument("--create-sample-data", action="store_true", help="Create sample brands and agents")
    
    args = parser.parse_args()
    
    # Default brands if none specified
    if args.brands:
        brand_slugs = [slug.strip() for slug in args.brands.split(',')]
    else:
        brand_slugs = ["essco-bathware", "demo-brand"]
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    mongodb_uri = os.getenv("MONGODB_URI")
    if not mongodb_uri:
        logger.error("MONGODB_URI environment variable not set")
        return
    
    setup = BrandDatabaseSetup(
        mongodb_uri=mongodb_uri,
        system_db_name=args.system_db
    )
    
    await setup.setup(brand_slugs, create_sample_data=args.create_sample_data)


if __name__ == "__main__":
    asyncio.run(main())