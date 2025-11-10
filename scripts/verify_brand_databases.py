#!/usr/bin/env python3
"""
Verification script for brand-specific database architecture.

This script verifies:
1. System database connectivity and structure
2. Brand database creation and indexes
3. Connection manager functionality  
4. Agent-to-brand mapping

Usage:
    python scripts/verify_brand_databases.py
"""

import asyncio
import os
from typing import Dict, List
import structlog
from motor.motor_asyncio import AsyncIOMotorClient

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


class BrandDatabaseVerifier:
    """Verifies brand-specific database architecture."""
    
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
    
    async def verify_system_database(self) -> Dict:
        """Verify system database structure."""
        system_db = self.client[self.system_db_name]
        results = {"exists": True, "collections": {}, "indexes": {}}
        
        try:
            # Check required collections exist
            collections = await system_db.list_collection_names()
            required_collections = ["brands", "users", "agents", "audit_logs"]
            
            for collection_name in required_collections:
                exists = collection_name in collections
                results["collections"][collection_name] = exists
                
                if exists:
                    collection = system_db[collection_name]
                    count = await collection.count_documents({})
                    indexes = await collection.index_information()
                    results["indexes"][collection_name] = {
                        "count": count,
                        "indexes": list(indexes.keys())
                    }
            
            logger.info("System database verified", 
                       database=self.system_db_name,
                       collections=len([c for c in results["collections"].values() if c]))
            
        except Exception as e:
            logger.error("System database verification failed", error=str(e))
            results["exists"] = False
            results["error"] = str(e)
        
        return results
    
    async def get_brands(self) -> List[Dict]:
        """Get all brands from system database."""
        system_db = self.client[self.system_db_name]
        brands = []
        
        try:
            brands_collection = system_db.brands
            async for brand in brands_collection.find({}):
                brands.append({
                    "id": brand.get("id"),
                    "slug": brand.get("slug"), 
                    "name": brand.get("name"),
                    "created_at": brand.get("created_at")
                })
        except Exception as e:
            logger.error("Failed to get brands", error=str(e))
        
        return brands
    
    async def verify_brand_database(self, brand_slug: str) -> Dict:
        """Verify brand-specific database structure."""
        brand_db = self.client[brand_slug]
        results = {"exists": True, "collections": {}, "indexes": {}}
        
        try:
            # Check required collections exist
            collections = await brand_db.list_collection_names()
            required_collections = [
                "knowledge_base", "conversations", "short_term_memory",
                "episodic_memory", "semantic_memory", "graph_memory"
            ]
            
            for collection_name in required_collections:
                exists = collection_name in collections
                results["collections"][collection_name] = exists
                
                if exists:
                    collection = brand_db[collection_name]
                    count = await collection.count_documents({})
                    indexes = await collection.index_information()
                    results["indexes"][collection_name] = {
                        "count": count,
                        "indexes": list(indexes.keys())
                    }
            
            logger.info("Brand database verified", 
                       brand=brand_slug,
                       collections=len([c for c in results["collections"].values() if c]))
            
        except Exception as e:
            logger.error("Brand database verification failed", brand=brand_slug, error=str(e))
            results["exists"] = False
            results["error"] = str(e)
        
        return results
    
    async def verify_agents(self) -> List[Dict]:
        """Verify agents and their brand associations."""
        system_db = self.client[self.system_db_name]
        agents = []
        
        try:
            agents_collection = system_db.agents
            async for agent in agents_collection.find({}):
                agents.append({
                    "id": agent.get("id"),
                    "name": agent.get("name"),
                    "brand_slug": agent.get("brand_slug"),
                    "status": agent.get("status"),
                    "created_at": agent.get("created_at")
                })
        except Exception as e:
            logger.error("Failed to get agents", error=str(e))
        
        return agents
    
    async def verify_connection_manager(self):
        """Verify connection manager functionality."""
        results = {"system_db": False, "brand_dbs": {}}
        
        try:
            # Test system database access
            system_db = self.client[self.system_db_name]
            await system_db.command('ping')
            results["system_db"] = True
            logger.info("Connection manager system DB test passed")
            
            # Test brand database access
            brands = await self.get_brands()
            for brand in brands:
                brand_slug = brand["slug"]
                try:
                    brand_db = self.client[brand_slug]
                    await brand_db.command('ping')
                    results["brand_dbs"][brand_slug] = True
                    logger.info("Connection manager brand DB test passed", brand=brand_slug)
                except Exception as e:
                    results["brand_dbs"][brand_slug] = False
                    logger.error("Connection manager brand DB test failed", brand=brand_slug, error=str(e))
            
        except Exception as e:
            logger.error("Connection manager verification failed", error=str(e))
            results["error"] = str(e)
        
        return results
    
    async def run_verification(self):
        """Run complete verification process."""
        try:
            await self.connect()
            
            print("=" * 80)
            print("BRAND DATABASE ARCHITECTURE VERIFICATION")
            print("=" * 80)
            
            # 1. Verify system database
            print("\n1. System Database Verification")
            print("-" * 40)
            system_results = await self.verify_system_database()
            
            if system_results["exists"]:
                print("✅ System database exists")
                for collection, exists in system_results["collections"].items():
                    status = "✅" if exists else "❌"
                    count = system_results["indexes"].get(collection, {}).get("count", 0)
                    print(f"   {status} {collection}: {count} documents")
            else:
                print("❌ System database missing or inaccessible")
                return
            
            # 2. Get brands and verify their databases
            print("\n2. Brand Database Verification")
            print("-" * 40)
            brands = await self.get_brands()
            
            if not brands:
                print("⚠️  No brands found in system database")
            else:
                for brand in brands:
                    print(f"\nBrand: {brand['name']} ({brand['slug']})")
                    brand_results = await self.verify_brand_database(brand["slug"])
                    
                    if brand_results["exists"]:
                        print("  ✅ Brand database exists")
                        for collection, exists in brand_results["collections"].items():
                            status = "✅" if exists else "❌"
                            count = brand_results["indexes"].get(collection, {}).get("count", 0)
                            print(f"     {status} {collection}: {count} documents")
                    else:
                        print("  ❌ Brand database missing or inaccessible")
            
            # 3. Verify agents
            print("\n3. Agent-Brand Association Verification")
            print("-" * 40)
            agents = await self.verify_agents()
            
            if not agents:
                print("⚠️  No agents found in system database")
            else:
                for agent in agents:
                    brand_status = "✅" if agent["brand_slug"] else "❌"
                    print(f"  {brand_status} {agent['name']} → {agent['brand_slug'] or 'NO BRAND'}")
            
            # 4. Connection manager test
            print("\n4. Connection Manager Verification")
            print("-" * 40)
            conn_results = await self.verify_connection_manager()
            
            if conn_results["system_db"]:
                print("  ✅ System database connection")
            else:
                print("  ❌ System database connection failed")
            
            for brand_slug, success in conn_results["brand_dbs"].items():
                status = "✅" if success else "❌"
                print(f"  {status} Brand database connection: {brand_slug}")
            
            # Summary
            print("\n" + "=" * 80)
            print("VERIFICATION SUMMARY")
            print("=" * 80)
            
            total_brands = len(brands)
            working_brands = len([b for b in conn_results["brand_dbs"].values() if b])
            total_agents = len(agents)
            mapped_agents = len([a for a in agents if a["brand_slug"]])
            
            print(f"System Database: {'✅' if system_results['exists'] else '❌'}")
            print(f"Brands: {working_brands}/{total_brands} working")
            print(f"Agents: {mapped_agents}/{total_agents} properly mapped")
            
            if system_results["exists"] and working_brands == total_brands and mapped_agents == total_agents:
                print("\n🎉 All verifications passed! Brand database architecture is working correctly.")
            else:
                print("\n⚠️  Some verifications failed. Review the results above.")
            
        except Exception as e:
            logger.error("Verification failed", error=str(e), exc_info=True)
        finally:
            await self.disconnect()


async def main():
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    mongodb_uri = os.getenv("MONGODB_URI")
    if not mongodb_uri:
        print("❌ MONGODB_URI environment variable not set")
        return
    
    system_db_name = os.getenv("MONGO_SYSTEM_DB", "system")
    
    verifier = BrandDatabaseVerifier(
        mongodb_uri=mongodb_uri,
        system_db_name=system_db_name
    )
    
    await verifier.run_verification()


if __name__ == "__main__":
    asyncio.run(main())