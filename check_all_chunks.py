#!/usr/bin/env python3
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
client = MongoClient(os.getenv('MONGODB_URI'))
db = client['essco_agent']
kb = db['knowledge_base']

total = kb.count_documents({})
print(f'📊 Total chunks in knowledge_base: {total}')

if total > 0:
    print('\n📋 Sample documents:')
    for i, doc in enumerate(kb.find().limit(3), 1):
        print(f'\nDocument {i}:')
        print(f'  _id: {doc.get("_id")}')
        print(f'  doc_id: {doc.get("doc_id")}')
        print(f'  brand_id: {doc.get("brand_id")}')
        print(f'  content_type: {doc.get("content_type")}')
        print(f'  has product_data: {"product_data" in doc}')
        if 'product_data' in doc and doc['product_data']:
            print(f'  product_data.sku: {doc["product_data"].get("sku")}')
else:
    print('\n⚠️  Database is empty! Background processing may have failed.')
    print('\n🔍 Check API server logs for errors.')
