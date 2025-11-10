"""
Setup Brand Memory Layers - Complete Mirix-Inspired Architecture

This script creates all memory collections for a brand database:
- Semantic Memory (knowledge_base, knowledge_sources)
- Core Memory (conversations, short_term_summaries)
- Episodic Memory (episodic_memory)
- Procedural Memory (procedural_memory) - NEW
- Graph Memory (graph_memory)
- Resource Memory (resource_memory) - NEW
- Knowledge Vault (knowledge_vault) - NEW

Usage:
    python scripts/setup_brand_memory_layers.py --brand-slug essco-bathware
"""

import asyncio
import os
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import argparse

# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), '..', 'apps', 'api', '.env')
load_dotenv(env_path)


async def create_index_safe(collection, index_spec, **kwargs):
    """Create index safely, skipping if already exists"""
    try:
        await collection.create_index(index_spec, **kwargs)
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate key" in str(e).lower():
            pass  # Index already exists, skip
        else:
            raise


async def setup_brand_memory_layers(brand_slug: str):
    """Create all memory layer collections and indexes for a brand."""
    
    mongodb_uri = os.getenv("MONGODB_URI")
    if not mongodb_uri:
        raise ValueError("MONGODB_URI not found in environment")
    
    client = AsyncIOMotorClient(mongodb_uri)
    brand_db = client[brand_slug]
    
    print(f"\n🎯 Setting up memory layers for brand: {brand_slug}")
    print(f"📁 Database: {brand_slug}")
    
    # ========================================================================
    # 1. SEMANTIC MEMORY
    # ========================================================================
    print("\n📚 1. SEMANTIC MEMORY")
    
    # 1.1 knowledge_base
    kb_collection = brand_db.knowledge_base
    print("  ├─ knowledge_base")
    
    # Text index for BM25
    try:
        await kb_collection.create_index(
            [("content", "text"), ("title", "text")],
            name="text_search_idx",
            default_language="english"
        )
        print("  │  ✓ BM25 Text Index created")
    except Exception as e:
        print(f"  │  ⚠️  Text index: {e}")
    
    # Metadata indexes
    await kb_collection.create_index([("content_type", 1)])
    await kb_collection.create_index([("metadata.category", 1)])
    await kb_collection.create_index([("doc_id", 1), ("section", 1)])
    print("  │  ✓ Metadata indexes created")
    
    print("  │  ⚠️  Vector Index (vector_index) must be created in Atlas UI:")
    print("  │     - Name: vector_index")
    print("  │     - Field: embedding")
    print("  │     - Dimensions: 1024")
    print("  │     - Similarity: cosine")
    
    # 1.2 knowledge_sources (NEW)
    sources_collection = brand_db.knowledge_sources
    print("  └─ knowledge_sources (NEW)")
    
    await sources_collection.create_index([("source_id", 1)], unique=True)
    await sources_collection.create_index([("source_type", 1)])
    print("     ✓ Source indexes created")
    
    # Insert sample source registry
    sample_source = {
        "source_id": "essco-website",
        "source_type": "website",
        "name": "Essco Bathware Official Website",
        "url": "https://www.esscobathware.com",
        "last_crawled": datetime.utcnow(),
        "status": "active",
        "metadata": {
            "crawl_frequency": "weekly",
            "priority": "high"
        }
    }
    await sources_collection.update_one(
        {"source_id": sample_source["source_id"]},
        {"$setOnInsert": sample_source},
        upsert=True
    )
    print("     ✓ Sample source registered")
    
    # ========================================================================
    # 2. CORE MEMORY
    # ========================================================================
    print("\n💬 2. CORE MEMORY")
    
    # 2.1 conversations
    conv_collection = brand_db.conversations
    print("  ├─ conversations")
    
    await create_index_safe(conv_collection, [("conversation_id", 1)], unique=True)
    await create_index_safe(conv_collection, [("user_id", 1)])
    await create_index_safe(conv_collection, [("agent_id", 1)])
    await create_index_safe(conv_collection, [("created_at", 1)], expireAfterSeconds=259200)  # 72h TTL
    print("     ✓ Conversation indexes verified/created (TTL: 72h)")
    
    # 2.2 short_term_summaries
    summary_collection = brand_db.short_term_summaries
    print("  └─ short_term_summaries")
    
    await create_index_safe(summary_collection, [("conversation_id", 1)])
    await create_index_safe(summary_collection, [("created_at", 1)], expireAfterSeconds=259200)  # 72h TTL
    print("     ✓ Summary indexes created (TTL: 72h)")
    
    # ========================================================================
    # 3. EPISODIC MEMORY
    # ========================================================================
    print("\n🧠 3. EPISODIC MEMORY")
    
    episodic_collection = brand_db.episodic_memory
    print("  └─ episodic_memory")
    
    await create_index_safe(episodic_collection, [("user_id", 1)])
    await create_index_safe(episodic_collection, [("fact_type", 1)])
    await create_index_safe(episodic_collection, [("confidence", -1)])
    await create_index_safe(episodic_collection, [("created_at", 1)], expireAfterSeconds=7776000)  # 90d TTL
    print("     ✓ Episodic indexes created (TTL: 90d)")
    
    # ========================================================================
    # 4. PROCEDURAL MEMORY (NEW)
    # ========================================================================
    print("\n⚙️  4. PROCEDURAL MEMORY (NEW)")
    
    procedural_collection = brand_db.procedural_memory
    print("  └─ procedural_memory")
    
    await create_index_safe(procedural_collection, [("instruction_id", 1)], unique=True)
    await create_index_safe(procedural_collection, [("agent_id", 1)])
    await create_index_safe(procedural_collection, [("instruction_type", 1)])
    await create_index_safe(procedural_collection, [("priority", -1)])
    print("     ✓ Procedural indexes created")
    
    # Insert sample procedural memory
    sample_procedure = {
        "instruction_id": "faucet-installation-001",
        "agent_id": None,  # Shared across all agents
        "brand_id": brand_slug,
        "instruction_type": "workflow",
        "name": "Faucet Installation Process",
        "description": "Step-by-step guide for installing bathroom faucets",
        "steps": [
            {
                "step_number": 1,
                "action": "Turn off water supply to the sink",
                "conditions": {},
                "next_step": 2
            },
            {
                "step_number": 2,
                "action": "Remove old faucet if replacing",
                "conditions": {"if": "replacing_existing == true"},
                "next_step": 3
            },
            {
                "step_number": 3,
                "action": "Clean the mounting surface",
                "conditions": {},
                "next_step": 4
            },
            {
                "step_number": 4,
                "action": "Install new faucet according to manufacturer instructions",
                "conditions": {},
                "next_step": 5
            },
            {
                "step_number": 5,
                "action": "Turn on water supply and check for leaks",
                "conditions": {},
                "next_step": "complete"
            }
        ],
        "conditions": {
            "apply_when": "product_type == 'faucet' AND query_contains('install')",
            "required_context": ["product_type", "installation"]
        },
        "priority": 5,
        "created_at": datetime.utcnow()
    }
    await procedural_collection.update_one(
        {"instruction_id": sample_procedure["instruction_id"]},
        {"$setOnInsert": sample_procedure},
        upsert=True
    )
    print("     ✓ Sample installation workflow created")
    
    # ========================================================================
    # 5. GRAPH MEMORY
    # ========================================================================
    print("\n🔗 5. GRAPH MEMORY")
    
    graph_collection = brand_db.graph_memory
    print("  ├─ graph_memory")
    
    # Use 'id' for uniqueness, and make it sparse to allow for different document types
    await create_index_safe(graph_collection, [("id", 1)], unique=True, sparse=True)
    await create_index_safe(graph_collection, [("rule_type", 1)])
    await create_index_safe(graph_collection, [("enabled", 1)])
    await create_index_safe(graph_collection, [("priority", -1)])
    await create_index_safe(graph_collection, [("severity", 1)])
    await create_index_safe(graph_collection, [("trigger_keywords", 1)])
    print("  │  ✓ Graph indexes created")
    
    # Seed default escalation rules
    default_escalations = [
        {
            "id": "high-severity-escalation",
            "rule_type": "escalation",
            "enabled": True,
            "conditions": {
                "all": [
                    {"field": "severity", "operator": "equals", "value": "high"},
                    {"field": "status", "operator": "not_equals", "value": "resolved"}
                ]
            },
            "actions": {
                "notify": ["support", "management"],
                "change_status": "escalated"
            },
            "priority": 1
        },
        {
            "id": "medium-severity-escalation",
            "rule_type": "escalation",
            "enabled": True,
            "conditions": {
                "all": [
                    {"field": "severity", "operator": "equals", "value": "medium"},
                    {"field": "status", "operator": "not_equals", "value": "resolved"}
                ]
            },
            "actions": {
                "notify": ["support"],
                "change_status": "pending_review"
            },
            "priority": 2
        },
        {
            "id": "low-severity-escalation",
            "rule_type": "escalation",
            "enabled": True,
            "conditions": {
                "all": [
                    {"field": "severity", "operator": "equals", "value": "low"},
                    {"field": "status", "operator": "not_equals", "value": "resolved"}
                ]
            },
            "actions": {
                "notify": [],
                "change_status": "resolved"
            },
            "priority": 3
        }
    ]
    for rule in default_escalations:
        await graph_collection.update_one(
            {"id": rule["id"]},
            {"$setOnInsert": rule},
            upsert=True
        )
    print("  │  ✓ Default escalation rules seeded")
    
    # ========================================================================
    # 6. RESOURCE MEMORY (NEW)
    # ========================================================================
    print("\n🔧 6. RESOURCE MEMORY (NEW)")
    
    resource_collection = brand_db.resource_memory
    print("  └─ resource_memory")
    
    await create_index_safe(resource_collection, [("resource_id", 1)], unique=True)
    await create_index_safe(resource_collection, [("resource_type", 1)])
    await create_index_safe(resource_collection, [("agent_id", 1)])
    print("     ✓ Resource indexes created")
    
    # Insert sample tool
    sample_tool = {
        "resource_id": "price_calculator",
        "resource_type": "tool",
        "name": "Price Calculator",
        "description": "Calculate total price with discounts and taxes",
        "agent_id": None,  # Available to all agents
        "schema": {
            "type": "function",
            "function": {
                "name": "calculate_price",
                "description": "Calculate final price with discounts and taxes",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "base_price": {"type": "number"},
                        "discount_percent": {"type": "number"},
                        "tax_percent": {"type": "number"}
                    },
                    "required": ["base_price"]
                }
            }
        },
        "enabled": True,
        "created_at": datetime.utcnow()
    }
    await resource_collection.update_one(
        {"resource_id": sample_tool["resource_id"]},
        {"$setOnInsert": sample_tool},
        upsert=True
    )
    print("     ✓ Sample tool registered")
    
    # ========================================================================
    # 7. KNOWLEDGE VAULT (NEW - Encrypted)
    # ========================================================================
    print("\n🔐 7. KNOWLEDGE VAULT (NEW)")
    
    vault_collection = brand_db.knowledge_vault
    print("  └─ knowledge_vault")
    
    await create_index_safe(vault_collection, [("vault_id", 1)], unique=True)
    await create_index_safe(vault_collection, [("data_type", 1)])
    await create_index_safe(vault_collection, [("user_id", 1)])
    await create_index_safe(vault_collection, [("encrypted", 1)])
    print("     ✓ Vault indexes created")
    
    # Insert sample vault entry
    sample_vault = {
        "vault_id": "pii_vault_001",
        "data_type": "pii",
        "user_id": "user_123",
        "encrypted": True,
        "encryption_method": "AES256-GCM",
        "kms_key_id": "aws-kms-key-id-placeholder",
        "encrypted_data": "encrypted_blob_placeholder",  # Actual encrypted data
        "redacted_abstract": "User's phone number (encrypted)",
        "access_level": "restricted",
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(days=365)  # 1 year
    }
    await vault_collection.update_one(
        {"vault_id": sample_vault["vault_id"]},
        {"$setOnInsert": sample_vault},
        upsert=True
    )
    print("     ✓ Sample vault entry created")
    
    # ========================================================================
    # 8. SUMMARY
    # ========================================================================
    print("\n" + "="*60)
    print("✅ SETUP COMPLETE!")
    print("="*60)
    
    # List all collections
    collections = await brand_db.list_collection_names()
    print(f"\n📊 Collections in {brand_slug}:")
    for coll in sorted(collections):
        count = await brand_db[coll].count_documents({})
        print(f"  ├─ {coll}: {count} documents")
    
    print("\n⚠️  MANUAL STEP REQUIRED:")
    print("  Create Atlas Vector Search Index on knowledge_base:")
    print(f"  1. Go to MongoDB Atlas UI")
    print(f"  2. Navigate to {brand_slug} database")
    print(f"  3. Select knowledge_base collection")
    print(f"  4. Create Search Index:")
    print(f"     - Name: vector_index")
    print(f"     - Type: Vector Search")
    print(f"     - Field: embedding")
    print(f"     - Dimensions: 1024")
    print(f"     - Similarity: cosine")
    
    client.close()


async def main():
    parser = argparse.ArgumentParser(description='Setup brand memory layers')
    parser.add_argument('--brand-slug', required=True, help='Brand slug (e.g., essco-bathware)')
    args = parser.parse_args()
    
    await setup_brand_memory_layers(args.brand_slug)


if __name__ == "__main__":
    asyncio.run(main())
