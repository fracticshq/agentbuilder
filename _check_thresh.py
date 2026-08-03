import asyncio
from app.connections import connection_manager

async def main():
    await connection_manager.connect_mongodb()
    db = connection_manager.get_system_db()
    agents = await db.agents.find({'status': 'active'}).to_list(20)
    for a in agents:
        r = a.get('configuration', {}).get('rag', {}).get('retrieval', {})
        print(f"{a['name']}: threshold={r.get('similarity_threshold')} top_k={r.get('top_k')}")
    
    # Also check how many amplifier products exist in soundtrails
    client = connection_manager.mongodb_client
    for brand in ['soundtrails', 'aandindia']:
        db2 = client[brand]
        import re
        names = await db2.knowledge_base.distinct('product_data.name', {'content_type': 'product'})
        amps = [n for n in names if re.search(r'amplif', n or '', re.I)]
        print(f"\n{brand}: {len(names)} total products, {len(amps)} amplifiers")
        for n in amps[:5]:
            print(f"  - {n}")

asyncio.run(main())
