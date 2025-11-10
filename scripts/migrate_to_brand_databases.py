#!/usr/bin/env python3
"""
Migration script to move from single database to brand-specific databases.

This script:
1. Creates system database for brands, users, and global data
2. Migrates existing agents to system database with brand association
3. Creates brand-specific databases for each brand
4. Migrates brand-specific data (knowledge_base, conversations, etc.) to respective brand databases
5. Preserves all existing data while reorganizing the structure

Usage:
    python scripts/migrate_to_brand_databases.py --source-db agent-builder --dry-run
    python scripts/migrate_to_brand_databases.py --source-db agent-builder --execute
"""

import asyncio
import argparse
import os
from typing import Dict, List, Any, Optional
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


class BrandDatabaseMigrator:
    """Migrates from single database to brand-specific databases."""
    
    def __init__(self, mongodb_uri: str, source_db_name: str, system_db_name: str = "system"):
        self.mongodb_uri = mongodb_uri
        self.source_db_name = source_db_name
        self.system_db_name = system_db_name
        self.client: Optional[AsyncIOMotorClient] = None
        
        # Collections that belong in system database
        self.system_collections = {
            "brands", "users", "audit_logs", "system_config", "global_settings"
        }
        
        # Collections that should be migrated to brand databases
        self.brand_collections = {
            "knowledge_base", "conversations", "episodic_memory", 
            "short_term_memory", "semantic_memory", "graph_memory",
            "documents", "chunks", "vectors"
        }
        
        # Agents collection needs special handling (moved to system with brand association)
        self.special_collections = {"agents"}
        
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
    
    async def analyze_existing_data(self) -> Dict[str, Any]:
        """Analyze existing database structure and data."""
        source_db = self.client[self.source_db_name]
        
        analysis = {
            "collections": {},
            "total_documents": 0,
            "brands_detected": set(),
            "agents_count": 0,
            "migration_plan": {}
        }
        
        # List all collections
        collections = await source_db.list_collection_names()
        logger.info("Found collections", collections=collections)
        
        for collection_name in collections:
            collection = source_db[collection_name]
            count = await collection.count_documents({})
            analysis["collections"][collection_name] = count
            analysis["total_documents"] += count
            
            # Try to detect brands from existing data
            if collection_name == "agents":
                analysis["agents_count"] = count
                async for agent in collection.find({}):
                    brand_id = agent.get("brand_id") or agent.get("brand") or "default-brand"
                    analysis["brands_detected"].add(brand_id)
            
            elif collection_name in self.brand_collections:
                # Look for brand_id fields
                async for doc in collection.find({}, {"brand_id": 1, "metadata.brand_id": 1}).limit(100):
                    brand_id = doc.get("brand_id") or doc.get("metadata", {}).get("brand_id")
                    if brand_id:
                        analysis["brands_detected"].add(brand_id)
        
        # Convert set to list for JSON serialization
        analysis["brands_detected"] = list(analysis["brands_detected"])
        
        # Create migration plan
        for collection_name in collections:
            if collection_name in self.system_collections:
                analysis["migration_plan"][collection_name] = "system"
            elif collection_name in self.brand_collections:
                analysis["migration_plan"][collection_name] = "brand_specific"
            elif collection_name in self.special_collections:
                analysis["migration_plan"][collection_name] = "special_handling"
            else:
                analysis["migration_plan"][collection_name] = "unknown"
        
        return analysis
    
    async def create_system_database(self) -> None:
        """Create system database with required collections."""
        system_db = self.client[self.system_db_name]
        
        # Create system collections with indexes
        logger.info("Creating system database collections")
        
        # Brands collection
        brands_collection = system_db.brands
        await brands_collection.create_index("slug", unique=True)
        await brands_collection.create_index("name")
        
        # Users collection (global users across all brands)
        users_collection = system_db.users
        await users_collection.create_index("email", unique=True)
        await users_collection.create_index("created_at")
        
        # Agents collection (moved from brand DBs to system for management)
        agents_collection = system_db.agents
        await agents_collection.create_index("id", unique=True)
        await agents_collection.create_index("brand_slug")
        await agents_collection.create_index([("brand_slug", 1), ("name", 1)])
        
        # Audit logs collection
        audit_collection = system_db.audit_logs
        await audit_collection.create_index([("timestamp", -1)])
        await audit_collection.create_index("brand_slug")
        await audit_collection.create_index("action")
        
        logger.info("System database created", database=self.system_db_name)
    
    async def migrate_brands_and_agents(self, brands: List[str]) -> Dict[str, str]:
        """Migrate agents to system database and create brand records."""
        source_db = self.client[self.source_db_name]
        system_db = self.client[self.system_db_name]
        
        brand_slug_map = {}
        
        # Create brand records if they don't exist
        for brand_id in brands:
            brand_slug = brand_id.lower().replace(' ', '-').replace('_', '-')
            brand_slug_map[brand_id] = brand_slug
            
            existing_brand = await system_db.brands.find_one({"slug": brand_slug})
            if not existing_brand:
                brand_doc = {
                    "id": brand_id,
                    "slug": brand_slug,
                    "name": brand_id.replace('-', ' ').title(),
                    "description": f"Migrated brand: {brand_id}",
                    "industry": "Unknown",
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "migration_source": self.source_db_name
                }
                await system_db.brands.insert_one(brand_doc)
                logger.info("Created brand", brand_slug=brand_slug, brand_id=brand_id)
        
        # Migrate agents to system database
        if await source_db.list_collection_names(filter={"name": "agents"}):
            agents_collection = source_db.agents
            system_agents = system_db.agents
            
            async for agent in agents_collection.find({}):
                # Determine brand for this agent
                brand_id = agent.get("brand_id") or agent.get("brand") or "default-brand"
                brand_slug = brand_slug_map.get(brand_id, brand_id.lower().replace(' ', '-'))
                
                # Update agent document structure for system database
                agent_doc = {
                    "id": agent.get("id") or str(agent.get("_id")),
                    "name": agent.get("name", f"Agent {agent.get('_id')}"),
                    "description": agent.get("description", "Migrated agent"),
                    "brand_slug": brand_slug,
                    "brand_id": brand_id,  # Keep original for reference
                    "system_prompt": agent.get("system_prompt", ""),
                    "configuration": agent.get("configuration", {}),
                    "status": agent.get("status", "active"),
                    "created_at": agent.get("created_at", datetime.utcnow()),
                    "updated_at": datetime.utcnow(),
                    "migration_source": self.source_db_name,
                    "original_id": str(agent.get("_id"))
                }
                
                await system_agents.insert_one(agent_doc)
                logger.info("Migrated agent", agent_id=agent_doc["id"], brand_slug=brand_slug)
        
        return brand_slug_map
    
    async def create_brand_databases(self, brand_slugs: List[str]) -> None:
        """Create brand-specific databases with required collections."""
        for brand_slug in brand_slugs:
            brand_db = self.client[brand_slug]
            logger.info("Creating brand database", brand=brand_slug)
            
            # Create brand-specific collections with indexes
            
            # Knowledge base collection
            kb_collection = brand_db.knowledge_base
            await kb_collection.create_index([("embeddings", "2dsphere")])  # Vector search
            await kb_collection.create_index("doc_id")
            await kb_collection.create_index("metadata.url")
            await kb_collection.create_index("metadata.sku")
            
            # Conversations collection
            conversations = brand_db.conversations
            await conversations.create_index("conversation_id")
            await conversations.create_index("user_id")
            await conversations.create_index([("conversation_id", 1), ("timestamp", 1)])
            
            # Memory collections
            short_term = brand_db.short_term_memory
            await short_term.create_index("conversation_id")
            await short_term.create_index([("conversation_id", 1), ("timestamp", 1)])
            
            episodic = brand_db.episodic_memory
            await episodic.create_index("user_id")
            await episodic.create_index([("user_id", 1), ("confidence", -1)])
            
            semantic = brand_db.semantic_memory
            await semantic.create_index("doc_id")
            await semantic.create_index("version")
            
            graph = brand_db.graph_memory
            await graph.create_index("rule_type")
            await graph.create_index("severity")
            
            logger.info("Brand database created", brand=brand_slug)
    
    async def migrate_brand_data(self, brand_slug_map: Dict[str, str]) -> None:
        """Migrate brand-specific data to respective brand databases."""
        source_db = self.client[self.source_db_name]
        
        for collection_name in self.brand_collections:
            if collection_name in await source_db.list_collection_names():
                source_collection = source_db[collection_name]
                total_docs = await source_collection.count_documents({})
                
                if total_docs == 0:
                    continue
                    
                logger.info("Migrating collection", collection=collection_name, total_docs=total_docs)
                
                async for doc in source_collection.find({}):
                    # Determine which brand this document belongs to
                    brand_id = (
                        doc.get("brand_id") or 
                        doc.get("metadata", {}).get("brand_id") or
                        "default-brand"
                    )
                    
                    brand_slug = brand_slug_map.get(brand_id, brand_id.lower().replace(' ', '-'))
                    
                    # Insert into brand-specific database
                    brand_db = self.client[brand_slug]
                    brand_collection = brand_db[collection_name]
                    
                    # Clean up document (remove MongoDB ObjectId if needed)
                    doc.pop("_id", None)
                    doc["migrated_at"] = datetime.utcnow()
                    doc["migration_source"] = self.source_db_name
                    
                    await brand_collection.insert_one(doc)
                
                logger.info("Collection migrated", collection=collection_name)
    
    async def create_migration_log(self, analysis: Dict[str, Any], brand_slug_map: Dict[str, str]) -> None:
        """Create a log of the migration process."""
        system_db = self.client[self.system_db_name]
        
        migration_log = {
            "migration_id": f"brand_db_migration_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.utcnow(),
            "source_database": self.source_db_name,
            "system_database": self.system_db_name,
            "brand_slug_mapping": brand_slug_map,
            "analysis": analysis,
            "status": "completed",
            "version": "1.0"
        }
        
        await system_db.migration_logs.insert_one(migration_log)
        logger.info("Migration log created", migration_id=migration_log["migration_id"])
    
    async def migrate(self, dry_run: bool = True) -> None:
        """Execute the complete migration process."""
        try:
            await self.connect()
            
            # Step 1: Analyze existing data
            logger.info("Step 1: Analyzing existing data structure")
            analysis = await self.analyze_existing_data()
            
            logger.info("Migration Analysis", 
                       total_docs=analysis["total_documents"],
                       brands_detected=len(analysis["brands_detected"]),
                       collections=len(analysis["collections"]))
            
            if dry_run:
                logger.info("DRY RUN - No changes will be made")
                logger.info("Analysis Complete", analysis=analysis)
                return
            
            # Step 2: Create system database
            logger.info("Step 2: Creating system database")
            await self.create_system_database()
            
            # Step 3: Migrate brands and agents
            logger.info("Step 3: Migrating brands and agents")
            brand_slug_map = await self.migrate_brands_and_agents(analysis["brands_detected"])
            
            # Step 4: Create brand-specific databases
            logger.info("Step 4: Creating brand-specific databases")
            await self.create_brand_databases(list(brand_slug_map.values()))
            
            # Step 5: Migrate brand-specific data
            logger.info("Step 5: Migrating brand-specific data")
            await self.migrate_brand_data(brand_slug_map)
            
            # Step 6: Create migration log
            logger.info("Step 6: Creating migration log")
            await self.create_migration_log(analysis, brand_slug_map)
            
            logger.info("Migration completed successfully!")
            logger.info("New database structure:",
                       system_db=self.system_db_name,
                       brand_databases=list(brand_slug_map.values()))
            
        except Exception as e:
            logger.error("Migration failed", error=str(e), exc_info=True)
            raise
        finally:
            await self.disconnect()


async def main():
    parser = argparse.ArgumentParser(description="Migrate to brand-specific databases")
    parser.add_argument("--source-db", required=True, help="Source database name")
    parser.add_argument("--system-db", default="system", help="System database name")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only, don't migrate")
    parser.add_argument("--execute", action="store_true", help="Execute migration")
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        logger.error("Must specify either --dry-run or --execute")
        return
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    mongodb_uri = os.getenv("MONGODB_URI")
    if not mongodb_uri:
        logger.error("MONGODB_URI environment variable not set")
        return
    
    migrator = BrandDatabaseMigrator(
        mongodb_uri=mongodb_uri,
        source_db_name=args.source_db,
        system_db_name=args.system_db
    )
    
    await migrator.migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())