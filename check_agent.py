#!/usr/bin/env python3
from pymongo import MongoClient
from bson import ObjectId
import os
from dotenv import load_dotenv

load_dotenv()

mongo_uri = os.getenv('MONGO_URI')
client = MongoClient(mongo_uri)

# Check BOTH system database and brand database
system_db = client['agent-builder']
brand_db = client['essco-bathware']

print('Checking system database (agent-builder)...')
agent = system_db.agents.find_one({'id': '912f6fd5-5084-4d83-90ff-ed3283df2699'})

if not agent:
    print('Not in system database, checking brand database (essco-bathware)...')
    agent = brand_db.agents.find_one({'id': '912f6fd5-5084-4d83-90ff-ed3283df2699'})

if agent:
    print('✅ Found agent!')
    print(f"id field: {agent.get('id')}")
    print(f"Name: {agent.get('name')}")
    print(f"Brand: {agent.get('brand_slug')}")
    print()
    
    prompt = agent.get('system_prompt', '')
    print(f'System Prompt Length: {len(prompt)} characters')
    print()
    
    if '<product_info>' in prompt:
        print('✅ System prompt contains <product_info> tags')
        count = prompt.count('<product_info>')
        print(f'   Found {count} example(s) in prompt')
    else:
        print('❌ System prompt missing <product_info> tags')
        print()
        print('First 500 chars of prompt:')
        print(prompt[:500])
else:
    print('❌ Agent not found')
    print()
    print('All agents:')
    for a in system_db.agents.find():
        print(f"  - _id: {a['_id']}, id: {a.get('id')}, name: {a.get('name')}")
