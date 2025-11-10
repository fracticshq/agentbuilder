#!/usr/bin/env python3
"""
Verify the Mirix-inspired memory layer setup
"""
import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Load from correct path
env_path = os.path.join(os.path.dirname(__file__), '..', 'apps', 'api', '.env')
load_dotenv(env_path)


async def verify_memory_layers(brand_slug: str):
    mongodb_uri = os.getenv("MONGODB_URI")
    if not mongodb_uri:
        raise ValueError("MONGODB_URI not found in environment")
    
    client = AsyncIOMotorClient(mongodb_uri)
    brand_db = client[brand_slug]
    
    print(f"\n🔍 Verifying Memory Layers for: {brand_slug}\n")
    print("=" * 80)
    
    # 1. Semantic Memory
    print("\n📚 1. SEMANTIC MEMORY")
    kb_count = await brand_db.knowledge_base.count_documents({})
    sources_count = await brand_db.knowledge_sources.count_documents({})
    print(f"  ├─ knowledge_base: {kb_count} documents")
    print(f"  └─ knowledge_sources: {sources_count} sources")
    
    # Show sample source
    sample_source = await brand_db.knowledge_sources.find_one({})
    if sample_source:
        print(f"     Sample source: {sample_source.get('name')} ({sample_source.get('source_type')})")
    
    # 2. Core Memory
    print("\n💬 2. CORE MEMORY")
    conv_count = await brand_db.conversations.count_documents({})
    summary_count = await brand_db.short_term_summaries.count_documents({})
    print(f"  ├─ conversations: {conv_count} active (TTL: 72h)")
    print(f"  └─ short_term_summaries: {summary_count} summaries")
    
    # 3. Episodic Memory
    print("\n🧠 3. EPISODIC MEMORY")
    episodic_count = await brand_db.episodic_memory.count_documents({})
    high_conf_count = await brand_db.episodic_memory.count_documents({"confidence": {"$gte": 0.8}})
    print(f"  └─ episodic_memory: {episodic_count} user facts (TTL: 90d)")
    print(f"     High confidence (≥0.8): {high_conf_count}")
    
    # 4. Procedural Memory
    print("\n⚙️  4. PROCEDURAL MEMORY")
    proc_count = await brand_db.procedural_memory.count_documents({})
    workflows = await brand_db.procedural_memory.count_documents({"instruction_type": "workflow"})
    sops = await brand_db.procedural_memory.count_documents({"instruction_type": "sop"})
    print(f"  └─ procedural_memory: {proc_count} instructions")
    print(f"     Workflows: {workflows} | SOPs: {sops}")
    
    # Show sample workflow
    sample_proc = await brand_db.procedural_memory.find_one({"instruction_type": "workflow"})
    if sample_proc:
        print(f"     Sample: {sample_proc.get('name')} ({len(sample_proc.get('steps', []))} steps)")
    
    # 5. Graph Memory
    print("\n🕸️  5. GRAPH MEMORY")
    graph_count = await brand_db.graph_memory.count_documents({})
    print(f"  └─ graph_memory: {graph_count} rules/policies")
    
    # Check legacy escalation triggers
    escalation_count = await brand_db.escalation_triggers.count_documents({})
    if escalation_count > 0:
        print(f"     Legacy escalation_triggers: {escalation_count} (consider migrating to graph_memory)")
    
    # 6. Resource Memory
    print("\n🔧 6. RESOURCE MEMORY")
    resource_count = await brand_db.resource_memory.count_documents({})
    tools = await brand_db.resource_memory.count_documents({"resource_type": "tool"})
    apis = await brand_db.resource_memory.count_documents({"resource_type": "api"})
    print(f"  └─ resource_memory: {resource_count} resources")
    print(f"     Tools: {tools} | APIs: {apis}")
    
    # Show sample tool
    sample_tool = await brand_db.resource_memory.find_one({"resource_type": "tool"})
    if sample_tool:
        print(f"     Sample: {sample_tool.get('name')} - {sample_tool.get('description')}")
    
    # 7. Knowledge Vault
    print("\n🔐 7. KNOWLEDGE VAULT")
    vault_count = await brand_db.knowledge_vault.count_documents({})
    encrypted_count = await brand_db.knowledge_vault.count_documents({"encrypted": True})
    print(f"  └─ knowledge_vault: {vault_count} entries")
    print(f"     Encrypted: {encrypted_count}")
    
    # Check indexes
    print("\n📑 INDEX VERIFICATION")
    print("=" * 80)
    
    collections = [
        ("knowledge_base", ["text_index", "metadata.content_type_1"]),
        ("conversations", ["conversation_id_1", "created_at_1"]),
        ("episodic_memory", ["user_id_1", "created_at_1"]),
        ("procedural_memory", ["instruction_id_1", "instruction_type_1"]),
        ("graph_memory", ["rule_id_1", "rule_type_1"]),
        ("resource_memory", ["resource_id_1", "resource_type_1"]),
        ("knowledge_vault", ["vault_id_1", "encrypted_1"])
    ]
    
    for coll_name, expected_indexes in collections:
        indexes = await brand_db[coll_name].index_information()
        index_names = list(indexes.keys())
        print(f"\n{coll_name}:")
        for idx in expected_indexes:
            status = "✓" if idx in index_names else "✗"
            print(f"  {status} {idx}")
    
    # Check for Vector Index (must be done manually in Atlas UI)
    print("\n⚠️  VECTOR SEARCH INDEX:")
    print("  Atlas Vector Search index must be created manually in Atlas UI")
    print("  Collection: knowledge_base")
    print("  Name: vector_index")
    print("  Field: embedding (1024 dimensions, cosine)")
    
    print("\n" + "=" * 80)
    print("✅ Verification Complete!\n")
    
    client.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Verify memory layer setup")
    parser.add_argument("--brand-slug", default="essco-bathware", help="Brand slug")
    args = parser.parse_args()
    
    asyncio.run(verify_memory_layers(args.brand_slug))
