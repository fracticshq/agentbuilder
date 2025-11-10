#!/usr/bin/env python3
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

mongo_uri = os.getenv('MONGO_URI')
client = MongoClient(mongo_uri)
system_db = client['agent-builder']

# Read the full system prompt
with open('suggested_system_prompt.md', 'r', encoding='utf-8') as f:
    system_prompt = f.read()

print(f"Loaded prompt: {len(system_prompt)} characters")

# Update the EXISTING agent
result = system_db.agents.update_one(
    {'id': '0f603b3f-3023-431a-95bd-3a6fff7cdfb9'},
    {'$set': {'system_prompt': system_prompt}}
)

print(f"✅ Updated agent")
print(f"   Matched: {result.matched_count}")
print(f"   Modified: {result.modified_count}")

# Verify
agent = system_db.agents.find_one({'id': '0f603b3f-3023-431a-95bd-3a6fff7cdfb9'})
new_prompt = agent.get('system_prompt', '')
print(f"✅ New prompt length: {len(new_prompt)} characters")

if '<product_info>' in new_prompt:
    print(f"✅ Contains <product_info> tags")
else:
    print("❌ Missing <product_info> tags!")

print("\nUse this URL:")
print("http://localhost:5173/?agent_id=0f603b3f-3023-431a-95bd-3a6fff7cdfb9")
