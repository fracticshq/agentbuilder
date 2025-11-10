#!/usr/bin/env python3
"""Check MongoDB database status."""
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
client = MongoClient(os.getenv('MONGODB_URI'))

print('✅ MongoDB Connection Successful!\n')
print('📊 Database Info:')
db = client['essco_agent']
collections = db.list_collection_names()
print(f'  Database: essco_agent')
print(f'  Collections: {collections}')
print()

if 'knowledge_base' in collections:
    kb = db['knowledge_base']
    total = kb.count_documents({})
    by_brand = {}
    for doc in kb.find({}, {'brand_id': 1}):
        brand = doc.get('brand_id', 'unknown')
        by_brand[brand] = by_brand.get(brand, 0) + 1
    
    print(f'📚 Knowledge Base Collection:')
    print(f'  Total documents: {total}')
    if by_brand:
        print(f'  By brand:')
        for brand, count in by_brand.items():
            print(f'    - {brand}: {count} chunks')
    else:
        print(f'  ✨ Empty - Ready for fresh upload!')
else:
    print('⚠️  knowledge_base collection does not exist yet')
    print('   It will be created on first upload')
