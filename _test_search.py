import asyncio
from app.connections import connection_manager
from app.config import Settings

async def main():
    await connection_manager.connect_mongodb()
    settings = Settings()
    
    # Test direct vector search with a simple text match first
    client = connection_manager.mongodb_client
    db = client['soundtrails']
    
    # 1. Count all product chunks
    total = await db.knowledge_base.count_documents({'content_type': 'product'})
    print(f"Total product chunks: {total}")
    
    # 2. Check if embeddings exist
    sample = await db.knowledge_base.find_one({'content_type': 'product', 'embeddings': {'$exists': True}})
    if sample:
        emb_len = len(sample.get('embeddings', []))
        print(f"Embeddings present, dimension: {emb_len}")
    else:
        print("NO EMBEDDINGS FOUND - products have no vector data!")
    
    # 3. Check for amplifier in content field (text match)
    amp_text = await db.knowledge_base.count_documents({
        'content_type': 'product',
        'content': {'$regex': 'amplif', '$options': 'i'}
    })
    print(f"Amplifier chunks (text match): {amp_text}")
    
    # 4. Check Atlas vector index name
    indexes = await db.knowledge_base.list_indexes().to_list(20)
    for idx in indexes:
        print(f"Index: {idx.get('name')} type={idx.get('type','regular')}")

asyncio.run(main())
